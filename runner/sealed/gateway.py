"""Local HTTP endpoint applications talk to. Routes jobs to verified images under a policy."""
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import manifest as mf
from . import registry
from .gate import audit, check
from .paths import AUDIT
from .policy import Policy
from .sandbox import run_job

POLICY_DIR = Path(os.environ.get("SEALED_POLICY_DIR", Path(__file__).resolve().parents[2] / "policies"))
GPU = os.environ.get("SEALED_GPU", "0") == "1"

app = FastAPI(title="sealed gateway", version="0.0.1")


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


@app.get("/v1/apps")
def apps():
    return registry.load()


@app.get("/v1/policies")
def policies():
    return sorted(p.stem for p in POLICY_DIR.glob("*.yaml"))


@app.get("/v1/audit")
def audit_tail(n: int = 50):
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text().splitlines()[-n:]
    return [__import__("json").loads(l) for l in lines]


@app.post("/v1/jobs")
def submit(job: Job):
    policy = load_policy(job.policy)
    if job.op not in policy.allowed_ops:
        raise HTTPException(403, f"operation '{job.op}' not allowed by policy '{policy.name}'")
    hit = registry.find_by_name(job.app)
    if hit:
        iid, entry = hit
        image = entry["image"]
        if job.op not in entry["operations"]:
            raise HTTPException(400, f"app '{job.app}' does not declare operation '{job.op}'")
        if mf.image_id(image) != iid:
            raise HTTPException(409, f"image '{image}' changed since verification; run `sealed verify` again")
    elif policy.require_verified:
        raise HTTPException(403, f"app '{job.app}' is not verified and policy '{policy.name}' requires verified apps")
    else:
        image, iid = job.app, mf.image_id(job.app) or "unknown"
    res = run_job(image, job.op, job.input, job.params, memory=policy.memory, gpu=GPU, timeout=policy.timeout_seconds)
    verdict = check(policy, job.op, job.input, res.output) if res.ok else None
    audit(policy, image, iid, job.op, job.input, res.output if res.ok else None,
          verdict or type("V", (), {"allowed": False, "reason": res.error})(), res.duration, res.ok)
    if not res.ok:
        raise HTTPException(502, {"error": res.error, "stderr_tail": res.stderr[-500:]})
    if not verdict.allowed:
        raise HTTPException(403, {"blocked_by_gate": verdict.reason})
    return {"ok": True, "app": job.app, "image_id": iid, "op": job.op, "output": res.output, "seconds": round(res.duration, 2)}
