"""sealed control plane.

What it holds: runners (enrolled machines), the policies and trusted publisher keys they should use, and the
audit METADATA they report (hashes, sizes, image IDs, verdicts). It never sees document content: runners
have no path to send it, and the audit format contains none.

Single-file service, SQLite state, token auth. Admin token via SEALED_CONTROL_ADMIN_TOKEN.
"""
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

DB = Path(os.environ.get("SEALED_CONTROL_DB", "sealed-control.sqlite"))
ADMIN = os.environ.get("SEALED_CONTROL_ADMIN_TOKEN") or secrets.token_urlsafe(24)
app = FastAPI(title="sealed control", version="0.0.1")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS enroll_tokens(token TEXT PRIMARY KEY, label TEXT, created REAL, used_by TEXT);
        CREATE TABLE IF NOT EXISTS runners(id TEXT PRIMARY KEY, key TEXT, label TEXT, enrolled REAL, last_seen REAL,
                                           hostname TEXT, version TEXT, gpu INTEGER, apps TEXT, pool TEXT, runtime TEXT, jobs INTEGER DEFAULT 0, overrides TEXT DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS audit(runner TEXT, ts TEXT, policy TEXT, image TEXT, image_id TEXT, op TEXT,
                                         input_sha256 TEXT, input_chars INTEGER, output_chars INTEGER, app_ok INTEGER,
                                         gate TEXT, gate_reason TEXT, duration_s REAL, client TEXT, UNIQUE(runner, ts, input_sha256, op));
        """)
        if not c.execute("SELECT 1 FROM config WHERE k='policies'").fetchone():
            c.execute("INSERT INTO config VALUES('policies', ?)", (json.dumps({}),))
            c.execute("INSERT INTO config VALUES('trusted_keys', ?)", (json.dumps({}),))
            c.execute("INSERT INTO config VALUES('registry', ?)", (json.dumps(""),))
            c.execute("INSERT INTO config VALUES('runtime', ?)", (json.dumps(""),))
            c.execute("INSERT INTO config VALUES('webhook', ?)", (json.dumps(""),))
            c.execute("INSERT INTO config VALUES('public_url', ?)", (json.dumps(""),))
        # migrations for older DBs
        for col, ddl in (("overrides", "ALTER TABLE runners ADD COLUMN overrides TEXT DEFAULT '{}'"), ):
            if col not in [r[1] for r in c.execute("PRAGMA table_info(runners)")]:
                c.execute(ddl)
        if "client" not in [r[1] for r in c.execute("PRAGMA table_info(audit)")]:
            c.execute("ALTER TABLE audit ADD COLUMN client TEXT")


init()


def admin(authorization: str = Header("")):
    if authorization != f"Bearer {ADMIN}":
        raise HTTPException(401, "admin token required")


def runner_auth(runner_id: str, authorization: str = Header("")) -> sqlite3.Row:
    with db() as c:
        r = c.execute("SELECT * FROM runners WHERE id=?", (runner_id,)).fetchone()
    if not r or authorization != f"Bearer {r['key']}":
        raise HTTPException(401, "runner key invalid")
    return r


# ---------- admin ----------
class TokenReq(BaseModel):
    label: str = ""


@app.post("/v1/admin/enroll-tokens", dependencies=[Depends(admin)])
def make_token(t: TokenReq):
    tok = "enr_" + secrets.token_urlsafe(18)
    with db() as c:
        c.execute("INSERT INTO enroll_tokens VALUES(?,?,?,NULL)", (tok, t.label, time.time()))
    return {"token": tok, "label": t.label}


@app.get("/v1/admin/runners", dependencies=[Depends(admin)])
def list_runners():
    with db() as c:
        rows = c.execute("SELECT id,label,enrolled,last_seen,hostname,version,gpu,apps,pool,runtime,jobs FROM runners ORDER BY last_seen DESC").fetchall()
    return [dict(r, apps=json.loads(r["apps"] or "[]"), pool=json.loads(r["pool"] or "[]"),
                 online=(time.time() - (r["last_seen"] or 0)) < 120) for r in rows]


class ConfigReq(BaseModel):
    policies: Optional[dict] = None       # name -> yaml text
    trusted_keys: Optional[dict] = None   # pubkey -> label
    registry: Optional[str] = None
    runtime: Optional[str] = None


@app.put("/v1/admin/config", dependencies=[Depends(admin)])
def set_config(cfg: ConfigReq):
    with db() as c:
        for k, v in cfg.model_dump(exclude_none=True).items():
            c.execute("INSERT OR REPLACE INTO config VALUES(?,?)", (k, json.dumps(v)))
    return get_config_raw()


def get_config_raw():
    with db() as c:
        return {r["k"]: json.loads(r["v"]) for r in c.execute("SELECT k,v FROM config")}


@app.get("/v1/admin/config", dependencies=[Depends(admin)])
def get_config():
    return get_config_raw()


@app.get("/v1/admin/audit", dependencies=[Depends(admin)])
def admin_audit(runner: Optional[str] = None, n: int = 200):
    with db() as c:
        q = "SELECT * FROM audit" + (" WHERE runner=?" if runner else "") + " ORDER BY ts DESC LIMIT ?"
        rows = c.execute(q, ((runner, n) if runner else (n,))).fetchall()
    return [dict(r) for r in rows]


# ---------- runners ----------
class Enroll(BaseModel):
    token: str
    hostname: str = ""
    version: str = ""


@app.post("/v1/enroll")
def enroll(e: Enroll):
    with db() as c:
        t = c.execute("SELECT * FROM enroll_tokens WHERE token=? AND used_by IS NULL", (e.token,)).fetchone()
        if not t:
            raise HTTPException(403, "enrolment token invalid or already used")
        rid, key = "rn_" + secrets.token_hex(6), "rk_" + secrets.token_urlsafe(24)
        c.execute("INSERT INTO runners(id,key,label,enrolled,last_seen,hostname,version) VALUES(?,?,?,?,?,?,?)",
                  (rid, key, t["label"], time.time(), time.time(), e.hostname, e.version))
        c.execute("UPDATE enroll_tokens SET used_by=? WHERE token=?", (rid, e.token))
    return {"runner_id": rid, "runner_key": key}


class Heartbeat(BaseModel):
    hostname: str = ""
    version: str = ""
    gpu: bool = False
    apps: list = []
    pool: list = []
    runtime: str = ""
    audit: list = []          # new audit lines since last heartbeat (metadata only)


@app.post("/v1/runners/{runner_id}/heartbeat")
def heartbeat(runner_id: str, hb: Heartbeat, r: sqlite3.Row = Depends(runner_auth)):
    with db() as c:
        c.execute("UPDATE runners SET last_seen=?,hostname=?,version=?,gpu=?,apps=?,pool=?,runtime=?,jobs=jobs+? WHERE id=?",
                  (time.time(), hb.hostname, hb.version, int(hb.gpu), json.dumps(hb.apps), json.dumps(hb.pool), hb.runtime, len(hb.audit), runner_id))
        for a in hb.audit:
            c.execute("INSERT OR IGNORE INTO audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (runner_id, a.get("ts"), a.get("policy"), a.get("image"), a.get("image_id"), a.get("op"), a.get("input_sha256"),
                       a.get("input_chars"), a.get("output_chars"), int(bool(a.get("app_ok"))), a.get("gate"), a.get("gate_reason"), a.get("duration_s"), a.get("client")))
        ov = json.loads(c.execute("SELECT overrides FROM runners WHERE id=?", (runner_id,)).fetchone()[0] or "{}")
    cfg = get_config_raw()
    out = {k: cfg.get(k) for k in ("policies", "trusted_keys", "registry", "runtime")}
    if ov.get("policy_name") and ov["policy_name"] in (cfg.get("policies") or {}):
        out["policies"] = {**(cfg.get("policies") or {}), "confidential": cfg["policies"][ov["policy_name"]]}
    if ov.get("runtime"):
        out["runtime"] = ov["runtime"]
    bad = [a for a in hb.audit if a.get("gate") == "block" or not a.get("app_ok")]
    if bad and cfg.get("webhook"):
        notify(cfg["webhook"], runner_id, r["label"], bad)
    return {"ok": True, "config": out}


def notify(url: str, runner_id: str, label: str, events: list) -> None:
    import threading
    import urllib.request

    def send():
        body = json.dumps({"source": "sealed-control", "runner": runner_id, "label": label, "count": len(events),
                           "text": f"sealed: {len(events)} blocked/errored job(s) on runner {label or runner_id}",
                           "events": [{k: a.get(k) for k in ("ts", "op", "image", "gate", "gate_reason", "app_ok", "client")} for a in events[:20]]}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"content-type": "application/json"}), timeout=10)
        except Exception as e:
            print(f"webhook failed: {e}")
    threading.Thread(target=send, daemon=True).start()


PUBLIC_URL = os.environ.get("SEALED_CONTROL_PUBLIC_URL", "http://<control-host>:8480")


@app.get("/", response_class=HTMLResponse)
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/overview", status_code=303)


@app.get("/legacy", response_class=HTMLResponse)
def dashboard(request: Request):
    tok = request.query_params.get("token", "")
    if tok != ADMIN:
        return HTMLResponse("<p style='font-family:system-ui;padding:2rem'>sealed control. Open <code>/?token=&lt;admin token&gt;</code>.</p>")
    runners = list_runners()
    with db() as c:
        total = c.execute("SELECT COUNT(*) n, SUM(gate='block') b FROM audit").fetchone()
        recent = c.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT 25").fetchall()
    rows = "".join(
        f"<tr><td>{'🟢' if r['online'] else '⚪'}</td><td>{r['label'] or ''}<br><small>{r['id']}</small></td><td>{r['hostname']}</td>"
        f"<td>{', '.join(a.get('name','') + ' ' + a.get('version','') for a in r['apps'])}</td>"
        f"<td>{'GPU' if r['gpu'] else 'CPU'} {r['runtime'] or 'runc'}</td><td>{r['jobs']}</td>"
        f"<td>{time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['last_seen'] or 0))}</td></tr>" for r in runners)
    aud = "".join(f"<tr><td>{a['ts']}</td><td>{a['runner']}</td><td>{a['op']}</td><td>{a['image']}</td><td>{a['input_chars']}→{a['output_chars']}</td>"
                  f"<td>{'✅' if a['gate']=='allow' else '⛔ ' + (a['gate_reason'] or '')}</td><td>{a['duration_s']}s</td></tr>" for a in recent)
    return f"""<!doctype html><meta charset=utf-8><title>sealed control</title>
<style>body{{font-family:system-ui;margin:2rem;color:#222}}table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}td,th{{border-bottom:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:14px}}small{{color:#888}}h2{{margin-top:2rem}}</style>
<h1>sealed control</h1><p>{len(runners)} runners, {sum(r['online'] for r in runners)} online · {total['n'] or 0} jobs reported · {total['b'] or 0} blocked by gate · no document content ever leaves a runner</p>
<h2>Runners</h2><table><tr><th></th><th>Runner</th><th>Host</th><th>Verified apps</th><th>Compute</th><th>Jobs</th><th>Last seen (UTC)</th></tr>{rows}</table>
<h2>Recent jobs (metadata only)</h2><table><tr><th>Time</th><th>Runner</th><th>Op</th><th>Image</th><th>Chars</th><th>Gate</th><th>Took</th></tr>{aud}</table>"""


from . import ui as _ui  # noqa: E402
app.include_router(_ui.r)


def main():
    import click
    host, port = os.environ.get("SEALED_CONTROL_HOST", "127.0.0.1"), int(os.environ.get("SEALED_CONTROL_PORT", "8480"))
    print(f"sealed control on http://{host}:{port}   admin token: {ADMIN}   db: {DB}")
    uvicorn.run("sealed_control.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
