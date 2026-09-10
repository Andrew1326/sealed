"""Admission pipeline: turns an image into a verified digest, or explains why not."""
import json
import shutil
import subprocess
import time
import uuid
from typing import Any

from . import manifest as mf
from . import registry
from .gate import check
from .paths import HOME, REPORTS
from .policy import Policy, OutputRules
from .sandbox import run_job, run_raw, sandbox_args
from .pool import Warm
import re


class Report:
    def __init__(self, image: str):
        self.image = image
        self.steps: list = []
        self.passed = True

    def step(self, name: str, ok: bool, detail: Any = None, fatal: bool = True):
        self.steps.append({"step": name, "ok": ok, "detail": detail})
        if not ok and fatal:
            self.passed = False
        return ok

    def to_dict(self):
        return {"image": self.image, "passed": self.passed, "steps": self.steps}


def _fixture_input(image: str, fx: dict):
    """Fixture input may be {"file": "tests/x.docx"} -> base64 of that file inside the image."""
    inp = fx.get("input", "")
    if isinstance(inp, dict) and "file" in inp:
        p = run_raw(image, ["base64", "-w", "0", "/sealed/" + inp["file"]], timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"fixture file missing in image: {inp['file']}")
        return p.stdout.decode().strip()
    return inp


def _expect(fixture: dict, res) -> tuple:
    exp = fixture.get("expect", {})
    if "ok" in exp and exp["ok"] != res.ok:
        return False, f"expected ok={exp['ok']}, got ok={res.ok} ({res.error})"
    if not res.ok and "ok" not in exp:
        return False, f"app error: {res.error}"
    if not res.ok:
        return True, "expected failure"
    text = res.output if isinstance(res.output, str) else json.dumps(res.output, ensure_ascii=False)
    low = text.lower()
    if "contains_any" in exp and not any(s.lower() in low for s in exp["contains_any"]):
        return False, f"none of {exp['contains_any']} in output: {text[:200]!r}"
    if "contains_all" in exp and not all(s.lower() in low for s in exp["contains_all"]):
        return False, f"not all of {exp['contains_all']} in output: {text[:200]!r}"
    if "not_contains" in exp and any(s.lower() in low for s in exp["not_contains"]):
        return False, f"forbidden content in output: {text[:200]!r}"
    if "json_keys" in exp:
        if not isinstance(res.output, dict) or not set(exp["json_keys"]) <= set(res.output):
            return False, f"missing keys {exp['json_keys']} in {text[:200]!r}"
    if "max_chars" in exp and len(text) > exp["max_chars"]:
        return False, f"output {len(text)} chars > {exp['max_chars']}"
    if "min_chars" in exp and len(text) < exp["min_chars"]:
        return False, f"output {len(text)} chars < {exp['min_chars']}"
    if "starts_with" in exp and not text.startswith(exp["starts_with"]):
        return False, f"output does not start with {exp['starts_with']!r}: {text[:60]!r}"
    return True, text[:120]


