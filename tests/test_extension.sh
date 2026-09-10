#!/usr/bin/env bash
# Extension hook: a package can add pages, nav items and an edition name without forking the control plane.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); export SEALED_HOME=$T SEALED_CONTROL_DB=$T/c.sqlite SEALED_CONTROL_ADMIN_TOKEN=adm_ext SEALED_CONTROL_PORT=8484
mkdir -p $T/ext && cat > $T/ext/demo_ext.py <<'PY'
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
r = APIRouter()
def register(ctx):
    @r.get("/ui/demo", response_class=HTMLResponse)
    def demo(request: Request):
        if (g := ctx.ui.gate(request)):
            return g
        return ctx.ui.page("Demo", "<h1>Hello from an extension</h1>", "demo")
    ctx.app.include_router(r)
    ctx.add_nav("Enterprise", "demo", "Demo page", "/ui/demo")
    ctx.set_edition("demo-edition", ["demo"])
PY
PYTHONPATH=$T/ext SEALED_CONTROL_EXTENSIONS=demo_ext:register .venv/bin/sealed-control > $T/c.log 2>&1 & CP=$!
trap 'kill $CP 2>/dev/null; rm -rf "$T"' EXIT
sleep 2
C=http://127.0.0.1:8484
curl -sf $C/v1/edition | grep -q '"demo-edition"' && echo "  PASS edition reported"
curl -sf -c $T/j -o /dev/null -X POST $C/ui/login -d token=adm_ext
curl -sf -b $T/j $C/ui/demo | grep -q "Hello from an extension" && echo "  PASS extension page served behind the same login"
curl -sf -b $T/j $C/ui/overview | grep -q "Demo page" && echo "  PASS extension nav item in the sidebar"
curl -s -o /dev/null -w "%{redirect_url}" $C/ui/demo | grep -q login && echo "  PASS extension page gated"
