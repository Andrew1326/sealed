"""Control panel: server-rendered pages over the same SQLite state as the API. Login = admin token in a cookie."""
import html
import json
import time
import urllib.request
from typing import Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import app as core

r = APIRouter()
COOKIE = "sealed_admin"

CSS = """
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;margin:0;color:#1d1d1f;background:#f5f5f7}
nav{background:#111;color:#eee;padding:.7rem 1.5rem;display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap}
nav a{color:#ddd;text-decoration:none}nav a.on,nav a:hover{color:#fff;border-bottom:2px solid #6cf}nav b{margin-right:1rem}
main{padding:1.5rem;max-width:1200px}h1{font-size:1.4rem;margin:.2rem 0 1rem}h2{font-size:1.05rem;margin:1.5rem 0 .5rem}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden}td,th{padding:.45rem .7rem;border-bottom:1px solid #eee;text-align:left;font-size:14px;vertical-align:top}
th{background:#fafafa;font-weight:600}small,.muted{color:#777}code{background:#eee;padding:.1rem .3rem;border-radius:4px;font-size:13px}
textarea{width:100%;min-height:220px;font-family:ui-monospace,monospace;font-size:13px;padding:.6rem;border:1px solid #ccc;border-radius:6px}
input[type=text],input[type=url],input[type=password],select{padding:.4rem .5rem;border:1px solid #ccc;border-radius:6px;font-size:14px;min-width:16rem}
button{background:#111;color:#fff;border:0;border-radius:6px;padding:.45rem .9rem;font-size:14px;cursor:pointer}button.danger{background:#b3261e}
.card{background:#fff;border-radius:8px;padding:1rem 1.2rem;margin-bottom:1rem;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:.8rem}.kpi b{font-size:1.6rem;display:block}
.ok{color:#1a7f37}.bad{color:#b3261e}.flash{background:#e8f4ff;border-left:4px solid #3b82f6;padding:.6rem .9rem;margin-bottom:1rem;border-radius:4px}
.err{background:#fdecea;border-left-color:#b3261e}form.inline{display:inline}
"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def page(title: str, body: str, active: str = "", flash: str = "", err: bool = False) -> HTMLResponse:
    tabs = [("overview", "Overview"), ("runners", "Runners"), ("policies", "Policies"), ("trust", "Trust"),
            ("tokens", "Enrol tokens"), ("audit", "Audit"), ("alerts", "Alerts"), ("settings", "Settings")]
    nav = "".join(f'<a href="/ui/{k}" class="{"on" if k == active else ""}">{v}</a>' for k, v in tabs)
    fl = f'<div class="flash {"err" if err else ""}">{esc(flash)}</div>' if flash else ""
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{esc(title)} · sealed control</title>"
                        f"<style>{CSS}</style><nav><b>sealed control</b>{nav}<span style='flex:1'></span><a href='/ui/logout'>Log out</a></nav><main>{fl}{body}</main>")


def authed(request: Request) -> bool:
    return request.cookies.get(COOKIE) == core.ADMIN


def gate(request: Request):
    return None if authed(request) else RedirectResponse("/ui/login", status_code=303)


def ago(ts: Optional[float]) -> str:
    if not ts:
        return "never"
    d = int(time.time() - ts)
    return f"{d}s ago" if d < 90 else f"{d // 60}m ago" if d < 5400 else f"{d // 3600}h ago"


# ---------- login ----------
@r.get("/ui/login", response_class=HTMLResponse)
def login_form(request: Request):
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>sealed control</title><style>{CSS}</style><main style='max-width:26rem;margin:6rem auto'>"
                        "<div class=card><h1>sealed control</h1><form method=post><p><input type=password name=token placeholder='admin token' autofocus style='width:100%'></p>"
                        "<button>Sign in</button></form><p class=muted>The admin token is printed when the control plane starts, or set via SEALED_CONTROL_ADMIN_TOKEN.</p></div></main>")


@r.post("/ui/login")
def login(token: str = Form(...)):
    if token != core.ADMIN:
        return RedirectResponse("/ui/login", status_code=303)
    resp = RedirectResponse("/ui/overview", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=86400 * 7)
    return resp


@r.get("/ui/logout")
def logout():
    resp = RedirectResponse("/ui/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------- overview ----------
@r.get("/ui/overview", response_class=HTMLResponse)
@r.get("/ui", response_class=HTMLResponse)
def overview(request: Request):
    if (g := gate(request)):
        return g
    runners = core.list_runners()
    with core.db() as c:
        t = c.execute("SELECT COUNT(*) n, SUM(gate='block') b, SUM(app_ok=0) e FROM audit").fetchone()
        day = c.execute("SELECT COUNT(*) n FROM audit WHERE ts > ?", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400)),)).fetchone()
    kpi = f"""<div class=grid>
      <div class='card kpi'><b>{len(runners)}</b>runners <span class=ok>{sum(x['online'] for x in runners)} online</span></div>
      <div class='card kpi'><b>{t['n'] or 0}</b>jobs reported</div>
      <div class='card kpi'><b>{day['n'] or 0}</b>last 24h</div>
      <div class='card kpi'><b class='{"bad" if t['b'] else ""}'>{t['b'] or 0}</b>blocked by gate</div>
      <div class='card kpi'><b>{t['e'] or 0}</b>app errors</div></div>"""
    rows = "".join(f"<tr><td>{'🟢' if x['online'] else '⚪'}</td><td><a href='/ui/runners/{x['id']}'>{esc(x['label'] or x['id'])}</a><br><small>{esc(x['hostname'])}</small></td>"
                   f"<td>{', '.join(esc(a.get('name')) for a in x['apps'])}</td><td>{'GPU' if x['gpu'] else 'CPU'} · {esc(x['runtime'] or 'runc')}</td><td>{x['jobs']}</td><td>{ago(x['last_seen'])}</td></tr>" for x in runners)
    return page("Overview", kpi + "<h2>Runners</h2><table><tr><th></th><th>Runner</th><th>Verified apps</th><th>Compute</th><th>Jobs</th><th>Last seen</th></tr>" + (rows or "<tr><td colspan=6 class=muted>No runners yet. Create an enrol token and run the installer.</td></tr>") + "</table>"
                "<p class=muted>Nothing on this page is document content. Runners report hashes, sizes, image IDs and gate verdicts only.</p>", "overview")


# ---------- runners ----------
@r.get("/ui/runners", response_class=HTMLResponse)
def runners(request: Request):
    if (g := gate(request)):
        return g
    rows = "".join(f"<tr><td>{'🟢' if x['online'] else '⚪'}</td><td><a href='/ui/runners/{x['id']}'>{esc(x['label'] or x['id'])}</a><br><small>{x['id']}</small></td><td>{esc(x['hostname'])}</td>"
                   f"<td>{esc(x['version'])}</td><td>{len(x['apps'])}</td><td>{len([p for p in x['pool'] if p.get('alive')])} warm</td><td>{x['jobs']}</td><td>{ago(x['last_seen'])}</td></tr>" for x in core.list_runners())
    return page("Runners", "<h1>Runners</h1><table><tr><th></th><th>Runner</th><th>Host</th><th>Version</th><th>Apps</th><th>Pool</th><th>Jobs</th><th>Last seen</th></tr>" + rows + "</table>", "runners")


@r.get("/ui/runners/{rid}", response_class=HTMLResponse)
def runner_detail(request: Request, rid: str, flash: str = ""):
    if (g := gate(request)):
        return g
    with core.db() as c:
        x = c.execute("SELECT * FROM runners WHERE id=?", (rid,)).fetchone()
        aud = c.execute("SELECT * FROM audit WHERE runner=? ORDER BY ts DESC LIMIT 50", (rid,)).fetchall()
    if not x:
        return page("Runner", "<p>unknown runner</p>", "runners")
    apps = json.loads(x["apps"] or "[]"); pool = json.loads(x["pool"] or "[]"); ov = json.loads(x["overrides"] or "{}")
    cfg = core.get_config_raw()
    pol_opts = "".join(f"<option value='{esc(n)}' {'selected' if ov.get('policy_name') == n else ''}>{esc(n)}</option>" for n in cfg.get("policies", {}))
    body = f"""<h1>{esc(x['label'] or rid)} <small class=muted>{rid}</small></h1>