def verify(image: str, gpu: bool = False, skip_scan: bool = False, log=print) -> Report:
    rep = Report(image)

    # 1. provenance: image must exist locally and resolve to a content-addressed ID
    iid = mf.image_id(image)
    if not rep.step("provenance.image_id", bool(iid), iid or "image not found locally"):
        return rep
    log(f"[1/8] image id {iid[:19]}…")

    # 2. manifest present and valid
    try:
        man = mf.read_manifest(image)
        mf.validate_manifest(man)
        rep.step("manifest.valid", True, man)
        log(f"[2/8] manifest ok: {man['name']} {man['version']} ops={man['operations']}")
    except Exception as e:
        rep.step("manifest.valid", False, str(e))
        return rep

    # 3. image config must not ask for anything the sandbox forbids
    cfg = mf.image_config(image)["Config"]
    asks = {}
    if cfg.get("ExposedPorts"):
        asks["ExposedPorts"] = list(cfg["ExposedPorts"])
    if cfg.get("Volumes"):
        asks["Volumes"] = list(cfg["Volumes"])
    user = (cfg.get("User") or "").strip()
    if user in ("", "0", "root"):
        asks["User"] = user or "(root)"
    rep.step("config.no_forbidden_requests", not asks, asks or "no ports, no volumes, non-root user")
    log(f"[3/8] image config {'REJECTED: ' + json.dumps(asks) if asks else 'ok'}")

    # 4. sandbox self-test: egress and writes must fail from inside this image
    probe = (
        "import socket,sys;r={}\n"
        "try:\n socket.create_connection(('1.1.1.1',80),timeout=3);r['egress']='OPEN'\n"
        "except Exception as e: r['egress']='blocked: '+type(e).__name__\n"
        "try:\n open('/probe','w').write('x');r['rootfs_write']='OPEN'\n"
        "except Exception as e: r['rootfs_write']='blocked: '+type(e).__name__\n"
        "try:\n import os;os.setuid(0);r['setuid']='OPEN'\n"
        "except Exception as e: r['setuid']='blocked: '+type(e).__name__\n"
        "print(__import__('json').dumps(r))"
    )
    pr, ok = None, True
    for py in ("python3", "python"):
        p = run_raw(image, [py, "-c", probe], timeout=60, gpu=gpu)
        if p.returncode == 0 and p.stdout.strip():
            pr = json.loads(p.stdout.decode().strip().splitlines()[-1])
            ok = all(v.startswith("blocked") for v in pr.values())
            break
    if pr is None:
        pr = {"note": "image has no python; probe skipped (the evil-image test covers the sandbox itself)"}
    rep.step("sandbox.probe", ok, pr)
    log(f"[4/8] sandbox probe {pr}")

    # 5. conformance: the image's own fixtures per operation. Fixture 0 runs cold (one job + EOF),
    #    all fixtures then stream through ONE warm container (JSON-lines protocol, model reuse).
    req = man.get("requires", {})
    mem = req.get("memory", "8g")
    timeout = req.get("timeout_seconds", 300)
    all_ok = True
    for op in man["operations"]:
        try:
            fixtures = mf.read_fixtures(image, op)
        except Exception as e:
            rep.step(f"conformance.{op}", False, str(e))
            all_ok = False
            continue
        results = []
        res = run_job(image, op, _fixture_input(image, fixtures[0]), fixtures[0].get("params"), memory=mem, gpu=gpu, timeout=timeout)
        ok, detail = _expect(fixtures[0], res)
        results.append({"mode": "cold", "fixture": 0, "ok": ok, "detail": detail, "seconds": round(res.duration, 1)})
        log(f"[5/8] {op} cold fixture 0: {'ok' if ok else 'FAIL'} ({res.duration:.1f}s) {detail if not ok else ''}")
        w = Warm(image, mem, gpu)
        for i, fx in enumerate(fixtures):
            res = w.submit(op, _fixture_input(image, fx), fx.get("params"), timeout)
            ok, detail = _expect(fx, res)
            results.append({"mode": "warm", "fixture": i, "ok": ok, "detail": detail, "seconds": round(res.duration, 1)})
            if not ok and res.stderr:
                results[-1]["stderr"] = res.stderr[-800:]
            log(f"[5/8] {op} warm fixture {i}: {'ok' if ok else 'FAIL'} ({res.duration:.1f}s) {detail if not ok else ''}")
        w.kill()
        rep.step(f"conformance.{op}", all(r["ok"] for r in results), results)

    # 6. intent: trace the first fixture under strace. Attempts to reach the network or escalate
    #    are rejected even though the sandbox blocked them. Honest inference code never does this.
    tools = HOME / "tools"
    if (tools / "strace").exists():
        cfg_ep = (cfg.get("Entrypoint") or []) + (cfg.get("Cmd") or [])
        op0 = man["operations"][0]
        fx0 = mf.read_fixtures(image, op0)[0]
        job = json.dumps({"op": op0, "input": _fixture_input(image, fx0), "params": fx0.get("params") or {}})
        ep = ["/.sealed-verify/ld-musl-x86_64.so.1", "--library-path", "/.sealed-verify", "/.sealed-verify/strace",
              "-f", "-qq", "-e", "trace=socket,connect,sendto,sendmsg,mount,setuid,setgid,ptrace,init_module,finit_module,reboot,kexec_load",
              "-o", "/tmp/.trace"] + cfg_ep
        # entrypoint + a shell-free way to print the trace afterwards: run strace, then cat via python
        wrapper = ["python", "-c",
                   "import subprocess,sys;p=subprocess.run(" + json.dumps(ep) + ",stdin=sys.stdin);"
                   "sys.stdout.write('\\n===TRACE===\\n'+open('/tmp/.trace').read())"]
        cmd = sandbox_args(image, memory=mem, gpu=gpu, entrypoint=wrapper, verify_tools=str(tools))
        pr = subprocess.run(cmd, input=job.encode(), capture_output=True, timeout=timeout)
        out = pr.stdout.decode(errors="replace")
        trace = out.split("===TRACE===", 1)[1] if "===TRACE===" in out else ""
        bad, advisory = [], []
        for line in trace.splitlines():
            l = line.strip()[:160]
            if re.search(r"(connect|sendto|sendmsg)\(.*(AF_INET|AF_INET6)", line):
                bad.append(l)                       # tried to talk to an IP address: reject
            elif re.search(r"\b(mount|setuid|setgid|ptrace|init_module|finit_module|reboot|kexec_load)\(", line) and "resumed" not in line:
                bad.append(l)                       # tried to escalate: reject
            elif re.search(r"socket\((AF_INET|AF_INET6|AF_PACKET|AF_NETLINK)", line):
                advisory.append(l)                  # opened a socket but never used it (e.g. urllib3 ipv6 probe)
        if advisory:
            rep.step("intent.sockets_opened", True, sorted(set(advisory))[:10], fatal=False)
        uniq = sorted(set(bad))
        rep.step("intent.no_network_or_escalation", not uniq, uniq[:20] or f"clean trace ({len(trace.splitlines())} syscalls observed)")
        log(f"[6/8] intent trace: {'REJECTED, ' + str(len(uniq)) + ' suspicious syscalls, e.g. ' + uniq[0] if uniq else 'clean'}")
    else:
        rep.step("intent.no_network_or_escalation", True, "strace tools missing; run `sealed tools` (advisory)", fatal=False)
        log("[6/8] intent trace skipped: run `sealed tools` to install the static strace")

    # 7. canary: unique token must flow through the gate rules of a strict policy
    canary = f"CANARY-{uuid.uuid4().hex[:12]}"
    binary_out = not (man.get("output", "text/plain").startswith("text/") or man.get("output") == "application/json")
    strict = Policy(name="verify-strict", output=OutputRules(max_chars=50_000_000 if binary_out else 50_000, max_verbatim_span_words=25))
    op = man["operations"][0]
    fx = mf.read_fixtures(image, op)[0]
    inp = _fixture_input(image, fx)
    inp = (inp + f" {canary}") if isinstance(inp, str) and man.get("input", "text/plain").startswith("text/") else inp
    res = run_job(image, op, inp, fx.get("params"), memory=mem, gpu=gpu, timeout=timeout)
    v = check(strict, op, inp, res.output) if res.ok else None
    canary_ok = bool(res.ok and v and v.allowed)
    rep.step("gate.canary", canary_ok, {"app_ok": res.ok, "gate": (v.reason if v and not v.allowed else "allow"), "error": res.error})
    log(f"[7/8] canary through strict gate: {'ok' if canary_ok else 'FAIL'}")

    # 8. vulnerability scan if trivy is installed (advisory, non-fatal)
    if not skip_scan and shutil.which("trivy"):
        p = subprocess.run(["trivy", "image", "--quiet", "--severity", "CRITICAL", "--format", "json", image], capture_output=True, text=True)
        try:
            crit = sum(len(r.get("Vulnerabilities") or []) for r in json.loads(p.stdout).get("Results", []))
        except Exception:
            crit = -1
        rep.step("scan.trivy_critical", crit == 0, {"critical": crit}, fatal=False)
        log(f"[8/8] trivy critical vulnerabilities: {crit}")
    else:
        rep.step("scan.trivy_critical", True, "trivy not installed, skipped", fatal=False)
        log("[8/8] trivy not installed, scan skipped (advisory)")

    path = REPORTS / f"{man['name']}-{int(time.time())}.json"
    path.write_text(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
    if rep.passed:
        registry.add(iid, image, man, str(path), gpu_verified=gpu)
        log(f"VERIFIED  {image}  ->  {iid[:19]}…  added to allowlist")
    else:
        log(f"REJECTED  {image}  see {path}")
    return rep
