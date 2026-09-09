import json
import sys
from pathlib import Path

import click

from . import manifest as mf
from . import registry
from .gate import audit, check
from .paths import ALLOWLIST, AUDIT, HOME
from .policy import Policy
from .sandbox import run_job, sandbox_args
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
@click.option("--file", "file_", type=click.Path(exists=True), help="read input from file instead of stdin")
@click.option("--gpu", is_flag=True)
@click.option("--unverified", is_flag=True, help="run an unverified image by name (non-confidential use only)")
def run(app, op, policy_path, param, file_, gpu, unverified):
    """Run one job: sealed run translate-marian --op translate -p source=en -p target=de --file doc.txt"""
    pol = Policy.load(policy_path) if policy_path else Policy.load(Path(__file__).resolve().parents[2] / "policies" / "confidential.yaml")
    params = dict(kv.split("=", 1) for kv in param)
    text = Path(file_).read_text() if file_ else sys.stdin.read()
    hit = registry.find_by_name(app)
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
    res = run_job(image, op, text, params, memory=pol.memory, gpu=gpu, timeout=pol.timeout_seconds)
    if not res.ok:
        audit(pol, image, iid, op, text, None, type("V", (), {"allowed": False, "reason": res.error})(), res.duration, False)
        click.echo(f"app error: {res.error}\n{res.stderr[-800:]}", err=True)
        sys.exit(1)
    v = check(pol, op, text, res.output)
    audit(pol, image, iid, op, text, res.output, v, res.duration, True)
    if not v.allowed:
        click.echo(f"BLOCKED BY GATE: {v.reason}", err=True)
        sys.exit(3)
    click.echo(res.output if isinstance(res.output, str) else json.dumps(res.output, ensure_ascii=False, indent=2))


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
