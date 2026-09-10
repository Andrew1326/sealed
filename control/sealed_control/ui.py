"""Control panel: a dense operator console over the same SQLite state as the API.

Design system: see theme.py (adapted from the "Local SEO Console" variant).
Grammar per page: PageBar -> StatStrip -> the Object -> side rail. At lg+ workspace
pages pin to the viewport and each pane scrolls itself.
"""
import html
import json
import time
import urllib.parse
from typing import Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import app as core
from .theme import CSS, JS, icon

r = APIRouter()
COOKIE = "sealed_admin"

NAV = [
    ("Fleet", [("overview", "Overview", "/ui/overview"), ("runners", "Runners", "/ui/runners")]),
    ("Policy", [("policies", "Policies", "/ui/policies"), ("trust", "Trust", "/ui/trust"),
                ("tokens", "Enrol tokens", "/ui/tokens")]),
    ("Activity", [("audit", "Audit", "/ui/audit"), ("alerts", "Alerts", "/ui/alerts")]),
    ("", [("settings", "Settings", "/ui/settings")]),
]


EXTRA_NAV: list = []      # (section, key, label, href, icon_svg) added by extensions
EXTRA_ICONS: dict = {}


def add_nav(section: str, key: str, label: str, href: str, icon_svg: str = "") -> None:
    EXTRA_NAV.append((section, key, label, href))
    if icon_svg:
        EXTRA_ICONS[key] = icon_svg


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def q(x) -> str:
    return urllib.parse.quote(str(x or ""))


# ---------- health language: one module, every colour flows through it ----------
def runner_health(last_seen: Optional[float]) -> str:
    if not last_seen:
        return "none"
    d = time.time() - last_seen
    return "good" if d < 120 else "watch" if d < 600 else "action"


def ago(ts: Optional[float]) -> str:
    if not ts:
        return "never"
    d = int(time.time() - ts)
    if d < 90:
        return f"{d}s ago"
    if d < 5400:
        return f"{d // 60}m ago"
    if d < 172800:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


def stamp(ts: Optional[float], verb: str = "Seen") -> str:
    h = runner_health(ts)
    cls = "stamp stale" if h in ("watch", "action") else "stamp"
    return f'<span class="{cls}">{verb} {esc(ago(ts))}</span>'


def app_list(apps: list, keep: int = 2) -> str:
    """Dense app column: name the first few, count the rest. Keeps the row on one line."""
    names = [a.get("name", "") for a in apps if a.get("name")]
    if not names:
        return '<span class=dim>—</span>'
    shown = ", ".join(names[:keep])
    more = f' <span class="pill">+{len(names) - keep}</span>' if len(names) > keep else ""
    return f'{esc(shown)}{more}'


def op_badge(op: str) -> str:
    known = {"translate", "summarize", "convert", "extract", "classify"}
    return f'<span class="op {esc(op) if op in known else "other"}">{esc(op)}</span>'


def gate_cell(a) -> str:
    """The verdict only. The reason rides under the image so the row stays one line high."""
    if not a["app_ok"]:
        return '<span class="pill action">app error</span>'
    return ('<span class="pill good">allow</span>' if a["gate"] == "allow"
            else '<span class="pill action">blocked</span>')


def image_cell(a) -> str:
    reason = a["gate_reason"] if (a["gate"] != "allow" or not a["app_ok"]) else ""
    if reason:
        return (f'<div class=two-line title="{esc(reason)}">{esc(a["image"])}'
                f'<small class=bad>{esc(reason)}</small></div>')
    return esc(a["image"])



# ---------- shell ----------
def authed(request: Request) -> bool:
    return request.cookies.get(COOKIE) == core.ADMIN


def gate(request: Request):
    return None if authed(request) else RedirectResponse("/ui/login", status_code=303)


def nav_counts() -> dict:
    with core.db() as c:
        runners = c.execute("SELECT last_seen FROM runners").fetchall()
        tokens = c.execute("SELECT COUNT(*) FROM enroll_tokens WHERE used_by IS NULL").fetchone()[0]
        blocked = c.execute("SELECT COUNT(*) FROM audit WHERE gate='block' OR app_ok=0").fetchone()[0]
    cfg = core.get_config_raw()
    return {"runners": f'{sum(runner_health(r[0]) == "good" for r in runners)}/{len(runners)}',
            "policies": len(cfg.get("policies") or {}) or "", "trust": len(cfg.get("trusted_keys") or {}) or "",
            "tokens": tokens or "", "alerts": blocked or ""}