<div class=grid><div class=card><b>Host</b><br>{esc(x['hostname'])}<br><small>runner {esc(x['version'])}</small></div>
<div class=card><b>Compute</b><br>{'GPU' if x['gpu'] else 'CPU'} · {esc(x['runtime'] or 'runc')}</div>
<div class=card><b>Jobs</b><br>{x['jobs']}</div><div class=card><b>Last seen</b><br>{ago(x['last_seen'])}<br><small>enrolled {time.strftime('%Y-%m-%d', time.gmtime(x['enrolled']))}</small></div></div>
<h2>Verified apps</h2><table><tr><th>App</th><th>Version</th><th>Operations</th></tr>{"".join(f"<tr><td>{esc(a.get('name'))}</td><td>{esc(a.get('version'))}</td><td>{esc(', '.join(a.get('operations', [])))}</td></tr>" for a in apps) or "<tr><td colspan=3 class=muted>none reported</td></tr>"}</table>
<h2>Warm pool</h2><table><tr><th>Image</th><th>GPU</th><th>Jobs</th><th>Idle</th></tr>{"".join(f"<tr><td>{esc(p.get('image'))}</td><td>{p.get('gpu')}</td><td>{p.get('jobs')}</td><td>{p.get('idle_s')}s</td></tr>" for p in pool) or "<tr><td colspan=4 class=muted>empty</td></tr>"}</table>
<h2>Per-runner override</h2><div class=card><form method=post action='/ui/runners/{rid}/override'>
<p>Confidential policy variant for this runner: <select name=policy_name><option value=''>(fleet default)</option>{pol_opts}</select>
&nbsp; Runtime: <input type=text name=runtime value='{esc(ov.get('runtime',''))}' placeholder='runsc / kata-runtime / empty = fleet' style='min-width:12rem'> <button>Save</button></p>
<p class=muted>The selected policy is delivered to this runner under the name <code>confidential</code>. Leave empty to inherit the fleet config.</p></form>
<form method=post action='/ui/runners/{rid}/delete' class=inline onsubmit="return confirm('Remove this runner? It will need a new enrol token to come back.')"><button class=danger>Remove runner</button></form></div>
<h2>Recent jobs</h2>{audit_table(aud)}"""
    return page("Runner", body, "runners", flash)


@r.post("/ui/runners/{rid}/override")
def runner_override(rid: str, policy_name: str = Form(""), runtime: str = Form("")):
    ov = {k: v for k, v in {"policy_name": policy_name.strip(), "runtime": runtime.strip()}.items() if v}
    with core.db() as c:
        c.execute("UPDATE runners SET overrides=? WHERE id=?", (json.dumps(ov), rid))
    return RedirectResponse(f"/ui/runners/{rid}?flash=override+saved,+applied+on+next+heartbeat", status_code=303)


@r.post("/ui/runners/{rid}/delete")
def runner_delete(rid: str):
    with core.db() as c:
        c.execute("DELETE FROM runners WHERE id=?", (rid,))
    return RedirectResponse("/ui/runners", status_code=303)


# ---------- policies ----------
DEFAULT_POLICY = """name: confidential
tier: confidential
require_verified: true
allowed_ops: ["*"]
memory: 8g
timeout_seconds: 300
audit: true
warm: true
chunk_chars: 6000
output:
  max_chars: 200000
  max_verbatim_span_words: 40
