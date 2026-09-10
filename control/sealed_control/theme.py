"""Design system for the sealed console.

Adapted from the "Local SEO Console" variant (agent-kit/variants/design/seog/01):
hairline separation, whisper elevation, 12px radius, viewport-pinned workspace pages
with per-pane scrolling, one PageBar + StatStrip + Object + rail grammar, and a single
four-level health language. Tokens keep the original derivation structure; the accent
is the only thing a rebrand needs to change.

Domain mapping for sealed:
  good   = runner online, gate allowed, app ok
  watch  = runner late (heartbeat 2-10 min)
  action = runner offline, gate blocked, app error
  none   = never reported (gray, never green: absence is not success)
Group identity colours carry OPERATION identity (translate/convert/extract/...),
never severity, exactly as in the source variant.
"""

CSS = """
:root{
  --c-primary:#004ac6; --c-primary-fg:#ffffff;
  --c-success:#059669; --c-success-soft:#e7f6f0;
  --c-alert:#d92d20;   --c-alert-soft:#fdecea;
  --c-warning:#b45309; --c-warning-soft:#fdf3e3;

  --c-bg:#f6f7f9; --c-surface:#ffffff; --c-surface-2:#f3f4f6; --c-surface-3:#eceef1;
  --c-border:rgba(17,24,39,.08); --c-border-strong:rgba(17,24,39,.14);
  --c-text:#14161a; --c-muted:rgba(20,22,26,.62); --c-dim:rgba(20,22,26,.42);

  --shadow-card:0 1px 2px rgba(17,24,39,.05);
  --shadow-pop:0 10px 34px rgba(17,17,17,.12);

  --op-translate:#4f46e5; --op-summarize:#b45faf; --op-convert:#0f766e;
  --op-extract:#9a6b2f;   --op-classify:#5b6472;  --op-other:#5b6472;

  --radius-card:12px;
  --primary-hover:color-mix(in srgb,var(--c-primary) 82%,white);
  --primary-soft:color-mix(in srgb,var(--c-primary) 14%,transparent);
}
html[data-theme="dark"]{
  --c-primary:#5b8dff; --c-primary-fg:#ffffff;
  --c-success:#34d399; --c-success-soft:rgba(52,211,153,.15);
  --c-alert:#f87171;   --c-alert-soft:rgba(248,113,113,.15);
  --c-warning:#fbbf24; --c-warning-soft:rgba(251,191,36,.15);

  --c-bg:#0d0f12; --c-surface:#15181d; --c-surface-2:#1b1f25; --c-surface-3:#232830;
  --c-border:rgba(255,255,255,.10); --c-border-strong:rgba(255,255,255,.18);
  --c-text:#e7e9ee; --c-muted:rgba(231,233,238,.66); --c-dim:rgba(231,233,238,.42);

  --shadow-card:0 1px 2px rgba(0,0,0,.4);
  --shadow-pop:0 10px 34px rgba(0,0,0,.55);

  --op-translate:#8b8cf5; --op-summarize:#d78ad2; --op-convert:#4db6ac;
  --op-extract:#d0a464;   --op-classify:#9aa4b2;  --op-other:#9aa4b2;
}

*{box-sizing:border-box}
*{scrollbar-width:thin;scrollbar-color:var(--c-surface-3) transparent}
html,body{margin:0;padding:0}
body{background:var(--c-bg);color:var(--c-text);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
button:not(:disabled),[role=button]:not(:disabled){cursor:pointer}
.tnum{font-variant-numeric:tabular-nums}

/* ---------- shell ---------- */
.sidebar{position:fixed;inset:0 auto 0 0;width:16rem;background:var(--c-surface);border-right:1px solid var(--c-border);display:flex;flex-direction:column;z-index:40;transition:transform .18s ease}
.sidebar-head{height:4rem;display:flex;align-items:center;gap:.6rem;padding:0 1rem;border-bottom:1px solid var(--c-border)}
.mark{width:26px;height:26px;border-radius:7px;background:var(--c-primary);color:var(--c-primary-fg);display:grid;place-items:center;font-size:13px;font-weight:700;letter-spacing:-.02em;flex:0 0 auto}
.wordmark{font-weight:650;letter-spacing:-.01em}
.wordmark span{color:var(--c-dim);font-weight:500}
.nav{flex:1;overflow-y:auto;padding:.75rem .625rem}
.nav-label{padding:.5rem .625rem .25rem;font-size:10.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--c-dim)}
.nav a{display:flex;align-items:center;gap:.6rem;height:34px;padding:0 .625rem;border-radius:8px;color:var(--c-muted);font-size:13.5px;font-weight:500}
.nav a:hover{background:var(--c-surface-2);color:var(--c-text)}
.nav a.on{background:var(--primary-soft);color:var(--c-primary);font-weight:600}
.nav a .ico{width:16px;height:16px;flex:0 0 auto;opacity:.9}
.nav a .count{margin-left:auto;font-size:11px;color:var(--c-dim);font-variant-numeric:tabular-nums}
.nav a.on .count{color:var(--c-primary)}
.side-foot{border-top:1px solid var(--c-border);padding:.625rem;display:flex;align-items:center;gap:.5rem}
.shell{padding-left:16rem}
.topbar{position:sticky;top:0;z-index:30;height:4rem;display:flex;align-items:center;gap:.75rem;padding:0 1.5rem;background:color-mix(in srgb,var(--c-bg) 80%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--c-border)}
.crumbs{display:flex;align-items:center;gap:.4rem;min-width:0;font-size:13.5px;color:var(--c-muted)}
.crumbs .sep{flex:0 0 auto;color:var(--c-dim)}
.crumbs .lv{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.crumbs .cur{color:var(--c-text);font-weight:600}
main{padding:1rem 1.5rem;min-width:0;overflow-x:clip}
.burger{display:none;height:34px;width:34px;border-radius:8px;border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-muted);align-items:center;justify-content:center}
.scrim{display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:35}
@media(max-width:1023px){
  .sidebar{transform:translateX(-100%)}
  body.nav-open .sidebar{transform:none}
  body.nav-open .scrim{display:block}
  .shell{padding-left:0}
  .burger{display:inline-flex}
  .topbar{padding:0 1rem}
  main{padding:.875rem 1rem}
}

/* ---------- page grammar ---------- */
.page{display:flex;flex-direction:column;gap:.75rem}
@media(min-width:1024px){.page.pinned{height:calc(100dvh - 6rem)}.page.pinned>.pane{flex:1 1 auto;min-height:0}}
.pagebar{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .75rem;min-height:3rem;padding-bottom:.625rem;border-bottom:1px solid var(--c-border)}
.pagebar h1{margin:0;font-size:17px;font-weight:640;letter-spacing:-.015em}
.pagebar .meta{display:flex;min-width:0;align-items:center;gap:.5rem}
.pagebar .actions{margin-left:auto;display:flex;flex-wrap:wrap;align-items:center;gap:.5rem}

.strip{overflow:hidden;border:1px solid var(--c-border);border-radius:var(--radius-card);background:var(--c-surface);box-shadow:var(--shadow-card);flex:0 0 auto}
.strip-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:-1px 0 0 -1px}
@media(min-width:640px){.strip-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(min-width:1024px){.strip-grid{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}}
.cell{border-left:1px solid var(--c-border);border-top:1px solid var(--c-border);padding:.5rem .875rem;text-align:left;background:none;color:inherit;font:inherit;display:block;width:100%}
a.cell:hover,button.cell:hover{background:var(--c-surface-2)}
.cell[aria-pressed=true]{background:var(--primary-soft)}
.cell .k{margin:0;font-size:11.5px;font-weight:500;color:var(--c-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .v{margin:.125rem 0 0;display:flex;flex-wrap:wrap;align-items:baseline;gap:.125rem .5rem;font-size:20px;font-weight:640;font-variant-numeric:tabular-nums;line-height:1.2}

.split{display:grid;grid-template-columns:1fr;gap:1rem;min-height:0;flex:1}
/* grid/flex items default to min-width:auto and refuse to shrink below their content,
   which is what pushes a wide table into a horizontal PAGE scroll. Wide content must
   scroll inside its own container instead. */
.split>*,.pane,.pane>.pane-in,.tbl-card,.card,.card-b{min-width:0}
@media(min-width:1024px){
  .split{grid-template-columns:minmax(0,1.25fr) minmax(340px,1fr)}
  .split.wide{grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr)}
  .split.inbox{grid-template-columns:minmax(300px,.9fr) minmax(0,1.25fr)}
  .split>*{min-height:0}
}
.rail{display:flex;flex-direction:column;gap:1rem}

/* ScrollPane with edge fades */
.pane{position:relative;min-height:0;display:flex;flex-direction:column}
.pane>.pane-in>.tbl-card:first-child:last-child{flex:1 1 auto}
.pane>.pane-in{flex:1 1 auto;min-height:0;overflow-y:auto;scrollbar-color:var(--c-border-strong) transparent;display:flex;flex-direction:column;gap:1rem}
@media(max-width:1023px){.pane>.pane-in{overflow:visible}}
.pane::before,.pane::after{content:"";position:absolute;left:0;right:0;height:8px;pointer-events:none;opacity:0;transition:opacity .15s;z-index:5}
.pane::before{top:0;background:linear-gradient(to bottom,var(--c-bg),transparent)}
.pane::after{bottom:0;background:linear-gradient(to top,var(--c-bg),transparent)}
.pane.fade-t::before{opacity:1}
.pane.fade-b::after{opacity:1}

/* ---------- primitives ---------- */
.card{border:1px solid var(--c-border);border-radius:var(--radius-card);background:var(--c-surface);box-shadow:var(--shadow-card)}
.card.pad{padding:1rem}
.card-h{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;padding:.625rem .875rem;border-bottom:1px solid var(--c-border)}
.card-h h2{margin:0;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--c-dim)}
.card-h .right{margin-left:auto;display:flex;align-items:center;gap:.5rem}
.card-b{padding:.875rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;height:32px;padding:0 .75rem;border-radius:8px;border:1px solid transparent;font-size:12.5px;font-weight:550;white-space:nowrap}
.btn.md{height:40px;padding:0 1rem;font-size:14px}
.btn.primary{background:var(--c-primary);color:var(--c-primary-fg)}
.btn.primary:hover{background:var(--primary-hover)}
.btn.secondary{background:var(--c-surface-2);color:var(--c-text);border-color:var(--c-border)}
.btn.secondary:hover{background:var(--c-surface-3)}
.btn.ghost{color:var(--c-muted)}
.btn.ghost:hover{background:var(--c-surface-2);color:var(--c-text)}
.btn.ghost.bad{color:var(--c-alert)}
.btn.ghost.bad:hover{background:var(--c-alert-soft);color:var(--c-alert)}
.btn.danger{background:var(--c-alert-soft);color:var(--c-alert);border-color:color-mix(in srgb,var(--c-alert) 25%,transparent)}
.btn.danger:hover{background:color-mix(in srgb,var(--c-alert) 20%,transparent)}
.pill{display:inline-flex;align-items:center;gap:.3rem;border-radius:999px;padding:.1rem .55rem;font-size:11.5px;font-weight:550;white-space:nowrap;background:var(--c-surface-2);color:var(--c-muted)}
.pill.good{background:var(--c-success-soft);color:var(--c-success)}
.pill.watch{background:var(--c-warning-soft);color:var(--c-warning)}
.pill.action{background:var(--c-alert-soft);color:var(--c-alert)}
.pill.accent{background:var(--primary-soft);color:var(--c-primary)}
.dot{width:7px;height:7px;border-radius:999px;display:inline-block;flex:0 0 auto;background:var(--c-dim)}
.dot.good{background:var(--c-success)}
.dot.watch{background:var(--c-warning)}
.dot.action{background:var(--c-alert)}
.op{display:inline-flex;align-items:center;gap:.35rem;font-size:12px;font-weight:550;color:var(--op-other)}
.op::before{content:"";width:6px;height:6px;border-radius:2px;background:currentColor}
.op.translate{color:var(--op-translate)}.op.summarize{color:var(--op-summarize)}
.op.convert{color:var(--op-convert)}.op.extract{color:var(--op-extract)}.op.classify{color:var(--op-classify)}
.stamp{font-size:11px;color:var(--c-dim);white-space:nowrap}
.stamp.stale{background:var(--c-warning-soft);color:var(--c-warning);border-radius:999px;padding:.05rem .45rem}
.muted{color:var(--c-muted)}
.dim{color:var(--c-dim)}
.ok{color:var(--c-success)}
.bad{color:var(--c-alert)}
code,kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;background:var(--c-surface-2);border-radius:5px;padding:.08rem .3rem}
pre{margin:0;overflow-x:auto;background:var(--c-surface-2);border:1px solid var(--c-border);border-radius:8px;padding:.7rem .8rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.6}
pre code{background:none;padding:0}
input[type=text],input[type=url],input[type=password],select,textarea{height:40px;border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-text);border-radius:8px;padding:0 .7rem;font:inherit;font-size:13.5px;width:100%;max-width:100%}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--c-primary);box-shadow:0 0 0 3px var(--primary-soft)}
textarea{height:auto;min-height:340px;padding:.7rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;line-height:1.6;resize:vertical}
.field{display:flex;flex-direction:column;gap:.3rem;min-width:0}
.field>label{font-size:11.5px;font-weight:600;color:var(--c-muted)}
.field .hint{font-size:11.5px;color:var(--c-dim)}
.row{display:flex;flex-wrap:wrap;align-items:flex-end;gap:.75rem}
.row>.grow{flex:1 1 16rem;min-width:0}
.inline{display:inline}

/* ---------- table ---------- */
.tbl-card{display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--c-border);border-radius:var(--radius-card);background:var(--c-surface);box-shadow:var(--shadow-card);min-height:0}
.tbl-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;padding:.5rem .625rem;border-bottom:1px solid var(--c-border)}
.tbl-toolbar input,.tbl-toolbar select{height:32px;font-size:12.5px;width:auto;min-width:10rem}
.tbl-scroll{min-height:0;flex:1;overflow:auto}
table{border-collapse:collapse;width:100%}
thead th{position:sticky;top:0;z-index:10;background:var(--c-surface);white-space:nowrap;border-bottom:1px solid var(--c-border);padding:.5rem .75rem;text-align:left;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--c-dim)}
tbody td{height:40px;padding:0 .75rem;border-bottom:1px solid var(--c-border);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:13px;vertical-align:middle}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--c-surface-2)}
tbody td.flex-col{max-width:24rem;overflow:hidden;text-overflow:ellipsis}
tbody td.flex-col>.two-line{min-width:0}
tbody td.flex-col>.two-line *{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* one column absorbs the slack so the rest stay at content width */
.tbl-card.slack thead th:last-child,.tbl-card.slack tbody td:last-child{width:100%;text-align:right}
tbody td.wrap{white-space:normal}
.tbl-empty{padding:2.25rem 1rem;text-align:center;color:var(--c-muted)}
.tbl-empty b{display:block;margin-bottom:.25rem;color:var(--c-text);font-weight:600}
.two-line{display:flex;flex-direction:column;line-height:1.25}
.two-line small{color:var(--c-dim);font-size:11px}
@media(max-width:1279px){.hide-xl{display:none}}
@media(max-width:767px){.hide-sm{display:none}}

/* ---------- misc ---------- */
.flash{display:flex;gap:.5rem;align-items:flex-start;background:var(--primary-soft);border-left:3px solid var(--c-primary);border-radius:8px;padding:.6rem .8rem;font-size:13px;margin-bottom:.75rem}
.flash.err{background:var(--c-alert-soft);border-left-color:var(--c-alert);color:var(--c-alert)}
.note{font-size:12px;color:var(--c-muted);display:flex;gap:.4rem;align-items:flex-start;line-height:1.5}
.kv{display:grid;grid-template-columns:auto 1fr;gap:.4rem .9rem;font-size:13px;align-items:baseline}
.kv dt{color:var(--c-muted);font-size:11.5px;white-space:nowrap}
.kv dd{margin:0;min-width:0;overflow-wrap:anywhere}
.login-wrap{min-height:100dvh;display:grid;place-items:center;padding:1.5rem}
.login{width:100%;max-width:23rem}
.avatar{width:32px;height:32px;border-radius:999px;background:var(--c-primary);color:var(--c-primary-fg);display:grid;place-items:center;font-size:12px;font-weight:650}
.seg{display:inline-flex;border:1px solid var(--c-border);border-radius:8px;overflow:hidden}
.seg a{padding:.3rem .6rem;font-size:12px;color:var(--c-muted);background:var(--c-surface)}
.seg a.on{background:var(--primary-soft);color:var(--c-primary);font-weight:600}
.seg a+a{border-left:1px solid var(--c-border)}
"""