def page(title: str, body: str, active: str = "", crumbs: Optional[list] = None,
         flash: str = "", err: bool = False) -> HTMLResponse:
    counts = nav_counts()
    nav = [(label, list(items)) for label, items in NAV]
    for section, key, label, href in EXTRA_NAV:
        for sl, items in nav:
            if sl == section:
                items.append((key, label, href))
                break
        else:
            nav.insert(len(nav) - 1, (section, [(key, label, href)]))
    groups = ""
    for label, items in nav:
        links = "".join(
            f'<a href="{href}" class="{"on" if key == active else ""}">{EXTRA_ICONS.get(key) or icon(key)}<span>{name}</span>'
            f'<span class="count">{esc(counts.get(key, ""))}</span></a>' for key, name, href in items)
        groups += (f'<div class="nav-label">{esc(label)}</div>' if label else "") + links
    trail = crumbs or [("Fleet", None), (title, None)]
    cr = ""
    for i, (lbl, href) in enumerate(trail):
        if i:
            cr += '<span class="sep">/</span>'
        last = i == len(trail) - 1
        inner = esc(lbl)
        cr += (f'<a class="lv{" cur" if last else ""}" href="{href}">{inner}</a>' if href
               else f'<span class="lv{" cur" if last else ""}">{inner}</span>')
    fl = f'<div class="flash{" err" if err else ""}">{esc(flash)}</div>' if flash else ""
    return HTMLResponse(f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><link rel=icon href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23004ac6'/%3E%3Ctext x='16' y='22' font-family='system-ui' font-size='18' font-weight='700' fill='white' text-anchor='middle'%3ES%3C/text%3E%3C/svg%3E"><title>{esc(title)} · sealed control</title>
<style>{CSS}</style><script>{JS}</script></head><body>
<div class=scrim onclick=sealedNav()></div>
<aside class=sidebar>
  <div class=sidebar-head><div class=mark>S</div><div class=wordmark>sealed <span>control</span></div></div>
  <nav class=nav>{groups}</nav>
  <div class=side-foot>
    <button class="btn ghost" onclick=sealedTheme() title="Light / dark">{icon('theme')}<span>Theme</span></button>
    <span class=dim style="font-size:11px">{esc(core.EDITION["name"])}</span>
    <a class="btn ghost" href="/ui/logout" style="margin-left:auto">Log out</a>
  </div>
</aside>
<div class=shell>
  <header class=topbar>
    <button class=burger onclick=sealedNav() aria-label="Menu">☰</button>
    <div class=crumbs>{cr}</div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:.6rem">
      <form method=get action="/ui/audit" style="display:none" class=topsearch></form>
      <div class=avatar title="Signed in as admin">AD</div>
    </div>
  </header>
  <main>{fl}{body}</main>
</div></body></html>""")


# ---------- building blocks ----------
def strip(cells: list) -> str:
    """StatStrip: hairline KPI row. Cells are doors (href) or filters (pressed)."""
    out = ""
    for c in cells:
        label, value = esc(c["label"]), c["value"]
        chip = c.get("chip", "")
        inner = f'<p class="k">{label}</p><p class="v">{value}{chip}</p>'
        if c.get("href"):
            out += f'<a class=cell href="{c["href"]}"{" aria-pressed=true" if c.get("on") else ""}>{inner}</a>'
        else:
            out += f'<div class=cell>{inner}</div>'
    return f'<div class=strip><div class=strip-grid>{out}</div></div>'


def table(cols: list, rows: str, toolbar: str = "", empty: str = "Nothing here yet", empty_action: str = "",
          slack: bool = True) -> str:
    """slack=True lets the LAST column absorb leftover width (right-aligned), so every other
    column sits at content width instead of the browser spreading them out."""
    head = "".join(f'<th class="{c.get("cls","")}">{esc(c["label"])}</th>' for c in cols)
    body = rows or f'<tr><td colspan={len(cols)}><div class=tbl-empty><b>{esc(empty)}</b>{empty_action}</div></td></tr>'
    tb = f'<div class=tbl-toolbar>{toolbar}</div>' if toolbar else ""
    return (f'<div class="tbl-card{" slack" if slack else ""}">{tb}<div class=tbl-scroll><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div></div>')


def card(title: str, body: str, right: str = "") -> str:
    h = f'<div class=card-h><h2>{esc(title)}</h2><div class=right>{right}</div></div>' if title else ""
    return f'<section class=card>{h}<div class=card-b>{body}</div></section>'


# ---------- login ----------
@r.get("/ui/login", response_class=HTMLResponse)
def login_form(bad: int = 0):
    err = '<div class="flash err">That token is not the admin token.</div>' if bad else ""
    return HTMLResponse(f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><link rel=icon href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23004ac6'/%3E%3Ctext x='16' y='22' font-family='system-ui' font-size='18' font-weight='700' fill='white' text-anchor='middle'%3ES%3C/text%3E%3C/svg%3E"><title>sealed control</title>
<style>{CSS}</style><script>{JS}</script></head><body><div class=login-wrap><div class=login>
<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:1rem"><div class=mark>S</div>
<div class=wordmark style="font-size:17px">sealed <span>control</span></div></div>
{err}<div class="card pad"><form method=post>
<div class=field><label for=t>Admin token</label><input id=t type=password name=token autofocus autocomplete=current-password></div>
<button class="btn primary md" style="margin-top:.75rem;width:100%;justify-content:center">Sign in</button></form>
<p class=note style="margin:.75rem 0 0">The token is printed when the control plane starts, or set with
<code>SEALED_CONTROL_ADMIN_TOKEN</code>.</p></div>
<p class=note style="margin-top:1rem">This console shows fleet metadata only. Document content never leaves a runner.</p>
</div></div></body></html>""")


@r.post("/ui/login")
def login(token: str = Form(...)):
    if token != core.ADMIN:
        return RedirectResponse("/ui/login?bad=1", status_code=303)
    resp = RedirectResponse("/ui/overview", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=86400 * 7)
    return resp