"""


@r.get("/ui/policies", response_class=HTMLResponse)
def policies(request: Request, edit: str = "", flash: str = "", err: int = 0):
    if (g := gate(request)):
        return g
    pol = core.get_config_raw().get("policies", {})
    rows = "".join(f"<tr><td><a href='/ui/policies?edit={esc(n)}'>{esc(n)}</a></td><td><code>{esc((yaml.safe_load(t) or {}).get('tier',''))}</code></td>"
                   f"<td>{esc((yaml.safe_load(t) or {}).get('allowed_ops',''))}</td><td>{'yes' if (yaml.safe_load(t) or {}).get('require_verified', True) else '<b class=bad>no</b>'}</td>"
                   f"<td><form method=post action='/ui/policies/delete' class=inline><input type=hidden name=name value='{esc(n)}'><button class=danger>Delete</button></form></td></tr>" for n, t in pol.items())
    text = pol.get(edit, DEFAULT_POLICY if not edit else "")
    body = f"""<h1>Policies</h1><p class=muted>Policies pushed here override the runner's local <code>policies/</code> on the next heartbeat. The gateway loads them by name; clients pick a policy per job.</p>
<table><tr><th>Name</th><th>Tier</th><th>Allowed ops</th><th>Verified only</th><th></th></tr>{rows or "<tr><td colspan=5 class=muted>No fleet policies yet: runners use their local files.</td></tr>"}</table>
<h2>{'Edit ' + esc(edit) if edit else 'New policy'}</h2><div class=card><form method=post action='/ui/policies/save'>
<p>Name: <input type=text name=name value='{esc(edit)}' placeholder='confidential' required></p>
<textarea name=text>{esc(text)}</textarea><p><button>Validate and save</button></p></form></div>"""
    return page("Policies", body, "policies", flash, bool(err))


@r.post("/ui/policies/save")
def policy_save(name: str = Form(...), text: str = Form(...)):
    try:
        d = yaml.safe_load(text) or {}
        assert isinstance(d, dict), "policy must be a YAML mapping"
        for k in ("name", "tier"):
            assert k in d, f"missing '{k}'"
        assert isinstance(d.get("allowed_ops", ["*"]), list), "allowed_ops must be a list"
        out = d.get("output", {}) or {}
        assert isinstance(out.get("max_chars", 1), int) and isinstance(out.get("max_verbatim_span_words", 0), int), "output limits must be integers"
    except Exception as e:
        return RedirectResponse(f"/ui/policies?edit={name}&err=1&flash=invalid+policy:+{urllib.request.quote(str(e))}", status_code=303)
    cfg = core.get_config_raw()
    pol = dict(cfg.get("policies", {})); pol[name.strip()] = text
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('policies', ?)", (json.dumps(pol),))
    return RedirectResponse(f"/ui/policies?edit={name}&flash=saved", status_code=303)


@r.post("/ui/policies/delete")
def policy_delete(name: str = Form(...)):
    cfg = core.get_config_raw()
    pol = dict(cfg.get("policies", {})); pol.pop(name, None)
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('policies', ?)", (json.dumps(pol),))
    return RedirectResponse("/ui/policies?flash=deleted", status_code=303)


# ---------- trust ----------
@r.get("/ui/trust", response_class=HTMLResponse)
def trust(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    keys = core.get_config_raw().get("trusted_keys", {})
    rows = "".join(f"<tr><td>{esc(l)}</td><td><code>{esc(k)}</code></td><td><form method=post action='/ui/trust/delete' class=inline><input type=hidden name=key value='{esc(k)}'><button class=danger>Remove</button></form></td></tr>" for k, l in keys.items())
    body = f"""<h1>Trusted publishers</h1><p class=muted>Runners only install registry entries signed by one of these keys. Distributed on the next heartbeat.</p>