JS = """
(function(){
  var t=localStorage.getItem('sealed-theme');
  if(t) document.documentElement.setAttribute('data-theme',t);
  else if(window.matchMedia&&matchMedia('(prefers-color-scheme:dark)').matches) document.documentElement.setAttribute('data-theme','dark');
})();
function sealedTheme(){
  var d=document.documentElement, n=d.getAttribute('data-theme')==='dark'?'light':'dark';
  d.setAttribute('data-theme',n); try{localStorage.setItem('sealed-theme',n)}catch(e){}
}
function sealedNav(){document.body.classList.toggle('nav-open')}
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('.pane').forEach(function(p){
    var s=p.querySelector('.pane-in'); if(!s) return;
    function upd(){
      p.classList.toggle('fade-t', s.scrollTop>4);
      p.classList.toggle('fade-b', s.scrollHeight-s.clientHeight-s.scrollTop>4);
    }
    s.addEventListener('scroll',upd,{passive:true});
    addEventListener('resize',upd); new MutationObserver(upd).observe(s,{childList:true,subtree:true}); upd();
  });
  document.querySelectorAll('form[data-confirm]').forEach(function(f){
    f.addEventListener('submit',function(e){ if(!confirm(f.getAttribute('data-confirm'))) e.preventDefault(); });
  });
});
"""

ICONS = {
    "overview": '<path d="M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z"/>',
    "runners": '<path d="M3 5h18v6H3zM3 13h18v6H3z"/><circle cx="7" cy="8" r="1.2" fill="currentColor"/><circle cx="7" cy="16" r="1.2" fill="currentColor"/>',
    "policies": '<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/>',
    "trust": '<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "tokens": '<path d="M15 7a4 4 0 11-3.9 5H8v3H5v-3H3v-2h8.1A4 4 0 0115 7z"/>',
    "audit": '<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    "alerts": '<path d="M12 4a6 6 0 016 6v4l2 3H4l2-3v-4a6 6 0 016-6z"/><path d="M10 20h4"/>',
    "theme": '<circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
}


def icon(name: str) -> str:
    return (f'<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round">{ICONS.get(name, "")}</svg>')