@r.get("/ui/logout")
def logout():
    resp = RedirectResponse("/ui/login", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ---------- overview ----------
@r.get("/ui", response_class=HTMLResponse)
@r.get("/ui/overview", response_class=HTMLResponse)
def overview(request: Request):
    if (g := gate(request)):
        return g
    runners = core.list_runners()
    with core.db() as c:
        tot = c.execute("SELECT COUNT(*) n, SUM(gate='block') b, SUM(app_ok=0) e FROM audit").fetchone()
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
        day = c.execute("SELECT COUNT(*) FROM audit WHERE ts > ?", (since,)).fetchone()[0]
        recent = c.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT 40").fetchall()
    online = sum(x["online"] for x in runners)
    apps = sorted({a.get("name") for x in runners for a in x["apps"] if a.get("name")})
    blocked, errors = tot["b"] or 0, tot["e"] or 0
    ks = strip([
        {"label": "Runners", "value": len(runners), "href": "/ui/runners",
         "chip": f'<span class="pill {"good" if online == len(runners) and runners else "watch"}">{online} online</span>' if runners else ""},
        {"label": "Verified apps", "value": len(apps), "href": "/ui/runners"},
        {"label": "Jobs (24h)", "value": day, "href": "/ui/audit",
         "chip": f'<span class="pill">{tot["n"] or 0} total</span>' if (tot["n"] or 0) != day else ""},
        {"label": "Blocked by gate", "value": f'<span class="{"bad" if blocked else "dim"}">{blocked}</span>',
         "href": "/ui/audit?gate_=block"},
        {"label": "App errors", "value": f'<span class="{"bad" if errors else "dim"}">{errors}</span>',
         "href": "/ui/audit?gate_=error"},
    ])
    rows = "".join(
        f'<tr onclick="location=\'/ui/runners/{x["id"]}\'">'
        f'<td style="width:1px"><span class="dot {runner_health(x["last_seen"])}"></span></td>'
        f'<td class=flex-col><div class=two-line><a href="/ui/runners/{x["id"]}"><b>{esc(x["label"] or x["id"])}</b></a>'
        f'<small>{esc(x["hostname"] or x["id"])}</small></div></td>'
        f'<td class="flex-col hide-sm">{app_list(x["apps"])}</td>'
        f'<td class=hide-xl>{"GPU" if x["gpu"] else "CPU"} · <span class=dim>{esc(x["runtime"] or "runc")}</span></td>'
        f'<td>{x["jobs"]}</td><td>{stamp(x["last_seen"])}</td></tr>' for x in runners)
    tbl = table([{"label": ""}, {"label": "Runner"}, {"label": "Verified apps", "cls": "hide-sm"},
                 {"label": "Compute", "cls": "hide-xl"}, {"label": "Jobs"}, {"label": "Heartbeat"}], rows,
                empty="No runners enrolled",
                empty_action='<a class="btn primary" href="/ui/tokens" style="margin-top:.6rem">Create an enrol token</a>')
    feed = "".join(
        f'<div style="display:flex;gap:.5rem;align-items:baseline;padding:.4rem 0;border-bottom:1px solid var(--c-border)">'
        f'{op_badge(a["op"])}<span class="dim tnum" style="font-size:11.5px">{esc(a["input_chars"])}→{esc(a["output_chars"])}</span>'
        f'<span style="margin-left:auto;display:flex;gap:.4rem;align-items:baseline">'
        f'{"<span class=\'pill action\'>blocked</span>" if a["gate"] == "block" else "<span class=\'pill action\'>error</span>" if not a["app_ok"] else ""}'
        f'<span class="stamp">{esc(a["ts"][11:19])}</span></span></div>' for a in recent[:14])
    rail = (card("Recent jobs", feed or '<p class=dim>No jobs reported yet.</p>',
                 right='<a class="btn ghost" href="/ui/audit">Open audit</a>')
            + card("What this console can see",
                   '<p class=note>Runners report the SHA-256 of each input, its size, the image ID, the policy '
                   'and the gate verdict. Document text never leaves the machine that processed it: the sandbox '
                   'has no network and the agent has no access to job content.</p>'
                   '<p class=note style="margin-top:.5rem">Trusted publishers and policies flow the other way, '
                   'applied on the next heartbeat.</p>'))
    body = ks + f'<div class="split wide"><div class=pane><div class=pane-in>{tbl}</div></div>' \
                f'<div class=pane><div class="pane-in rail">{rail}</div></div></div>'
    pb = ('<div class=pagebar><h1>Fleet</h1><div class=meta>'
          f'<span class="pill accent">{online} of {len(runners)} online</span></div>'
          '<div class=actions><a class="btn secondary" href="/ui/tokens">Enrol a runner</a>'
          '<a class="btn primary" href="/ui/policies">Edit policies</a></div></div>')
    return page("Overview", f'<div class="page pinned">{pb}{body}</div>', "overview", [("Fleet", None), ("Overview", None)])


# ---------- runners ----------
@r.get("/ui/runners", response_class=HTMLResponse)
def runners(request: Request):
    if (g := gate(request)):
        return g
    rs = core.list_runners()
    warm = sum(len([p for p in x["pool"] if p.get("alive")]) for x in rs)
    ks = strip([
        {"label": "Runners", "value": len(rs)},
        {"label": "Online", "value": f'<span class="{"ok" if rs and all(x["online"] for x in rs) else ""}">{sum(x["online"] for x in rs)}</span>'},
        {"label": "With GPU", "value": sum(bool(x["gpu"]) for x in rs)},
        {"label": "Warm containers", "value": warm},
        {"label": "Jobs reported", "value": sum(x["jobs"] for x in rs), "href": "/ui/audit"},
    ])
    rows = "".join(
        f'<tr onclick="location=\'/ui/runners/{x["id"]}\'">'
        f'<td style="width:1px"><span class="dot {runner_health(x["last_seen"])}"></span></td>'
        f'<td class=flex-col><div class=two-line><a href="/ui/runners/{x["id"]}"><b>{esc(x["label"] or x["id"])}</b></a>'
        f'<small>{esc(x["id"])}</small></div></td>'
        f'<td class="flex-col hide-sm">{esc(x["hostname"])}</td>'
        f'<td class=hide-xl><span class=dim>{esc(x["version"] or "—")}</span></td>'
        f'<td>{len(x["apps"])}</td>'
        f'<td class=hide-xl>{"GPU" if x["gpu"] else "CPU"} · <span class=dim>{esc(x["runtime"] or "runc")}</span></td>'
        f'<td>{len([p for p in x["pool"] if p.get("alive")])}</td><td>{x["jobs"]}</td>'
        f'<td>{stamp(x["last_seen"])}</td></tr>' for x in rs)
    tbl = table([{"label": ""}, {"label": "Runner"}, {"label": "Host", "cls": "hide-sm"},
                 {"label": "Version", "cls": "hide-xl"}, {"label": "Apps"}, {"label": "Compute", "cls": "hide-xl"},
                 {"label": "Warm"}, {"label": "Jobs"}, {"label": "Heartbeat"}], rows,
                empty="No runners enrolled",
                empty_action='<a class="btn primary" href="/ui/tokens" style="margin-top:.6rem">Create an enrol token</a>')
    pb = ('<div class=pagebar><h1>Runners</h1><div class=meta><span class=stamp>Heartbeat every 30s</span></div>'
          '<div class=actions><a class="btn primary" href="/ui/tokens">Enrol a runner</a></div></div>')
    return page("Runners", f'<div class="page pinned">{pb}{ks}<div class=pane><div class=pane-in>{tbl}</div></div></div>',
                "runners", [("Fleet", None), ("Runners", None)])


@r.get("/ui/runners/{rid}", response_class=HTMLResponse)
def runner_detail(request: Request, rid: str, flash: str = ""):
    if (g := gate(request)):
        return g
    with core.db() as c:
        x = c.execute("SELECT * FROM runners WHERE id=?", (rid,)).fetchone()
        aud = c.execute("SELECT * FROM audit WHERE runner=? ORDER BY ts DESC LIMIT 200", (rid,)).fetchall()
        agg = c.execute("SELECT SUM(gate='block') b, SUM(app_ok=0) e FROM audit WHERE runner=?", (rid,)).fetchone()
    if not x:
        return page("Runner", '<div class=tbl-empty><b>Unknown runner</b>It may have been removed.</div>', "runners")
    apps = json.loads(x["apps"] or "[]")
    pool = json.loads(x["pool"] or "[]")
    ov = json.loads(x["overrides"] or "{}")
    cfg = core.get_config_raw()
    name = x["label"] or rid
    ks = strip([
        {"label": "Jobs reported", "value": x["jobs"], "href": f"/ui/audit?runner={rid}"},
        {"label": "Verified apps", "value": len(apps)},
        {"label": "Warm containers", "value": len([p for p in pool if p.get("alive")])},
        {"label": "Blocked", "value": f'<span class="{"bad" if agg["b"] else "dim"}">{agg["b"] or 0}</span>',
         "href": f"/ui/audit?runner={rid}&gate_=block"},
        {"label": "App errors", "value": f'<span class="{"bad" if agg["e"] else "dim"}">{agg["e"] or 0}</span>',
         "href": f"/ui/audit?runner={rid}&gate_=error"},
    ])
    pol_opts = "".join(f'<option value="{esc(n)}"{" selected" if ov.get("policy_name") == n else ""}>{esc(n)}</option>'
                       for n in (cfg.get("policies") or {}))
    app_rows = "".join(f'<tr><td class=flex-col><div class=two-line><b>{esc(a.get("name"))}</b>'
                       f'<small>{esc(", ".join(a.get("operations", [])))}</small></div></td>'
                       f'<td class=dim>{esc(a.get("version"))}</td></tr>' for a in apps)
    pool_rows = "".join(f'<tr><td class=flex-col><div class=two-line>{esc(p.get("image"))}'
                        f'<small>{"GPU" if p.get("gpu") else "CPU"} · {esc(p.get("jobs"))} jobs</small></div></td>'
                        f'<td class=dim>idle {esc(p.get("idle_s"))}s</td></tr>' for p in pool)
    rail = (
        card("Identity",
             f'<dl class=kv><dt>Runner id</dt><dd><code>{esc(rid)}</code></dd>'
             f'<dt>Host</dt><dd>{esc(x["hostname"] or "—")}</dd>'
             f'<dt>Runner version</dt><dd>{esc(x["version"] or "—")}</dd>'
             f'<dt>Compute</dt><dd>{"GPU" if x["gpu"] else "CPU"} · sandbox runtime <code>{esc(x["runtime"] or "runc")}</code></dd>'
             f'<dt>Enrolled</dt><dd>{time.strftime("%Y-%m-%d", time.gmtime(x["enrolled"]))}</dd>'
             f'<dt>Heartbeat</dt><dd>{stamp(x["last_seen"])}</dd></dl>')
        + card("Verified apps", table([{"label": "App"}, {"label": "Version"}], app_rows, empty="No apps reported"))
        + card("Warm pool", table([{"label": "Image"}, {"label": "Idle"}], pool_rows, empty="No warm containers"))
        + card("Per-runner override",
               f'<form method=post action="/ui/runners/{rid}/override">'
               '<div class=row><div class="field grow"><label>Confidential policy for this runner</label>'
               f'<select name=policy_name><option value="">Fleet default</option>{pol_opts}</select>'
               '<span class=hint>Delivered to this runner under the name <code>confidential</code>.</span></div>'
               '<div class="field grow"><label>Sandbox runtime</label>'
               f'<input type=text name=runtime value="{esc(ov.get("runtime", ""))}" placeholder="inherit fleet setting">'
               '<span class=hint><code>runsc</code> or <code>kata-runtime</code> if installed on that host.</span></div>'
               '</div><button class="btn primary" style="margin-top:.75rem">Save override</button></form>'))
    left = f'<div class=pane><div class=pane-in>{audit_table(aud, show_runner=False)}</div></div>'
    right = f'<div class=pane><div class="pane-in rail">{rail}</div></div>'
    pb = (f'<div class=pagebar><h1>{esc(name)}</h1><div class=meta>'
          f'<span class="dot {runner_health(x["last_seen"])}"></span>{stamp(x["last_seen"])}</div>'
          f'<div class=actions><a class="btn secondary" href="/ui/audit?runner={rid}">Audit</a>'
          f'<form class=inline method=post action="/ui/runners/{rid}/delete" '
          f'data-confirm="Remove {esc(name)}? It needs a new enrol token to come back."><button class="btn danger">Remove runner</button></form>'
          '</div></div>')
    return page(name, f'<div class="page pinned">{pb}{ks}<div class="split wide">{left}{right}</div></div>',
                "runners", [("Fleet", None), ("Runners", "/ui/runners"), (name, None)], flash)


@r.post("/ui/runners/{rid}/override")
def runner_override(rid: str, policy_name: str = Form(""), runtime: str = Form("")):
    ov = {k: v for k, v in {"policy_name": policy_name.strip(), "runtime": runtime.strip()}.items() if v}
    with core.db() as c:
        c.execute("UPDATE runners SET overrides=? WHERE id=?", (json.dumps(ov), rid))
    return RedirectResponse(f"/ui/runners/{rid}?flash=Override+saved.+Applied+on+the+next+heartbeat.", status_code=303)


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
    rows = ""
    for n, t in pol.items():
        d = yaml.safe_load(t) or {}
        ops = d.get("allowed_ops", ["*"])
        ops_txt = "any operation" if ops == ["*"] else ", ".join(ops)
        out = (d.get("output") or {}).get("max_chars")
        sub = f'{d.get("tier", "—")} · {ops_txt}' + (f' · max {out:,} chars' if isinstance(out, int) else "")
        ver = ('<span class="pill good">verified only</span>' if d.get("require_verified", True)
               else '<span class="pill action">any image</span>')
        rows += (f'<tr><td class=flex-col><div class=two-line>'
                 f'<a href="/ui/policies?edit={q(n)}"><b>{esc(n)}</b></a><small>{esc(sub)}</small></div></td>'
                 f'<td>{ver}</td>'
                 f'<td style="text-align:right"><a class="btn ghost" href="/ui/policies?edit={q(n)}">Edit</a>'
                 f'<form class=inline method=post action="/ui/policies/delete" data-confirm="Delete policy {esc(n)}?">'
                 f'<input type=hidden name=name value="{esc(n)}"><button class="btn ghost bad">Delete</button></form></td></tr>')
    tbl = table([{"label": "Policy"}, {"label": "Images"}, {"label": ""}], rows,
                empty="No fleet policies",
                empty_action='<p class=note style="justify-content:center">Runners use their local <code>policies/</code> until you publish one here.</p>')
    text = pol.get(edit, DEFAULT_POLICY if not edit else "")
    editor = card(f"Edit {edit}" if edit else "New policy",
                  '<form method=post action="/ui/policies/save">'
                  f'<div class=field><label>Name</label><input type=text name=name value="{esc(edit)}" placeholder="confidential" required></div>'
                  f'<div class=field style="margin-top:.6rem"><label>YAML</label><textarea name=text spellcheck=false>{esc(text)}</textarea></div>'
                  '<div style="display:flex;gap:.5rem;margin-top:.75rem;align-items:center">'
                  '<button class="btn primary">Validate and save</button>'
                  + ('<a class="btn ghost" href="/ui/policies">New policy</a>' if edit else "")
                  + '</div><p class=note style="margin-top:.6rem">Saved policies reach every runner on its next heartbeat '
                    'and take precedence over the files in the runner\'s repo.</p></form>')
    pb = ('<div class=pagebar><h1>Policies</h1><div class=meta><span class=stamp>Distributed on the next heartbeat</span></div></div>')
    body = (f'<div class="split inbox"><div class=pane><div class=pane-in>{tbl}</div></div>'
            f'<div class=pane><div class="pane-in rail">{editor}</div></div></div>')
    return page("Policies", f'<div class="page pinned">{pb}{body}</div>', "policies",
                [("Policy", None), ("Policies", None)], flash, bool(err))


@r.post("/ui/policies/save")
def policy_save(name: str = Form(...), text: str = Form(...)):
    try:
        d = yaml.safe_load(text) or {}
        assert isinstance(d, dict), "policy must be a YAML mapping"
        for k in ("name", "tier"):
            assert k in d, f"missing '{k}'"
        assert isinstance(d.get("allowed_ops", ["*"]), list), "allowed_ops must be a list"
        out = d.get("output", {}) or {}
        assert isinstance(out.get("max_chars", 1), int) and isinstance(out.get("max_verbatim_span_words", 0), int), \
            "output limits must be integers"
    except Exception as e:
        return RedirectResponse(f"/ui/policies?edit={q(name)}&err=1&flash=Invalid+policy:+{q(str(e))}", status_code=303)
    pol = dict(core.get_config_raw().get("policies", {}))
    pol[name.strip()] = text
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('policies', ?)", (json.dumps(pol),))
    return RedirectResponse(f"/ui/policies?edit={q(name)}&flash=Policy+saved", status_code=303)


@r.post("/ui/policies/delete")
def policy_delete(name: str = Form(...)):
    pol = dict(core.get_config_raw().get("policies", {}))
    pol.pop(name, None)
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('policies', ?)", (json.dumps(pol),))
    return RedirectResponse("/ui/policies?flash=Policy+deleted", status_code=303)


# ---------- trust ----------
@r.get("/ui/trust", response_class=HTMLResponse)
def trust(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    keys = core.get_config_raw().get("trusted_keys", {})
    rows = "".join(
        f'<tr><td class=flex-col><b>{esc(l)}</b></td><td class="wrap"><code>{esc(k)}</code></td>'
        f'<td style="text-align:right"><form class=inline method=post action="/ui/trust/delete" '
        f'data-confirm="Stop trusting {esc(l)}? Runners will refuse new installs signed by this key.">'
        f'<input type=hidden name=key value="{esc(k)}"><button class="btn ghost bad">Remove</button></form></td></tr>'
        for k, l in keys.items())
    tbl = table([{"label": "Publisher"}, {"label": "Ed25519 public key"}, {"label": ""}], rows,
                empty="No trusted publishers",
                empty_action='<p class=note style="justify-content:center">Runners refuse every registry entry until a key is trusted.</p>')
    form = card("Trust a publisher",
                '<form method=post action="/ui/trust/add"><div class=row>'
                '<div class="field grow"><label>Label</label><input type=text name=label placeholder="sealed community" required></div>'
                '<div class="field grow"><label>Public key</label><input type=text name=key placeholder="base64 Ed25519 key" required></div>'
                '</div><button class="btn primary" style="margin-top:.75rem">Trust publisher</button>'
                '<p class=note style="margin-top:.6rem">A publisher signs the SOURCE of an app, not an image. Runners '
                'still build it locally and run the full admission pipeline before it can touch confidential data.</p></form>')
    pb = '<div class=pagebar><h1>Trusted publishers</h1></div>'
    body = (f'<div class="split"><div class=pane><div class=pane-in>{tbl}</div></div>'
            f'<div class=pane><div class="pane-in rail">{form}</div></div></div>')
    return page("Trust", f'<div class="page pinned">{pb}{body}</div>', "trust", [("Policy", None), ("Trust", None)], flash)


@r.post("/ui/trust/add")
def trust_add(label: str = Form(...), key: str = Form(...)):
    keys = dict(core.get_config_raw().get("trusted_keys", {}))
    keys[key.strip()] = label.strip()
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('trusted_keys', ?)", (json.dumps(keys),))
    return RedirectResponse("/ui/trust?flash=Publisher+trusted", status_code=303)


@r.post("/ui/trust/delete")
def trust_delete(key: str = Form(...)):
    keys = dict(core.get_config_raw().get("trusted_keys", {}))
    keys.pop(key, None)
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('trusted_keys', ?)", (json.dumps(keys),))
    return RedirectResponse("/ui/trust?flash=Publisher+removed", status_code=303)


# ---------- enrol tokens ----------
@r.get("/ui/tokens", response_class=HTMLResponse)
def tokens(request: Request, new: str = "", flash: str = ""):
    if (g := gate(request)):
        return g
    with core.db() as c:
        rows_db = c.execute("SELECT * FROM enroll_tokens ORDER BY created DESC").fetchall()
    rows = ""
    for t in rows_db:
        used = (f'<a class=pill href="/ui/runners/{t["used_by"]}">used</a>' if t["used_by"]
                else '<span class="pill good">unused</span>')
        act = ("" if t["used_by"] else
               f'<form class=inline method=post action="/ui/tokens/delete" data-confirm="Revoke this token?">'
               f'<input type=hidden name=token value="{esc(t["token"])}"><button class="btn ghost bad">Revoke</button></form>')
        rows += (f'<tr><td class=flex-col><div class=two-line><b>{esc(t["label"] or "—")}</b>'
                 f'<small><code>{esc(t["token"][:12])}…</code> · created {esc(ago(t["created"]))}</small></div></td>'
                 f'<td>{used}</td><td>{act}</td></tr>')
    tbl = table([{"label": "Token"}, {"label": "Status"}, {"label": ""}], rows, empty="No enrol tokens")
    base = core.get_config_raw().get("public_url") or core.PUBLIC_URL
    reveal = ""
    if new:
        pin = f' \\\n  SEALED_CONTROL_FINGERPRINT={core.FINGERPRINT}' if core.FINGERPRINT else ""
        one_liner = (f'SEALED_CONTROL={base} SEALED_ENROLL_TOKEN={new}{pin} \\\n'
                     '  bash -c "$(curl -fsSL https://raw.githubusercontent.com/Andrew1326/sealed/master/deploy/install.sh)"')
        reveal = card("New token — shown once",
                      f'<p style="margin:0 0 .5rem"><code style="font-size:13px">{esc(new)}</code></p>'
                      f'<p class=note style="margin:0 0 .4rem">Run this on the machine that will hold the data:</p>'
                      f'<pre><code>{esc(one_liner)}</code></pre>'
                      '<p class=note style="margin-top:.5rem">Or paste <code>deploy/cloud-init.yaml</code> as the VM\'s '
                      'user data with the same two values. The token works once.</p>',
                      right='<span class="pill accent">copy it now</span>')
    form = card("Create an enrol token",
                '<form method=post action="/ui/tokens/create"><div class=field><label>Label</label>'
                '<input type=text name=label placeholder="office-server" required>'
                '<span class=hint>Names the machine in this console.</span></div>'
                '<button class="btn primary" style="margin-top:.75rem">Create token</button></form>')
    pb = '<div class=pagebar><h1>Enrol tokens</h1><div class=meta><span class=stamp>Single use</span></div></div>'
    body = (f'<div class="split"><div class=pane><div class=pane-in>{tbl}</div></div>'
            f'<div class=pane><div class="pane-in rail">{reveal}{form}</div></div></div>')
    return page("Enrol tokens", f'<div class="page pinned">{pb}{body}</div>', "tokens",
                [("Policy", None), ("Enrol tokens", None)], flash)


@r.post("/ui/tokens/create")
def token_create(label: str = Form(...)):
    d = core.make_token(core.TokenReq(label=label))
    return RedirectResponse(f"/ui/tokens?new={d['token']}", status_code=303)


@r.post("/ui/tokens/delete")
def token_delete(token: str = Form(...)):
    with core.db() as c:
        c.execute("DELETE FROM enroll_tokens WHERE token=? AND used_by IS NULL", (token,))
    return RedirectResponse("/ui/tokens?flash=Token+revoked", status_code=303)


# ---------- audit ----------
def audit_table(rows, show_runner: bool = True, toolbar: str = "") -> str:
    tr = ""
    for a in rows:
        wide = (f'<td class=hide-sm><a href="/ui/runners/{a["runner"]}">{esc(a["runner"])}</a></td>'
                f'<td class=hide-xl>{esc(a["client"] or "—") if "client" in a.keys() else "—"}</td>') if show_runner else ""
        chars = f'<td class=hide-sm>{esc(a["input_chars"])} → {esc(a["output_chars"])}</td>' if show_runner else ""
        tr += (f'<tr><td><span class=stamp>{esc(a["ts"][5:10])} {esc(a["ts"][11:19])}</span></td>{wide}'
               f'<td>{op_badge(a["op"])}</td>'
               f'<td class=flex-col>{image_cell(a)}</td>{chars}'
               f'<td>{gate_cell(a)}</td><td>{esc(a["duration_s"])}s</td></tr>')
    cols = [{"label": "Time (UTC)"}]
    if show_runner:
        cols += [{"label": "Runner", "cls": "hide-sm"}, {"label": "Client", "cls": "hide-xl"}]
    cols += [{"label": "Op"}, {"label": "Image"}]
    if show_runner:
        cols.append({"label": "Chars", "cls": "hide-sm"})
    cols += [{"label": "Gate"}, {"label": "Took"}]
    return table(cols, tr, toolbar=toolbar, empty="No jobs match this view")


@r.get("/ui/audit", response_class=HTMLResponse)
def audit(request: Request, runner: str = "", op: str = "", gate_: str = "", q_: str = "", q: str = "", n: int = 300):
    if (g := gate(request)):
        return g
    term = q or q_
    where, args = [], []
    if runner:
        where.append("runner=?")
        args.append(runner)
    if op:
        where.append("op=?")
        args.append(op)
    if gate_ == "block":
        where.append("gate='block'")
    if gate_ == "error":
        where.append("app_ok=0")
    if term:
        where.append("(image LIKE ? OR image_id LIKE ? OR input_sha256 LIKE ? OR policy LIKE ?)")
        args += [f"%{term}%"] * 4
    sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
    with core.db() as c:
        rows = c.execute(sql, (*args, n)).fetchall()
        ops = [x[0] for x in c.execute("SELECT DISTINCT op FROM audit")]
        rns = [dict(x) for x in c.execute("SELECT DISTINCT runner FROM audit")]
        tot = c.execute("SELECT COUNT(*) n, SUM(gate='block') b, SUM(app_ok=0) e, SUM(input_chars) ic FROM audit").fetchone()
    ks = strip([
        {"label": "Jobs reported", "value": tot["n"] or 0, "href": "/ui/audit", "on": not (gate_ or runner or op or term)},
        {"label": "Allowed", "value": f'<span class=ok>{(tot["n"] or 0) - (tot["b"] or 0) - (tot["e"] or 0)}</span>'},
        {"label": "Blocked by gate", "value": f'<span class="{"bad" if tot["b"] else "dim"}">{tot["b"] or 0}</span>',
         "href": "/ui/audit?gate_=block", "on": gate_ == "block"},
        {"label": "App errors", "value": f'<span class="{"bad" if tot["e"] else "dim"}">{tot["e"] or 0}</span>',
         "href": "/ui/audit?gate_=error", "on": gate_ == "error"},
        {"label": "Characters processed", "value": f'{(tot["ic"] or 0):,}'},
    ])
    sel_r = "".join(f'<option value="{esc(x["runner"])}"{" selected" if x["runner"] == runner else ""}>{esc(x["runner"])}</option>' for x in rns)
    sel_o = "".join(f'<option{" selected" if x == op else ""}>{esc(x)}</option>' for x in ops)
    toolbar = (f'<form method=get style="display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;width:100%">'
               f'<input type=text name=q value="{esc(term)}" placeholder="Search image, image id, input hash, policy">'
               f'<select name=runner><option value="">All runners</option>{sel_r}</select>'
               f'<select name=op><option value="">All operations</option>{sel_o}</select>'
               f'<select name=gate_><option value="">Everything</option>'
               f'<option value=block{" selected" if gate_ == "block" else ""}>Blocked only</option>'
               f'<option value=error{" selected" if gate_ == "error" else ""}>App errors only</option></select>'
               f'<button class="btn secondary">Filter</button>'
               f'<a class="btn ghost" href="/ui/audit">Clear</a>'
               f'<a class="btn ghost" style="margin-left:auto" href="/v1/admin/audit?n=5000">JSON export</a></form>')
    filt = []
    if runner:
        filt.append(f'<span class="pill accent">runner {esc(runner)}</span>')
    if op:
        filt.append(f'<span class="pill accent">op {esc(op)}</span>')
    if gate_:
        filt.append(f'<span class="pill accent">{esc(gate_)} only</span>')
    if term:
        filt.append(f'<span class="pill accent">“{esc(term)}”</span>')
    pb = ('<div class=pagebar><h1>Audit</h1><div class=meta>' + "".join(filt) +
          f'<span class=stamp>{len(rows)} shown</span></div></div>')
    body = f'<div class=pane><div class=pane-in>{audit_table(rows, toolbar=toolbar)}</div></div>'
    return page("Audit", f'<div class="page pinned">{pb}{ks}{body}</div>', "audit", [("Activity", None), ("Audit", None)])


# ---------- alerts ----------
@r.get("/ui/alerts", response_class=HTMLResponse)
def alerts(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    cfg = core.get_config_raw()
    with core.db() as c:
        rows = c.execute("SELECT * FROM audit WHERE gate='block' OR app_ok=0 ORDER BY ts DESC LIMIT 200").fetchall()
        tot = c.execute("SELECT SUM(gate='block') b, SUM(app_ok=0) e FROM audit").fetchone()
    hook = cfg.get("webhook", "")
    ks = strip([
        {"label": "Blocked by gate", "value": f'<span class="{"bad" if tot["b"] else "dim"}">{tot["b"] or 0}</span>'},
        {"label": "App errors", "value": f'<span class="{"bad" if tot["e"] else "dim"}">{tot["e"] or 0}</span>'},
        {"label": "Webhook", "value": '<span class="pill good">on</span>' if hook else '<span class="pill">off</span>'},
    ])
    form = card("Webhook",
                '<form method=post action="/ui/alerts/save"><div class=field><label>Endpoint</label>'
                f'<input type=url name=webhook value="{esc(hook)}" placeholder="https://hooks.slack.com/services/…">'
                '<span class=hint>Every blocked output and app error is POSTed as JSON. Metadata only. Empty disables it.</span>'
                '</div><button class="btn primary" style="margin-top:.75rem">Save</button></form>')
    pb = ('<div class=pagebar><h1>Alerts</h1><div class=meta><span class=stamp>Blocked outputs and app errors</span>'
          '</div></div>')
    body = (f'<div class="split wide"><div class=pane><div class=pane-in>{audit_table(rows)}</div></div>'
            f'<div class=pane><div class="pane-in rail">{form}'
            + card("What triggers an alert",
                   '<p class=note>The output gate blocked a result, or an app failed. A blocked output means a '
                   'verified app tried to return something the policy forbids: too large, unexpected fields, or too '
                   'much of the input copied out verbatim.</p>') +
            '</div></div></div>')
    return page("Alerts", f'<div class="page pinned">{pb}{ks}{body}</div>', "alerts",
                [("Activity", None), ("Alerts", None)], flash)


@r.post("/ui/alerts/save")
def alerts_save(webhook: str = Form("")):
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO config VALUES('webhook', ?)", (json.dumps(webhook.strip()),))
    return RedirectResponse("/ui/alerts?flash=Webhook+saved", status_code=303)


# ---------- settings ----------
@r.get("/ui/settings", response_class=HTMLResponse)
def settings(request: Request, flash: str = ""):
    if (g := gate(request)):
        return g
    cfg = core.get_config_raw()
    fleet = card("Fleet defaults",
                 '<form method=post action="/ui/settings/save">'
                 '<div class=field><label>Registry</label>'
                 f'<input type=text name=registry value="{esc(cfg.get("registry", ""))}" '
                 'placeholder="https://raw.githubusercontent.com/Andrew1326/sealed/master/registry">'
                 '<span class=hint>Where runners look for signed app sources.</span></div>'
                 '<div class=field style="margin-top:.6rem"><label>Sandbox runtime</label>'
                 f'<input type=text name=runtime value="{esc(cfg.get("runtime", ""))}" placeholder="runc (default) · runsc · kata-runtime">'
                 '<span class=hint>gVisor or Kata put a user-space kernel between an app and the host. Runners fall '
                 'back to runc and say so if it is not installed.</span></div>'
                 '<div class=field style="margin-top:.6rem"><label>Public URL of this control plane</label>'
                 f'<input type=text name=public_url value="{esc(cfg.get("public_url", ""))}" placeholder="https://control.example.com">'
                 '<span class=hint>Used in the enrol one-liner.</span></div>'
                 '<button class="btn primary" style="margin-top:.75rem">Save settings</button></form>')
    api = card("API",
               '<p class=note>Everything in this console is also available as JSON under <code>/v1/admin/*</code> with '
               '<code>Authorization: Bearer &lt;admin token&gt;</code>. Runners use <code>/v1/enroll</code> and '
               '<code>/v1/runners/&lt;id&gt;/heartbeat</code>.</p>'
               '<p class=note style="margin-top:.5rem">The admin token is set with <code>SEALED_CONTROL_ADMIN_TOKEN</code> '
               'and printed at startup when unset.</p>')
    tls = card("Transport",
               (f'<p class=note><span class="pill good">TLS on</span> Certificate fingerprint <code>{esc(core.FINGERPRINT)}</code>. '
                'Runners enrolled with this fingerprint accept only this certificate, so a self-signed cert is safe to use.</p>')
               if core.FINGERPRINT else
               '<p class=note><span class="pill action">plain http</span> Fine on localhost or behind a TLS reverse proxy. '
               'For direct exposure run <code>sealed-control cert --host &lt;name&gt;</code> and start with '
               '<code>SEALED_CONTROL_CERT</code> / <code>SEALED_CONTROL_KEY</code>.</p>')
    boundary = card("Data boundary",
                    '<p class=note>This service stores runner registrations, the policies and trusted keys you publish, '
                    'and job metadata: timestamps, operations, image IDs, input hashes and sizes, gate verdicts. It has '
                    'no route to document content, and runners have no code path that would send it.</p>')
    pb = '<div class=pagebar><h1>Settings</h1></div>'
    body = (f'<div class="split"><div class=pane><div class="pane-in rail">{fleet}</div></div>'
            f'<div class=pane><div class="pane-in rail">{tls}{api}{boundary}</div></div></div>')
    return page("Settings", f'<div class="page pinned">{pb}{body}</div>', "settings", [("Settings", None)], flash)


@r.post("/ui/settings/save")
def settings_save(registry: str = Form(""), runtime: str = Form(""), public_url: str = Form("")):
    with core.db() as c:
        for k, v in (("registry", registry), ("runtime", runtime), ("public_url", public_url)):
            c.execute("INSERT OR REPLACE INTO config VALUES(?, ?)", (k, json.dumps(v.strip())))
    return RedirectResponse("/ui/settings?flash=Settings+saved", status_code=303)
