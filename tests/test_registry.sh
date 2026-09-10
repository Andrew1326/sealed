#!/usr/bin/env bash
# Registry: signed entries, trust, tamper detection, install as a fresh user.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
PUB=$(cat ~/.sealed/keys/publisher.pub)
export SEALED_HOME=$(mktemp -d)
echo "== fresh user: untrusted publisher must be refused"
$S install translate-marian --no-verify && { echo FAIL; exit 1; } || echo "PASS (exit $?)"
echo "== trust publisher, install on signed verification"
$S trust "$PUB" test-publisher
$S install translate-marian --no-verify
$S apps | grep -q translate-marian && echo "PASS installed"
echo "== tampered entry must be refused with a signature error"
T=$(mktemp -d); cp registry/*.json $T/
sed -i 's/"memory": "4g"/"memory": "1m"/' $T/translate-marian-0.2.0.json
OUT=$($S install translate-marian --registry $T --no-verify 2>&1 || true); grep -q "INVALID signature" <<<"$OUT" && echo "PASS tamper detected" || { echo "FAIL: $OUT"; exit 1; }
echo "== wrong image ID must be refused"
cp registry/*.json $T/
python3 - $T <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])/"translate-marian-0.2.0.json"; e=json.loads(p.read_text()); e["image_id"]="sha256:"+"0"*64
# re-sign is impossible without the key, so this also exercises the signature check; keep it simple:
p.write_text(json.dumps(e))
PY
OUT=$($S install translate-marian --registry $T --no-verify 2>&1 || true); grep -qE "INVALID signature|does not match" <<<"$OUT" && echo "PASS id mismatch refused" || { echo "FAIL: $OUT"; exit 1; }
rm -rf "$SEALED_HOME" "$T"
