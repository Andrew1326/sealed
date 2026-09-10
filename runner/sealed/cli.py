import json
import sys
from pathlib import Path

import click

from . import manifest as mf
from . import registry
from .gate import audit, check
from .paths import ALLOWLIST, AUDIT, HOME
from .policy import Policy
from .sandbox import run_job, sandbox_args, wants_gpu
from .documents import process_file, whole_text
import base64
import mimetypes
from .verify import verify as _verify
from . import signing
from . import source as srcpkg
import os
import subprocess


@click.group()
def main():
    """sealed: run apps on confidential data with no way out."""


@main.command()
@click.argument("image")
@click.option("--gpu", is_flag=True, help="expose GPUs to the sandbox (still no network)")
@click.option("--skip-scan", is_flag=True)
def verify(image, gpu, skip_scan):
    """Run the admission pipeline on IMAGE and add it to the allowlist if it passes."""
    rep = _verify(image, gpu=gpu, skip_scan=skip_scan)
    sys.exit(0 if rep.passed else 1)


@main.command()
@click.argument("app")
@click.option("--op", required=True)
@click.option("--policy", "policy_path", default=None, help="policy yaml (default: policies/confidential.yaml)")
@click.option("--param", "-p", multiple=True, help="key=value")
@click.option("--file", "file_", type=click.Path(exists=True), help="input file: txt md csv docx pdf (or stdin)")
@click.option("--out", "out_", type=click.Path(), help="output file for translate on documents (same format as input)")
@click.option("--gpu", is_flag=True)
@click.option("--cold", is_flag=True, help="fresh container for this job instead of the warm pool")
@click.option("--unverified", is_flag=True, help="run an unverified image by name (non-confidential use only)")
def run(app, op, policy_path, param, file_, out_, gpu, cold, unverified):
    """Run one job: sealed run translate-marian --op translate -p source=en -p target=de --file contract.docx --out contract.de.docx"""
    pol = Policy.load(policy_path) if policy_path else Policy.load(Path(__file__).resolve().parents[2] / "policies" / "confidential.yaml")
    params = dict(kv.split("=", 1) for kv in param)
    hit = registry.find_by_name(app)
    entry = None
    if hit:
        iid, entry = hit
        image = entry["image"]
        if mf.image_id(image) != iid:
            click.echo(f"image {image} changed since verification, re-run `sealed verify {image}`", err=True)
            sys.exit(2)
    elif unverified and not pol.require_verified:
        image, iid = app, mf.image_id(app) or "unknown"
    else:
        click.echo(f"'{app}' is not a verified app (see `sealed apps`). Policy '{pol.name}' requires verified apps.", err=True)
        sys.exit(2)
    warm = pol.warm and not cold
    gpu = wants_gpu(entry, gpu)

    def call(text):
        res = run_job(image, op, text, params, memory=pol.memory, gpu=gpu, timeout=pol.timeout_seconds, warm=warm)
        if not res.ok:
            audit(pol, image, iid, op, text, None, type("V", (), {"allowed": False, "reason": res.error})(), res.duration, False)
            click.echo(f"app error: {res.error}\n{res.stderr[-800:]}", err=True)
            sys.exit(1)
        v = check(pol, op, text, res.output)
        audit(pol, image, iid, op, text, res.output, v, res.duration, True)
        if not v.allowed:
            click.echo(f"BLOCKED BY GATE: {v.reason}", err=True)
            sys.exit(3)
        return res.output

    in_type = (entry or {}).get("input", "text/plain")
    out_type = (entry or {}).get("output", "text/plain")
    binary_in = not (in_type.startswith("text/") or in_type == "application/json")
    binary_out = not (out_type.startswith("text/") or out_type == "application/json")
    if binary_in or binary_out:
        if not file_:
            click.echo("this app takes a file: use --file", err=True)
            sys.exit(2)
        payload = base64.b64encode(Path(file_).read_bytes()).decode() if binary_in else Path(file_).read_text()
        output = call(payload)
        if binary_out:
            ext = (entry or {}).get("output_extension") or (mimetypes.guess_extension(out_type) or ".bin").lstrip(".")
            dst = Path(out_) if out_ else Path(file_).with_suffix("." + ext)
            dst.write_bytes(base64.b64decode(output))
            click.echo(f"wrote {dst} ({dst.stat().st_size} bytes)")
        else:
            click.echo(output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2))
        return
    if file_ and Path(file_).suffix.lower() in (".docx", ".pdf", ".txt", ".md", ".csv") and op == "translate":
        src = Path(file_)
        dst = Path(out_) if out_ else src.with_name(f"{src.stem}.{params.get('target', 'out')}{src.suffix}")
        dst = process_file(src, dst, call, pol.chunk_chars, log=lambda m: click.echo(m, err=True))
        click.echo(f"wrote {dst}")
        return
    if file_:
        text = whole_text(Path(file_)) if Path(file_).suffix.lower() in (".docx", ".pdf") else Path(file_).read_text()
    else:
        text = sys.stdin.read()
    output = call(text)
    click.echo(output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2))


