"""Warm pool: one long-lived sandboxed container per image, jobs streamed over stdin as JSON lines.

The sandbox contract is identical to the cold path (no network, read-only, no caps). What changes is
that the model stays loaded between jobs. Jobs of one tenant share a process; the container is killed
after `idle_seconds` without work, on any protocol error, or on `sealed pool-stop`.
"""
import json
import queue
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any, Optional

from .sandbox import RunResult, sandbox_args


class Warm:
    def __init__(self, image: str, memory: str, gpu: bool, cpus: Optional[float] = None):
        self.image, self.name = image, f"sealed-warm-{uuid.uuid4().hex[:10]}"
        self.cmd = sandbox_args(image, memory=memory, cpus=cpus, gpu=gpu, name=self.name)
        self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: "queue.Queue[str]" = queue.Queue()
        self.stderr: deque = deque(maxlen=200)
        self.lock = threading.Lock()
        self.last_used = time.time()
        self.jobs = 0
        threading.Thread(target=self._pump, args=(self.proc.stdout, self.lines.put), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, self.stderr.append), daemon=True).start()

    @staticmethod
    def _pump(stream, sink):
        for raw in iter(stream.readline, b""):
            sink(raw.decode(errors="replace").rstrip("\n"))
        sink(None)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def submit(self, op: str, input_value: Any, params: Optional[dict], timeout: int) -> RunResult:
        job = json.dumps({"op": op, "input": input_value, "params": params or {}}, ensure_ascii=False)
        assert "\n" not in job
        with self.lock:
            t0 = time.time()
            try:
                self.proc.stdin.write((job + "\n").encode())
                self.proc.stdin.flush()
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                self.kill()
                return RunResult(ok=False, error=f"timeout after {timeout}s (warm container killed)", stderr="\n".join(x for x in self.stderr if x),
                                 duration=time.time() - t0, docker_cmd=self.cmd)
            except (BrokenPipeError, OSError) as e:
                self.kill()
                return RunResult(ok=False, error=f"warm container died: {e}", stderr="\n".join(x for x in self.stderr if x),
                                 duration=time.time() - t0, docker_cmd=self.cmd)
            self.last_used, self.jobs = time.time(), self.jobs + 1
            dur = time.time() - t0
        if line is None:
            self.kill()
            return RunResult(ok=False, error="warm container exited", stderr="\n".join(x for x in self.stderr if x), duration=dur, docker_cmd=self.cmd)
        try:
            res = json.loads(line)
        except json.JSONDecodeError:
            self.kill()
            return RunResult(ok=False, error="app did not return a JSON line", stderr=line[-500:], duration=dur, docker_cmd=self.cmd)
        return RunResult(ok=bool(res.get("ok")), output=res.get("output"), error=res.get("error"),
                         stderr="\n".join(x for x in self.stderr if x)[-2000:], exit_code=0, duration=dur, docker_cmd=self.cmd)

    def kill(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        subprocess.run(["docker", "kill", self.name], capture_output=True)
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


class Pool:
    def __init__(self, idle_seconds: int = 600):
        self.idle_seconds = idle_seconds
        self.warm: dict = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reaper, daemon=True).start()

    def get(self, image: str, memory: str, gpu: bool, cpus: Optional[float] = None) -> Warm:
        key = (image, gpu)
        with self.lock:
            w = self.warm.get(key)
            if w is None or not w.alive():
                w = self.warm[key] = Warm(image, memory, gpu, cpus)
            return w

    def submit(self, image: str, op: str, input_value: Any, params: Optional[dict], memory: str, gpu: bool,
               timeout: int, cpus: Optional[float] = None) -> RunResult:
        w = self.get(image, memory, gpu, cpus)
        res = w.submit(op, input_value, params, timeout)
        if not w.alive():
            with self.lock:
                self.warm.pop((image, gpu), None)
        return res

    def stop_all(self):
        with self.lock:
            for w in self.warm.values():
                w.kill()
            self.warm.clear()

    def status(self) -> list:
        return [{"image": k[0], "gpu": k[1], "container": w.name, "alive": w.alive(), "jobs": w.jobs,
                 "idle_s": round(time.time() - w.last_used)} for k, w in self.warm.items()]

    def _reaper(self):
        while True:
            time.sleep(15)
            with self.lock:
                for k, w in list(self.warm.items()):
                    if not w.alive() or time.time() - w.last_used > self.idle_seconds:
                        w.kill()
                        self.warm.pop(k, None)


POOL = Pool()


def _shutdown(*_):
    POOL.stop_all()


import atexit
import signal
atexit.register(_shutdown)
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        _prev = signal.getsignal(_sig)
        def _handler(signum, frame, _prev=_prev):
            _shutdown()
            if callable(_prev):
                _prev(signum, frame)
            else:
                raise SystemExit(0)
        signal.signal(_sig, _handler)
    except (ValueError, OSError):
        pass
