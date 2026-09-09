"""Run one job inside an app image under the non-negotiable sandbox contract."""
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_MEMORY = "8g"
DEFAULT_TIMEOUT = 300


@dataclass
class RunResult:
    ok: bool
    output: Any = None
    error: Optional[str] = None
    stderr: str = ""
    exit_code: int = -1
    duration: float = 0.0
    docker_cmd: list = field(default_factory=list)


def sandbox_args(image: str, memory: str = DEFAULT_MEMORY, cpus: Optional[float] = None,
                 gpu: bool = False, entrypoint: Optional[list] = None, extra_env: Optional[dict] = None,
                 verify_tools: Optional[str] = None) -> list:
    """The sandbox contract. Every flag here is mandatory; images cannot opt out."""
    args = [
        "docker", "run", "--rm", "-i",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,nosuid,size=2g",
        "--memory", memory,
        "--memory-swap", memory,
        "--pids-limit", "256",
        "--ipc", "private",
        "--env", "HF_HUB_OFFLINE=1",
        "--env", "TRANSFORMERS_OFFLINE=1",
        "--env", "HOME=/tmp",
    ]
    if cpus:
        args += ["--cpus", str(cpus)]
    if gpu:
        args += ["--gpus", "all"]
    for k, v in (extra_env or {}).items():
        args += ["--env", f"{k}={v}"]
    if verify_tools:
        # verify-time only: read-only mount of a static strace so the runner can observe intent.
        # Production jobs never pass this; the sandbox stays volume-free.
        args += ["-v", f"{verify_tools}:/.sealed-verify:ro"]
    if entrypoint:
        args += ["--entrypoint", entrypoint[0]]
    args.append(image)
    if entrypoint and len(entrypoint) > 1:
        args += entrypoint[1:]
    return args


def run_job(image: str, op: str, input_value: Any, params: Optional[dict] = None,
            memory: str = DEFAULT_MEMORY, cpus: Optional[float] = None, gpu: bool = False,
            timeout: int = DEFAULT_TIMEOUT) -> RunResult:
    job = json.dumps({"op": op, "input": input_value, "params": params or {}})
    cmd = sandbox_args(image, memory=memory, cpus=cpus, gpu=gpu)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, input=job.encode(), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return RunResult(ok=False, error=f"timeout after {timeout}s", stderr=(e.stderr or b"").decode(errors="replace"),
                         duration=time.time() - t0, docker_cmd=cmd)
    dur = time.time() - t0
    stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0 and not proc.stdout.strip():
        return RunResult(ok=False, error=f"container exited {proc.returncode}", stderr=stderr,
                         exit_code=proc.returncode, duration=dur, docker_cmd=cmd)
    raw = proc.stdout.decode(errors="replace").strip()
    last_line = raw.splitlines()[-1] if raw else ""
    try:
        res = json.loads(last_line)
    except json.JSONDecodeError:
        return RunResult(ok=False, error="app did not return JSON on stdout", stderr=stderr + "\n--- stdout ---\n" + raw[-2000:],
                         exit_code=proc.returncode, duration=dur, docker_cmd=cmd)
    if not isinstance(res, dict) or "ok" not in res:
        return RunResult(ok=False, error="app result missing 'ok'", stderr=stderr, exit_code=proc.returncode, duration=dur, docker_cmd=cmd)
    return RunResult(ok=bool(res.get("ok")), output=res.get("output"), error=res.get("error"), stderr=stderr,
                     exit_code=proc.returncode, duration=dur, docker_cmd=cmd)


def run_raw(image: str, entrypoint: list, timeout: int = 60, **kw) -> subprocess.CompletedProcess:
    """Run an arbitrary command inside the sandbox (used by verify for probes and manifest reads)."""
    cmd = sandbox_args(image, entrypoint=entrypoint, **kw)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)