@main.command()
def apps():
    """List verified apps."""
    d = registry.load()
    if not d:
        click.echo("no verified apps. run: sealed verify <image>")
    for iid, e in d.items():
        click.echo(f"{e['name']:20} {e['version']:8} {','.join(e['operations']):30} {e['image']:32} {iid[:19]}…  verified {e['verified_at']}")


@main.command()
@click.argument("image_id")
def revoke(image_id):
    """Remove an image ID from the allowlist."""
    click.echo("removed" if registry.remove(image_id) else "not found")


@main.command()
@click.option("-n", default=20)
def audit_log(n):
    """Show the last N audit lines."""
    if AUDIT.exists():
        for l in AUDIT.read_text().splitlines()[-n:]:
            click.echo(l)


@main.command()
@click.argument("image")
def contract(image):
    """Print the exact docker command the sandbox uses for IMAGE."""
    click.echo(" ".join(sandbox_args(image)))


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8470)
@click.option("--cert", default=os.environ.get("SEALED_TLS_CERT", ""), help="TLS certificate (PEM). Empty = plain http.")
@click.option("--key", default=os.environ.get("SEALED_TLS_KEY", ""), help="TLS private key (PEM)")
def serve(host, port, cert, key):
    """Start the local gateway."""
    import uvicorn
    from . import auth
    if not auth.load() and host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("SEALED_ALLOW_NO_KEYS") != "1":
        click.echo(f"refusing to bind {host} without API keys. Create one: sealed keys create --label myapp", err=True)
        sys.exit(2)
    if host not in ("127.0.0.1", "localhost", "::1") and not cert and os.environ.get("SEALED_ALLOW_NO_TLS") != "1":
        click.echo(f"refusing to bind {host} without TLS. Run `sealed cert --host <name>` or set SEALED_ALLOW_NO_TLS=1 behind a TLS reverse proxy.", err=True)
        sys.exit(2)
    tls = f"tls {cert}" if cert else "plain http"
    if cert:
        from .certs import fingerprint
        click.echo(f"certificate fingerprint: {fingerprint(Path(cert).read_bytes())}")
    click.echo(f"sealed home: {HOME}  allowlist: {ALLOWLIST}  auth: {'api-key' if auth.load() else 'none (localhost dev mode)'}  {tls}")
    uvicorn.run("sealed.gateway:app", host=host, port=port, ssl_certfile=cert or None, ssl_keyfile=key or None)


@main.command()
def tools():
    """Install the static strace used by `verify` for intent detection (extracted from alpine)."""
    import subprocess
    d = HOME / "tools"
    d.mkdir(exist_ok=True)
    subprocess.run(["docker", "run", "--rm", "-v", f"{d}:/out", "alpine:3.20", "sh", "-c",
                    "apk add -q strace && cp /usr/bin/strace /lib/ld-musl-x86_64.so.1 /out/ && "
                    "for l in $(ldd /usr/bin/strace | awk '/=>/{print $3}'); do cp -L $l /out/; done; chmod a+rx /out/*"], check=True)
    click.echo(f"installed to {d}: " + ", ".join(sorted(p.name for p in d.iterdir())))


@main.command()
def pool():
    """Show warm containers (only meaningful inside a long-running `sealed serve`)."""
    from .pool import POOL
    click.echo(json.dumps(POOL.status(), indent=2))


@main.command()
def prune():
    """Drop allowlist entries whose image ID no longer exists or whose tag now points elsewhere."""
    d = registry.load()
    for iid, e in list(d.items()):
        if mf.image_id(e["image"]) != iid:
            registry.remove(iid)
            click.echo(f"pruned {e['name']} {e['version']} ({iid[:19]}…)")


DEFAULT_REGISTRY = os.environ.get("SEALED_REGISTRY", str(Path(__file__).resolve().parents[2] / "registry"))


