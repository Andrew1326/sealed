#!/usr/bin/env bash
# Control plane: enrol a runner, heartbeat with audit metadata, push config, dashboard renders.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
T=$(mktemp -d); export SEALED_HOME=$T; export SEALED_CONTROL_DB=$T/control.sqlite; export SEALED_CONTROL_ADMIN_TOKEN=adm_test
cp ~/.sealed/allowlist.json $T/ 2>/dev/null || echo '{}' > $T/allowlist.json
tail -n 5 ~/.sealed/audit.jsonl > $T/audit.jsonl 2>/dev/null || true
.venv/bin/sealed-control > $T/control.log 2>&1 & CP=$!
trap 'kill $CP 2>/dev/null; rm -rf "$T"' EXIT
sleep 2
C=http://127.0.0.1:8480; H="authorization: Bearer adm_test"
echo "== admin creates an enrolment token"
TOK=$(curl -sf -X POST $C/v1/admin/enroll-tokens -H "$H" -H 'content-type: application/json' -d '{"label":"office-server"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
echo "  $TOK"
echo "== runner enrols and heartbeats (sends audit metadata, receives config)"
$S enroll $C $TOK
$S agent --once | python3 -c "import json,sys;d=json.load(sys.stdin);print('  sent_audit',d['sent_audit'])"
echo "== token cannot be reused"
OUT=$($S enroll $C $TOK 2>&1 || true); grep -q "403" <<<"$OUT" && echo "  PASS single-use" || { echo "  FAIL: $OUT"; exit 1; }
echo "== admin pushes a policy and a trusted key; runner applies them on next heartbeat"
PUB=$(cat ~/.sealed/keys/publisher.pub)
curl -sf -X PUT $C/v1/admin/config -H "$H" -H 'content-type: application/json' -d "{\"policies\":{\"confidential\":\"name: confidential\\ntier: confidential\\nrequire_verified: true\\nallowed_ops: [translate, convert]\\noutput:\\n  max_chars: 100000\\n\"},\"trusted_keys\":{\"$PUB\":\"sealed-community\"},\"runtime\":\"runsc\"}" >/dev/null
$S agent --once | python3 -c "import json,sys;d=json.load(sys.stdin);print('  changed:',d['changed'])"
grep -q "allowed_ops: \[translate, convert\]" $T/policies/confidential.yaml && echo "  PASS policy applied"
grep -q "sealed-community" $T/trusted_keys.json && echo "  PASS trusted key applied"
echo "== admin sees the runner and its audit"
curl -sf $C/v1/admin/runners -H "$H" | python3 -c "import json,sys;r=json.load(sys.stdin)[0];print('  runner',r['label'],r['hostname'],'online' if r['online'] else 'offline','apps:',len(r['apps']),'jobs:',r['jobs'])"
curl -sf "$C/v1/admin/audit?n=3" -H "$H" | python3 -c "import json,sys;a=json.load(sys.stdin);print('  audit rows:',len(a),'| first:',{k:a[0][k] for k in ('op','image','gate','input_chars')} if a else '-')"
echo "== dashboard"
curl -sf "$C/?token=adm_test" | grep -q "office-server" && echo "  PASS dashboard lists the runner"
curl -sf "$C/?token=wrong" | grep -q "office-server" && echo "  FAIL leaks" || echo "  PASS wrong token sees nothing"
echo "== nothing but metadata crossed: no document text in the control DB"
python3 - $T/control.sqlite <<'PY'
import sqlite3,sys
c=sqlite3.connect(sys.argv[1]); cols=[r[1] for r in c.execute("PRAGMA table_info(audit)")]
assert not any(k in cols for k in ("input","output","text")), cols
print("  PASS audit schema:", ", ".join(cols))
PY
