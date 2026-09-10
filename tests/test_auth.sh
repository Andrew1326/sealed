#!/usr/bin/env bash
# Gateway auth: dev mode on localhost only; with keys, every /v1 call needs one; policy restriction; client in audit.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
export SEALED_HOME=$(mktemp -d); cp ~/.sealed/allowlist.json $SEALED_HOME/
echo "== no keys: refuses to bind a non-localhost address"
OUT=$($S serve --host 0.0.0.0 --port 8479 2>&1 || true); grep -q "refusing to bind" <<<"$OUT" && echo "  PASS"
echo "== no keys: localhost dev mode works"
$S serve --port 8479 >/dev/null 2>&1 & GW=$!; sleep 2
curl -sf localhost:8479/v1/apps >/dev/null && echo "  PASS open on localhost"
kill $GW; sleep 1
echo "== with keys: unauthenticated refused, wrong key refused, right key works, policy restriction enforced"
K1=$($S keys create --label app-a | head -1)
K2=$($S keys create --label app-b --policy standard | head -1)
$S serve --port 8479 >/dev/null 2>&1 & GW=$!; sleep 2
[ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8479/v1/apps)" = 401 ] && echo "  PASS no key -> 401"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H 'authorization: Bearer sk_nope' localhost:8479/v1/apps)" = 401 ] && echo "  PASS bad key -> 401"
curl -sf -H "authorization: Bearer $K1" localhost:8479/v1/apps >/dev/null && echo "  PASS good key -> 200"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "authorization: Bearer $K2" -X POST localhost:8479/v1/jobs -H 'content-type: application/json' -d '{"app":"translate-marian","op":"translate","input":"x","policy":"confidential"}')" = 403 ] && echo "  PASS app-b may not use confidential -> 403"
curl -sf -H "authorization: Bearer $K1" -X POST localhost:8479/v1/jobs -H 'content-type: application/json' -d '{"app":"translate-marian","op":"translate","input":"Keys work.","params":{"source":"en","target":"de"}}' | python3 -c "import json,sys;print('  ->',json.load(sys.stdin)['output'])"
grep -q '"client": "app-a"' $SEALED_HOME/audit.jsonl && echo "  PASS audit carries client label"
echo "== revoke"
$S keys revoke app-a >/dev/null
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "authorization: Bearer $K1" localhost:8479/v1/apps)" = 401 ] && echo "  PASS revoked key -> 401"
kill $GW; sleep 1; rm -rf "$SEALED_HOME"
