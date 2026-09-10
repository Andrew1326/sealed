"""Run one job inside an app image under the non-negotiable sandbox contract."""
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import glob
import os
import shutil

DEFAULT_MEMORY = "8g"
_runtime_checked: dict = {}


def runtime_args() -> list:
    """SEALED_RUNTIME=runsc (gVisor) or kata-runtime adds a user-space kernel / micro-VM between the app and
    the host kernel, which is the mitigation for container-escape bugs. Falls back to runc with a warning."""
    rt = os.environ.get("SEALED_RUNTIME", "").strip()
    if not rt or rt == "runc":
        return []
    if rt not in _runtime_checked:
        p = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True)
        _runtime_checked[rt] = rt in (json.loads(p.stdout or "{}") or {})
        if not _runtime_checked[rt]:
            import sys
            print(f"sealed: SEALED_RUNTIME={rt} is not registered with Docker, falling back to runc", file=sys.stderr)
    return ["--runtime", rt] if _runtime_checked[rt] else []
_DRIVER_LIBS = ["libcuda.so.1", "libnvidia-ml.so.1", "libnvidia-ptxjitcompiler.so.1", "libnvidia-nvvm.so.4"]


def has_gpu() -> bool:
    return os.path.exists("/dev/nvidiactl")


def wants_gpu(entry: Optional[dict], flag: bool = False) -> bool:
    """GPU on when the user asks, or when the verified manifest says optional/required and the host has one."""
    if flag:
        return has_gpu()
    if (entry or {}).get("gpu_verified"):
        return has_gpu()
    req = ((entry or {}).get("requires") or {}).get("gpu", "none")
    return req in ("optional", "required") and has_gpu()


def gpu_args() -> list:
    """GPU access. With the NVIDIA container toolkit installed: --gpus all. Without it: pass the device
    nodes and the driver's user-space libraries read-only. Still no network, still no writable mounts."""
    if shutil.which("nvidia-container-runtime-hook") or shutil.which("nvidia-ctk") or os.path.exists("/etc/cdi/nvidia.yaml"):
        return ["--gpus", "all"]
    args = []
    for d in ["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools"] + sorted(glob.glob("/dev/nvidia[1-9]")):
        if os.path.exists(d):
            args += ["--device", d]
    libdir = "/usr/lib/x86_64-linux-gnu"
    libs = [os.path.join(libdir, l) for l in _DRIVER_LIBS] + glob.glob(os.path.join(libdir, "libnvidia-gpucomp.so.*"))
    for l in libs:
        if os.path.exists(l):
            args += ["-v", f"{os.path.realpath(l)}:{l}:ro"]
    return args if "--device" in args else []

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
                 verify_tools: Optional[str] = None, name: Optional[str] = None) -> list:
    """The sandbox contract. Every flag here is mandatory; images cannot opt out."""
    args = [
        "docker", "run", "--rm", "-i",
        *runtime_args(),
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
    if name:
        args += ["--name", name]
    if cpus:
        args += ["--cpus", str(cpus)]
    if gpu:
        args += gpu_args()
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
            timeout: int = DEFAULT_TIMEOUT, warm: bool = False) -> RunResult:
    if warm:
        from .pool import POOL
        return POOL.submit(image, op, input_value, params, memory, gpu, timeout, cpus)
    job = json.dumps({"op": op, "input": input_value, "params": params or {}}, ensure_ascii=False) + "\n"
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