<table><tr><th>Label</th><th>Ed25519 public key</th><th></th></tr>{rows or "<tr><td colspan=3 class=muted>none</td></tr>"}</table>
<div class=card><form method=post action='/ui/trust/add'><p>Label <input type=text name=label required> &nbsp; Public key <input type=text name=key required style='min-width:28rem'> <button>Trust</button></p></form></div>"""
    return page("Trust", body, "trust", flash)


@r.post("/ui/trust/add")
def trust_add(label: str = Form(...), key: str = Form(...)):
    cfg = core.get_config_raw(); keys = dict(cfg.get("trusted_keys", {})); keys[key.strip()] = label.strip()
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('trusted_keys', ?)", (json.dumps(keys),))
    return RedirectResponse("/ui/trust?flash=key+trusted", status_code=303)


@r.post("/ui/trust/delete")
def trust_delete(key: str = Form(...)):
    cfg = core.get_config_raw(); keys = dict(cfg.get("trusted_keys", {})); keys.pop(key, None)
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('trusted_keys', ?)", (json.dumps(keys),))
    return RedirectResponse("/ui/trust?flash=key+removed", status_code=303)


# ---------- tokens ----------
@r.get("/ui/tokens", response_class=HTMLResponse)
def tokens(request: Request, new: str = "", flash: str = ""):
    if (g := gate(request)):
        return g
    with core.db() as c:
        rows = c.execute("SELECT * FROM enroll_tokens ORDER BY created DESC").fetchall()
    tr = "".join(f"<tr><td>{esc(t['label'])}</td><td><code>{esc(t['token'][:12])}…</code></td><td>{time.strftime('%Y-%m-%d %H:%M', time.gmtime(t['created']))}</td>"
                 f"<td>{('used by <a href=/ui/runners/' + t['used_by'] + '>' + t['used_by'] + '</a>') if t['used_by'] else '<span class=ok>unused</span>'}</td>"
                 f"<td>{'' if t['used_by'] else '<form method=post action=/ui/tokens/delete class=inline><input type=hidden name=token value=' + esc(t['token']) + '><button class=danger>Revoke</button></form>'}</td></tr>" for t in rows)
    shown = f"""<div class=card><b>New token (shown once):</b> <code>{esc(new)}</code><p>Install a runner with it:</p>
