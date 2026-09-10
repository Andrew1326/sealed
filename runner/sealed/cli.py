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
from .verify import verify as _verify


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
def serve(host, port):
    """Start the local gateway."""
    import uvicorn
    click.echo(f"sealed home: {HOME}  allowlist: {ALLOWLIST}")
    uvicorn.run("sealed.gateway:app", host=host, port=port)


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