@main.command()
@click.option("--name", default="publisher")
def keygen(name):
    """Create an Ed25519 publisher key in ~/.sealed/keys and trust it locally."""
    path, pub = signing.keygen(name)
    signing.trust(pub, f"local:{name}")
    click.echo(f"private key {path}\npublic key  {pub}\n(trusted locally; share the public key with users, they run: sealed trust <key> <label>)")


@main.command()
@click.argument("pubkey")
@click.argument("label")
def trust(pubkey, label):
    """Trust a publisher's public key."""
    signing.trust(pubkey, label)
    click.echo(f"trusted {label}")


@main.command()
@click.argument("app_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--image", required=True, help="the locally built and VERIFIED image of this source (proof the publisher ran verify)")
@click.option("--build-arg", "build_args", multiple=True, help="key=value build args users need (e.g. TORCH=cu128 for a CUDA variant)")
@click.option("--registry", "registry_dir", default=DEFAULT_REGISTRY, help="registry directory to write into")
@click.option("--key", default="publisher")
def sign(app_dir, image, build_args, registry_dir, key):
    """Package APP_DIR (Dockerfile, handler, manifest, fixtures) and sign it. Users build it themselves."""
    iid = mf.image_id(image)
    entry = registry.lookup(iid) if iid else None
    if not entry:
        click.echo(f"{image} is not in the allowlist. Build it from {app_dir} and run `sealed verify {image}` first.", err=True)
        sys.exit(2)
    man = json.loads((Path(app_dir) / "manifest.json").read_text())
    if man["name"] != entry["name"] or man["version"] != entry["version"]:
        click.echo(f"{app_dir} manifest is {man['name']} {man['version']} but {image} was verified as {entry['name']} {entry['version']}", err=True)
        sys.exit(2)
    data = srcpkg.pack(Path(app_dir))
    reg = Path(registry_dir); reg.mkdir(parents=True, exist_ok=True)
    fname = f"{man['name']}-{man['version']}.src.tar.gz"
    (reg / fname).write_bytes(data)
    e = signing.sign_entry(signing.make_entry(man, fname, srcpkg.sha256(data), dict(kv.split("=", 1) for kv in build_args), iid, entry["report"]), key)
    path = signing.write_registry_entry(reg, e)
    click.echo(f"signed {man['name']} {man['version']}  source {fname} ({len(data)//1024} KB, sha256 {srcpkg.sha256(data)[:16]}…) -> {path}")


@main.command()
@click.option("--registry", "base", default=DEFAULT_REGISTRY, help="registry URL or directory")
def catalog(base):
    """List apps available in the registry."""
    idx = signing.fetch_index(base)
    for a in idx["apps"]:
        gpu = a["requires"].get("gpu", "none")
        click.echo(f"{a['name']:20} {a['version']:12} {','.join(a['operations']):40} gpu={gpu:8} mem={a['requires'].get('memory','?')}  {a['description'][:60]}")


@main.command()
@click.argument("name")
@click.option("--registry", "base", default=DEFAULT_REGISTRY, help="registry URL or directory")
@click.option("--version", "version", default=None)
@click.option("--build-arg", "build_args", multiple=True, help="override/add docker build args (key=value)")
@click.option("--gpu", is_flag=True, help="verify with GPU access (use with a CUDA build arg if the app offers one)")
@click.option("--tag", default=None, help="image tag for the local build (default sealed/<name>:<version>[-<build args>])")
def install(name, base, version, build_args, gpu, tag):
    """Fetch a signed source package, check signature and hash, build the image locally, run verify, allow."""
    idx = signing.fetch_index(base)
    cands = [a for a in idx["apps"] if a["name"] == name and (version is None or a["version"] == version)]
    if not cands:
        click.echo(f"no app '{name}' in registry {base}", err=True)
        sys.exit(2)
    a = max(cands, key=lambda x: x["version"])
    e = signing.fetch_entry(base, a["entry"])
    who, why = signing.verify_entry(e)
    if why == "bad-signature":
        click.echo(f"REFUSED: entry for {name} {e['version']} has an INVALID signature. The entry was modified after signing.", err=True)
        sys.exit(3)
    if why:
        click.echo(f"REFUSED: entry for {name} {e['version']} is not signed by a trusted key (publisher key {e.get('publisher_key','?')[:16]}…).\n"
                   f"If you trust this publisher: sealed trust {e.get('publisher_key')} <label>", err=True)
        sys.exit(3)
    click.echo(f"signature ok: {name} {e['version']} signed by {who}")
    data = signing.fetch(base.rstrip("/") + "/" + e["source"]["file"])
    if srcpkg.sha256(data) != e["source"]["sha256"]:
        click.echo(f"REFUSED: source package hash {srcpkg.sha256(data)[:16]}… does not match signed {e['source']['sha256'][:16]}…", err=True)
        sys.exit(5)
    click.echo(f"source package hash ok ({len(data)//1024} KB)")
    build_dir = HOME / "build" / f"{name}-{e['version']}"
    if build_dir.exists():
        import shutil
        shutil.rmtree(build_dir)
    srcpkg.unpack(data, build_dir)
    args = dict(e["source"].get("build_args") or {})
    args.update(dict(kv.split("=", 1) for kv in build_args))
    tag = tag or f"sealed/{name}:{e['version']}" + ("-" + "-".join(v for v in args.values()) if args else "")
    cmd = ["docker", "build", "-t", tag] + sum((["--build-arg", f"{k}={v}"] for k, v in args.items()), []) + [str(build_dir)]
    click.echo(f"building {tag} from {build_dir} (downloads pinned model revisions on first build)…")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        click.echo("build failed", err=True)
        sys.exit(4)
    rep = _verify(tag, gpu=gpu, skip_scan=True)
    sys.exit(0 if rep.passed else 1)


