"""Local HTTP endpoint applications talk to. Routes jobs to verified images under a policy."""
import os
from pathlib import Path
from typing import Any, Optional

import base64
import mimetypes
import tempfile
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import manifest as mf
from . import registry
from .gate import audit, check
from . import auth
from .paths import AUDIT
from .policy import Policy
from .sandbox import run_job, wants_gpu, RunResult
import json as _json
import urllib.request

LAUNCHER = os.environ.get("SEALED_LAUNCHER", "").rstrip("/")   # e.g. http://launcher:8473 ; empty = run sandboxes from this process


def execute(image: str, iid: str, entry: dict, op: str, input_value, params, policy: Policy, gpu: bool) -> RunResult:
    if not LAUNCHER:
        return run_job(image, op, input_value, params, memory=policy.memory, gpu=gpu, timeout=policy.timeout_seconds, warm=policy.warm)
    body = _json.dumps({"image_id": iid, "op": op, "input": input_value, "params": params or {}, "memory": policy.memory,
                        "timeout": policy.timeout_seconds, "warm": policy.warm}).encode()
    req = urllib.request.Request(LAUNCHER + "/run", data=body, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=policy.timeout_seconds + 30) as r:
            d = _json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, _json.loads(e.read() or b"{}").get("detail", str(e)))
    except Exception as e:
        raise HTTPException(503, f"launcher unreachable: {e}")
    return RunResult(ok=d["ok"], output=d.get("output"), error=d.get("error"), stderr=d.get("stderr", ""), duration=d.get("duration", 0))
from .pool import POOL
from .documents import process_file, whole_text

from .paths import HOME as _HOME
POLICY_DIR = Path(os.environ.get("SEALED_POLICY_DIR", Path(__file__).resolve().parents[2] / "policies"))
if (_HOME / "policies").exists() and any((_HOME / "policies").glob("*.yaml")):
    POLICY_DIR = _HOME / "policies"          # policies distributed by the control plane take precedence
GPU_FLAG = os.environ.get("SEALED_GPU", "0") == "1"

app = FastAPI(title="sealed gateway", version="0.0.1")


def client(request: Request, authorization: str = Header("")) -> dict:
    """API-key check. No keys configured = dev mode, localhost only (enforced at startup in cli.serve)."""
    keys = auth.load()
    if not keys:
        return {"label": "local-dev", "policies": ["*"]}
    entry = auth.check(authorization.removeprefix("Bearer ").strip())
    if not entry:
        raise HTTPException(401, "API key required: Authorization: Bearer sk_...")
    return entry


def policy_for(c: dict, name: str) -> Policy:
    if "*" not in c["policies"] and name not in c["policies"]:
        raise HTTPException(403, f"client '{c['label']}' may not use policy '{name}'")
    return load_policy(name)


class Job(BaseModel):
    app: str
    op: str
    input: Any
    params: Optional[dict] = None
    policy: str = "confidential"


def load_policy(name: str) -> Policy:
    p = POLICY_DIR / f"{name}.yaml"
    if not p.exists():
        raise HTTPException(404, f"unknown policy '{name}'")
    return Policy.load(p)


@app.get("/health")
def health():
    return {"ok": True, "auth": "api-key" if auth.load() else "localhost-dev"}


@app.get("/v1/apps")
def apps(c: dict = Depends(client)):
    return registry.load()


@app.get("/v1/policies")
def policies(c: dict = Depends(client)):
    return sorted(p.stem for p in POLICY_DIR.glob("*.yaml"))


@app.get("/v1/audit")
def audit_tail(n: int = 50, c: dict = Depends(client)):
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text().splitlines()[-n:]
    return [__import__("json").loads(l) for l in lines]


@app.get("/v1/pool")
def pool_status(c: dict = Depends(client)):
    if LAUNCHER:
        with urllib.request.urlopen(LAUNCHER + "/pool", timeout=10) as r:
            return _json.loads(r.read())
    return POOL.status()


