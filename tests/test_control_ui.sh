#!/usr/bin/env bash
# Control panel: login, policy editor validation, trust, tokens, per-runner override, audit filters, webhook alerts.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
T=$(mktemp -d); export SEALED_HOME=$T; export SEALED_CONTROL_DB=$T/control.sqlite; export SEALED_CONTROL_ADMIN_TOKEN=adm_ui
cp ~/.sealed/allowlist.json $T/
printf '%s\n' '{"ts":"2026-09-10T10:00:00Z","policy":"confidential","tier":"confidential","client":"app-a","image":"sealed/extract-qwen:0.3.0","image_id":"sha256:x","op":"summarize","input_sha256":"abc","input_chars":500,"output_chars":900,"app_ok":true,"gate":"block","gate_reason":"output repeats 60 consecutive input words, limit 40","duration_s":3.2}' > $T/audit.jsonl
.venv/bin/sealed-control > $T/control.log 2>&1 & CP=$!
# webhook receiver
python3 - $T/hook.json <<'PY' &
import http.server, json, sys
out = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        open(out, "w").write(self.rfile.read(int(self.headers["content-length"])).decode()); self.send_response(200); self.end_headers()
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", 8499), H).serve_forever()
PY
HK=$!
trap 'kill $CP $HK 2>/dev/null; rm -rf "$T"' EXIT
sleep 2
C=http://127.0.0.1:8480; J=$T/cookies
echo "== login: wrong token bounces, right token sets cookie"
curl -s -o /dev/null -w "  wrong -> %{http_code} %{redirect_url}\n" -X POST $C/ui/login -d token=nope
curl -s -c $J -o /dev/null -X POST $C/ui/login -d token=adm_ui
curl -s -b $J $C/ui/overview | grep -q "runners" && echo "  PASS overview renders with cookie"
curl -s -o /dev/null -w "%{redirect_url}\n" $C/ui/overview | grep -q login && echo "  PASS no cookie -> login"
echo "== policy editor: invalid YAML rejected, valid saved"
curl -s -b $J -o /dev/null -w "  invalid -> %{redirect_url}\n" -X POST $C/ui/policies/save --data-urlencode name=strict --data-urlencode $'text=name: strict\ntier: confidential\nallowed_ops: notalist'
curl -s -b $J -o /dev/null -X POST $C/ui/policies/save --data-urlencode name=strict --data-urlencode $'text=name: strict\ntier: confidential\nrequire_verified: true\nallowed_ops: [translate]\noutput:\n  max_chars: 5000\n  max_verbatim_span_words: 10\n'
curl -s -b $J $C/ui/policies | grep -q "policies?edit=strict" && echo "  PASS policy listed"
echo "== trust + token + settings + webhook"
curl -s -b $J -o /dev/null -X POST $C/ui/trust/add -d label=community --data-urlencode "key=$(cat ~/.sealed/keys/publisher.pub)"
NEW=$(curl -s -b $J -o /dev/null -w "%{redirect_url}" -X POST $C/ui/tokens/create -d label=vm-1 | sed 's/.*new=//')
echo "  token $NEW"
curl -s -b $J $C/ui/tokens?new=$NEW | grep -q "install.sh" && echo "  PASS token page shows install one-liner"
curl -s -b $J -o /dev/null -X POST $C/ui/settings/save -d runtime=runsc -d public_url=http://control.local:8480 -d registry=
curl -s -b $J -o /dev/null -X POST $C/ui/alerts/save -d webhook=http://127.0.0.1:8499/hook
echo "== runner enrols; override to policy 'strict' delivered as 'confidential'; blocked audit line triggers webhook"
$S enroll $C $NEW >/dev/null
RID=$(python3 -c "import json;print(json.load(open('$T/agent.json'))['runner_id'])")
curl -s -b $J -o /dev/null -X POST $C/ui/runners/$RID/override -d policy_name=strict -d runtime=
$S agent --once >/dev/null
grep -q "max_verbatim_span_words: 10" $T/policies/confidential.yaml && echo "  PASS override delivered as confidential"
grep -q "runsc" $T/runtime.txt && echo "  PASS fleet runtime delivered"
sleep 1; grep -q "blocked/errored" $T/hook.json && echo "  PASS webhook received: $(python3 -c "import json;d=json.load(open('$T/hook.json'));print(d['text'])")"
echo "== runner detail + audit filters"
curl -s -b $J $C/ui/runners/$RID | grep -q "Per-runner override" && echo "  PASS runner detail"
curl -s -b $J "$C/ui/audit?gate_=block" | grep -q "consecutive input words" && echo "  PASS audit filter shows the blocked job"
curl -s -b $J "$C/ui/audit?op=translate" | grep -q "consecutive input words" && echo "  FAIL filter" || echo "  PASS op filter excludes it"
curl -s -b $J "$C/ui/alerts" | grep -q "app-a" && echo "  PASS alerts page shows client label"
echo "== responsive invariant: no horizontal page scroll on any console page"
python3 - "$C" "$T" <<'PY'
import re, sys, urllib.request, http.cookiejar
base, tmp = sys.argv[1], sys.argv[2]
jar = http.cookiejar.MozillaCookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
op.open(urllib.request.Request(base + "/ui/login", data=b"token=adm_ui",
                               headers={"content-type": "application/x-www-form-urlencoded"}))
pages = ["/ui/overview", "/ui/runners", "/ui/policies", "/ui/trust", "/ui/tokens", "/ui/audit", "/ui/alerts", "/ui/settings"]
bad = []
for p in pages:
    html = op.open(base + p).read().decode()
    # every shrinkable container must declare min-width:0, else a wide table pushes the page sideways
    if "min-width:0" not in html:
        bad.append(p + ": missing min-width:0 rule")
    if 'name=viewport' not in html:
        bad.append(p + ": missing viewport meta")
print("  PASS responsive rules present on all pages" if not bad else "  FAIL " + "; ".join(bad))
sys.exit(1 if bad else 0)
PY