@main.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8473)
def launcher(host, port):
    """Start the launcher: the only process that needs the Docker socket. Pair with `serve` via SEALED_LAUNCHER."""
    import uvicorn
    uvicorn.run("sealed.launcher:app", host=host, port=port)


@main.command()
@click.argument("control")
@click.argument("token")
@click.option("--fingerprint", default=os.environ.get("SEALED_CONTROL_FINGERPRINT", ""),
              help="pin the control plane's certificate (sha256:...); required for self-signed TLS")
def enroll(control, token, fingerprint):
    """Enrol this runner with a control plane: sealed enroll https://control.example.com enr_xxx --fingerprint sha256:..."""
    from . import agent
    import urllib.error
    if control.startswith("http://") and "127.0.0.1" not in control and "localhost" not in control:
        click.echo("warning: plain http to a remote control plane. Use https and --fingerprint.", err=True)
    try:
        st = agent.enroll(control, token, fingerprint)
    except urllib.error.HTTPError as e:
        click.echo(f"enrolment refused: HTTP {e.code} {e.read().decode(errors='replace')[:200]}", err=True)
        sys.exit(3)
    except Exception as e:
        msg = str(e)
        hint = ("\nself-signed certificate? pin it: --fingerprint sha256:... (shown on the control plane's enrol-token page)"
                if "certificate" in msg.lower() or "ssl" in msg.lower() else "")
        click.echo(f"enrolment failed: {msg[:300]}{hint}", err=True)
        sys.exit(3)
    click.echo(f"enrolled as {st['runner_id']} with {st['control']} (state in {agent.STATE})")


@main.command()
@click.option("--interval", default=30)
@click.option("--once", is_flag=True)
def agent(interval, once):
    """Heartbeat to the control plane, pull policy/trust config, push audit metadata."""
    from . import agent as ag
    if once:
        click.echo(json.dumps(ag.heartbeat_once(json.loads(ag.STATE.read_text()))))
    else:
        ag.run(interval)


@main.group()
def keys():
    """Gateway API keys."""


@keys.command("create")
@click.option("--label", required=True)
@click.option("--policy", "policies", multiple=True, help="restrict to these policies (default: any)")
def keys_create(label, policies):
    from . import auth
    key = auth.create(label, list(policies) or None)
    click.echo(f"{key}\n(shown once; stored hashed in {auth.KEYS})")


@keys.command("list")
def keys_list():
    from . import auth
    for h, e in auth.load().items():
        click.echo(f"{e['label']:24} policies={','.join(e['policies']):20} created {e['created']}  {h[:12]}…")


@keys.command("revoke")
@click.argument("label")
def keys_revoke(label):
    from . import auth
    click.echo(f"revoked {auth.revoke(label)} key(s) labelled {label}")


@main.command()
@click.option("--host", "hosts", multiple=True, required=True, help="hostname or IP the gateway is reached at (repeatable)")
@click.option("--out", default=str(HOME / "tls"))
def cert(hosts, out):
    """Generate a self-signed TLS certificate for the gateway."""
    from . import certs
    c, k, fp = certs.write(Path(out), list(hosts), "gateway")
    click.echo(f"cert {c}\nkey  {k}\nfingerprint {fp}\nstart with: sealed serve --host 0.0.0.0 --cert {c} --key {k}")
