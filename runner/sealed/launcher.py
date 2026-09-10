"""Launcher: the only process that holds the Docker socket.

It accepts one kind of request: run operation X of ALLOWLISTED image ID Y on this input, under the sandbox
contract. The image reference comes from the allowlist, never from the request. A compromised gateway can
therefore only do what a legitimate gateway does: run verified apps in the sandbox. It cannot mount
volumes, exec into containers, pull or delete images, or reach the Docker API in any other way.

Listens on a Unix socket or an internal TCP port. Never expose it publicly.
"""
import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import registry
from . import manifest as mf
from .pool import POOL
from .sandbox import run_job, wants_gpu

app = FastAPI(title="sealed launcher", version="0.0.1")
GPU_FLAG = os.environ.get("SEALED_GPU", "0") == "1"


class Run(BaseModel):
    image_id: str
    op: str
    input: Any
    params: Optional[dict] = None
    memory: str = "8g"
    timeout: int = 300
    warm: bool = True


@app.get("/health")
def health():
    return {"ok": True, "warm": len(POOL.status())}


@app.get("/pool")
def pool():
    return POOL.status()


@app.post("/run")
def run(r: Run):
    entry = registry.lookup(r.image_id)
    if not entry:
        raise HTTPException(403, f"image id {r.image_id[:19]}… is not in the allowlist")
    if mf.image_id(entry["image"]) != r.image_id:
        raise HTTPException(409, f"image '{entry['image']}' changed since verification; run `sealed verify` again")
    if r.op not in entry["operations"]:
        raise HTTPException(400, f"{entry['name']} does not declare operation '{r.op}'")
    res = run_job(entry["image"], r.op, r.input, r.params, memory=r.memory, gpu=wants_gpu(entry, GPU_FLAG),
                  timeout=r.timeout, warm=r.warm)
    return {"ok": res.ok, "output": res.output, "error": res.error, "stderr": res.stderr[-1000:], "duration": res.duration}
