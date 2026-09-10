"""Runner agent: enrol with a control plane, heartbeat, pull policy/trust config, push audit metadata.

State in ~/.sealed/agent.json. The agent is the only runner component that talks to the outside, and the only
things it sends are: hostname, version, verified app list, pool status, and audit lines (hashes and sizes,
never content). Everything it receives is written to disk for the gateway/launcher to pick up.
"""
import json
import os
import platform
import time
import urllib.request

from . import __version__, registry
from .paths import AUDIT, HOME
from .sandbox import has_gpu

STATE = HOME / "agent.json"
POLICY_DIR = HOME / "policies"


def _post(url, body, key=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **({"authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def enroll(control: str, token: str) -> dict:
    d = _post(control.rstrip("/") + "/v1/enroll", {"token": token, "hostname": platform.node(), "version": __version__})
    st = {"control": control.rstrip("/"), "runner_id": d["runner_id"], "runner_key": d["runner_key"], "audit_offset": 0}
    STATE.write_text(json.dumps(st, indent=2))
    STATE.chmod(0o600)
    return st


def _new_audit(st: dict) -> list:
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text().splitlines()
    new = lines[st.get("audit_offset", 0):]
    return [json.loads(l) for l in new if l.strip()][:500]


def apply_config(cfg: dict) -> list:
    changed = []
    pol = cfg.get("policies") or {}
    if pol:
        POLICY_DIR.mkdir(exist_ok=True)
        for name, text in pol.items():
            p = POLICY_DIR / f"{name}.yaml"
            if not p.exists() or p.read_text() != text:
                p.write_text(text)
                changed.append(f"policy {name}")
    keys = cfg.get("trusted_keys")
    if keys:
        from .signing import TRUSTED, load_trusted
        cur = load_trusted()
        merged = {**cur, **keys}
        if merged != cur:
            TRUSTED.write_text(json.dumps(merged, indent=2))
            changed.append("trusted keys")
    for k in ("registry", "runtime"):
        if cfg.get(k) is not None:
            p = HOME / f"{k}.txt"
            if not p.exists() or p.read_text() != cfg[k]:
                p.write_text(cfg[k])
                changed.append(k)
    return changed


def heartbeat_once(st: dict) -> dict:
    apps = [{"name": e["name"], "version": e["version"], "operations": e["operations"]} for e in registry.load().values()]
    audit = _new_audit(st)
    pool = []
    try:
        with urllib.request.urlopen(os.environ.get("SEALED_LAUNCHER", "http://127.0.0.1:8473") + "/pool", timeout=5) as r:
            pool = json.loads(r.read())
    except Exception:
        pass
    body = {"hostname": platform.node(), "version": __version__, "gpu": has_gpu(), "apps": apps, "pool": pool,
            "runtime": os.environ.get("SEALED_RUNTIME", ""), "audit": audit}
    d = _post(f"{st['control']}/v1/runners/{st['runner_id']}/heartbeat", body, st["runner_key"])
    st["audit_offset"] = st.get("audit_offset", 0) + len(audit)
    STATE.write_text(json.dumps(st, indent=2))
    return {"sent_audit": len(audit), "changed": apply_config(d.get("config") or {})}


def run(interval: int = 30):
    st = json.loads(STATE.read_text())
    print(f"sealed agent: runner {st['runner_id']} -> {st['control']} every {interval}s", flush=True)
    while True:
        try:
            r = heartbeat_once(st)
            if r["changed"] or r["sent_audit"]:
                print(f"heartbeat ok, audit +{r['sent_audit']}, config changed: {r['changed']}", flush=True)
        except Exception as e:
            print(f"heartbeat failed: {e}", flush=True)
        time.sleep(interval)