<pre>SEALED_CONTROL={esc(core.get_config_raw().get("public_url") or core.PUBLIC_URL)} SEALED_ENROLL_TOKEN={esc(new)} bash -c "$(curl -fsSL https://raw.githubusercontent.com/Andrew1326/sealed/master/deploy/install.sh)"</pre>
<p class=muted>Or paste <code>deploy/cloud-init.yaml</code> as VM user data with these two values.</p></div>""" if new else ""
    body = f"""<h1>Enrol tokens</h1>{shown}<div class=card><form method=post action='/ui/tokens/create'><p>Label <input type=text name=label placeholder='office-server' required> <button>Create token</button></p></form></div>
<table><tr><th>Label</th><th>Token</th><th>Created</th><th>Status</th><th></th></tr>{tr}</table>"""
    return page("Enrol tokens", body, "tokens", flash)


@r.post("/ui/tokens/create")
def token_create(label: str = Form(...)):
    d = core.make_token(core.TokenReq(label=label))
    return RedirectResponse(f"/ui/tokens?new={d['token']}", status_code=303)


@r.post("/ui/tokens/delete")
def token_delete(token: str = Form(...)):
    with core.db() as c:
        c.execute("DELETE FROM enroll_tokens WHERE token=? AND used_by IS NULL", (token,))
    return RedirectResponse("/ui/tokens?flash=revoked", status_code=303)


# ---------- audit ----------
def audit_table(rows) -> str:
    tr = "".join(f"<tr><td><small>{esc(a['ts'])}</small></td><td><a href='/ui/runners/{a['runner']}'>{esc(a['runner'])}</a></td><td>{esc(a['client'] if 'client' in a.keys() else '')}</td><td>{esc(a['op'])}</td><td>{esc(a['image'])}</td>"
                 f"<td>{a['input_chars']} → {a['output_chars']}</td><td>{'<span class=ok>allow</span>' if a['gate'] == 'allow' else '<span class=bad>block: ' + esc(a['gate_reason']) + '</span>'}{'' if a['app_ok'] else ' <span class=bad>(app error)</span>'}</td><td>{a['duration_s']}s</td></tr>" for a in rows)
    return "<table><tr><th>Time (UTC)</th><th>Runner</th><th>Client</th><th>Op</th><th>Image</th><th>Chars</th><th>Gate</th><th>Took</th></tr>" + (tr or "<tr><td colspan=8 class=muted>nothing yet</td></tr>") + "</table>"


@r.get("/ui/audit", response_class=HTMLResponse)
def audit(request: Request, runner: str = "", op: str = "", gate_: str = "", q: str = "", n: int = 200):
    if (g := gate(request)):
        return g
    where, args = [], []
    if runner:
        where.append("runner=?"); args.append(runner)
    if op:
        where.append("op=?"); args.append(op)
    if gate_ == "block":
        where.append("gate='block'")
    if gate_ == "error":
        where.append("app_ok=0")
    if q:
        where.append("(image LIKE ? OR image_id LIKE ? OR input_sha256 LIKE ? OR policy LIKE ?)"); args += [f"%{q}%"] * 4
    sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
    with core.db() as c:
        rows = c.execute(sql, (*args, n)).fetchall()
        ops = [x[0] for x in c.execute("SELECT DISTINCT op FROM audit")]
        rns = [x[0] for x in c.execute("SELECT DISTINCT runner FROM audit")]
    f = f"""<div class=card><form method=get>