def _resolve(policy: Policy, app_name: str, op: str):
    if not policy.allows(op):
        raise HTTPException(403, f"operation '{op}' not allowed by policy '{policy.name}'")
    hit = registry.find_by_name(app_name)
    if hit:
        iid, entry = hit
        image = entry["image"]
        if op not in entry["operations"]:
            raise HTTPException(400, f"app '{app_name}' does not declare operation '{op}'")
        if not LAUNCHER and mf.image_id(image) != iid:      # with a launcher, the launcher does this check
            raise HTTPException(409, f"image '{image}' changed since verification; run `sealed verify` again")
        return image, iid, wants_gpu(entry, GPU_FLAG), entry
    if policy.require_verified:
        raise HTTPException(403, f"app '{app_name}' is not verified and policy '{policy.name}' requires verified apps")
    return app_name, mf.image_id(app_name) or "unknown", wants_gpu(None, GPU_FLAG), {}


@app.post("/v1/files")
async def submit_file(file: UploadFile = File(...), app_name: str = Form(..., alias="app"), op: str = Form("translate"),
                      params: str = Form("{}"), policy_name: str = Form("confidential", alias="policy"), c: dict = Depends(client)):
    """Upload a txt/md/docx/pdf. translate -> same format back; summarize/extract/classify -> JSON."""
    policy = policy_for(c, policy_name)
    image, iid, gpu, entry = _resolve(policy, app_name, op)
    prm = __import__("json").loads(params or "{}")
    tmp = Path(tempfile.mkdtemp(prefix="sealed-"))
    src = tmp / Path(file.filename or "input.txt").name
    src.write_bytes(await file.read())

    def call(text):
        res = execute(image, iid, entry, op, text, prm, policy, gpu)
        verdict = check(policy, op, text, res.output) if res.ok else None
        audit(policy, image, iid, op, text, res.output if res.ok else None,
              verdict or type("V", (), {"allowed": False, "reason": res.error})(), res.duration, res.ok, client=c["label"])
        if not res.ok:
            raise HTTPException(502, {"error": res.error, "stderr_tail": res.stderr[-500:]})
        if not verdict.allowed:
            raise HTTPException(403, {"blocked_by_gate": verdict.reason})
        return res.output

    in_type, out_type = entry.get("input", "text/plain"), entry.get("output", "text/plain")
    binary_in = not (in_type.startswith("text/") or in_type == "application/json")
    binary_out = not (out_type.startswith("text/") or out_type == "application/json")
    if binary_in or binary_out:
        payload = base64.b64encode(src.read_bytes()).decode() if binary_in else src.read_text(errors="replace")
        output = call(payload)
        if binary_out:
            ext = entry.get("output_extension") or (mimetypes.guess_extension(out_type) or ".bin").lstrip(".")
            dst = tmp / f"{src.stem}.{ext}"
            dst.write_bytes(base64.b64decode(output))
            return FileResponse(str(dst), filename=dst.name, media_type=out_type)
        return {"ok": True, "app": app_name, "image_id": iid, "op": op, "file": src.name, "output": output}
    if op == "translate":
        dst = tmp / f"{src.stem}.{prm.get('target', 'out')}{src.suffix}"
        dst = process_file(src, dst, call, policy.chunk_chars)
        return FileResponse(str(dst), filename=dst.name)
    return {"ok": True, "app": app_name, "image_id": iid, "op": op, "file": src.name, "output": call(whole_text(src))}


@app.post("/v1/jobs")
def submit(job: Job, c: dict = Depends(client)):
    policy = policy_for(c, job.policy)
    image, iid, gpu, entry = _resolve(policy, job.app, job.op)
    res = execute(image, iid, entry, job.op, job.input, job.params, policy, gpu)
    verdict = check(policy, job.op, job.input, res.output) if res.ok else None
    audit(policy, image, iid, job.op, job.input, res.output if res.ok else None,
          verdict or type("V", (), {"allowed": False, "reason": res.error})(), res.duration, res.ok, client=c["label"])
    if not res.ok:
        raise HTTPException(502, {"error": res.error, "stderr_tail": res.stderr[-500:]})
    if not verdict.allowed:
        raise HTTPException(403, {"blocked_by_gate": verdict.reason})
    return {"ok": True, "app": job.app, "image_id": iid, "op": job.op, "output": res.output, "seconds": round(res.duration, 2)}