Runner <select name=runner><option value=''>all</option>{"".join(f"<option {'selected' if x == runner else ''}>{esc(x)}</option>" for x in rns)}</select>
&nbsp; Op <select name=op><option value=''>all</option>{"".join(f"<option {'selected' if x == op else ''}>{esc(x)}</option>" for x in ops)}</select>
&nbsp; Show <select name=gate_><option value=''>everything</option><option value=block {'selected' if gate_ == 'block' else ''}>blocked only</option><option value=error {'selected' if gate_ == 'error' else ''}>app errors only</option></select>
&nbsp; Search <input type=text name=q value='{esc(q)}' placeholder='image, image id, input hash, policy'> <button>Filter</button>
&nbsp; <a href='/v1/admin/audit?n=5000' class=muted>JSON export</a></form></div>"""
    return page("Audit", "<h1>Audit</h1>" + f + audit_table(rows), "audit")


# ---------- alerts ----------
@r.get("/ui/alerts", response_class=HTMLResponse)
def alerts(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    cfg = core.get_config_raw()
    with core.db() as c:
        rows = c.execute("SELECT * FROM audit WHERE gate='block' OR app_ok=0 ORDER BY ts DESC LIMIT 100").fetchall()
    body = f"""<h1>Alerts</h1><div class=card><form method=post action='/ui/alerts/save'>
<p>Webhook URL <input type=url name=webhook value='{esc(cfg.get('webhook',''))}' placeholder='https://hooks.slack.com/... or any endpoint accepting JSON POST' style='min-width:30rem'> <button>Save</button></p>
<p class=muted>Every blocked output and every app error reported by a runner is POSTed as JSON (metadata only). Leave empty to disable.</p></form></div>
<h2>Blocked outputs and app errors</h2>{audit_table(rows)}"""
    return page("Alerts", body, "alerts", flash)


@r.post("/ui/alerts/save")
def alerts_save(webhook: str = Form("")):
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('webhook', ?)", (json.dumps(webhook.strip()),))
    return RedirectResponse("/ui/alerts?flash=saved", status_code=303)


# ---------- settings ----------
@r.get("/ui/settings", response_class=HTMLResponse)
def settings(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    cfg = core.get_config_raw()
    body = f"""<h1>Settings</h1><div class=card><form method=post action='/ui/settings/save'>
<p>Registry URL <input type=text name=registry value='{esc(cfg.get('registry',''))}' placeholder='https://raw.githubusercontent.com/Andrew1326/sealed/master/registry' style='min-width:30rem'></p>
<p>Sandbox runtime <input type=text name=runtime value='{esc(cfg.get('runtime',''))}' placeholder='runc (default) / runsc / kata-runtime'></p>
<p>Public URL of this control plane <input type=text name=public_url value='{esc(cfg.get('public_url',''))}' placeholder='https://control.example.com' style='min-width:30rem'> <small class=muted>used in the install one-liner</small></p>
<p><button>Save</button></p></form></div>
<div class=card><b>API</b><p class=muted>Everything on these pages is also available under <code>/v1/admin/*</code> with <code>Authorization: Bearer &lt;admin token&gt;</code>. The runner API is <code>/v1/enroll</code> and <code>/v1/runners/&lt;id&gt;/heartbeat</code>.</p></div>"""
    return page("Settings", body, "settings", flash)


@r.post("/ui/settings/save")
def settings_save(registry: str = Form(""), runtime: str = Form(""), public_url: str = Form("")):
    with core.db() as c:
        for k, v in (("registry", registry), ("runtime", runtime), ("public_url", public_url)):
            c.execute("INSERT OR REPLACE INTO config VALUES(?, ?)", (k, json.dumps(v.strip())))
    return RedirectResponse("/ui/settings?flash=saved", status_code=303)
