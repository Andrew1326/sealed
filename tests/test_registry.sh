#!/usr/bin/env bash
# Registry: signed source packages, trust, tamper detection, install = build locally + verify, as a fresh user.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
PUB=$(cat ~/.sealed/keys/publisher.pub)
export SEALED_HOME=$(mktemp -d)
echo "== fresh user: untrusted publisher must be refused"
OUT=$($S install translate-marian 2>&1 || true); grep -q "not signed by a trusted key" <<<"$OUT" && echo "PASS untrusted refused"
echo "== trust publisher"
$S trust "$PUB" test-publisher
echo "== tampered entry must be refused with a signature error"
T=$(mktemp -d); cp registry/* $T/
sed -i 's/"memory": "4g"/"memory": "1m"/' $T/translate-marian-*.json
OUT=$($S install translate-marian --registry $T 2>&1 || true); grep -q "INVALID signature" <<<"$OUT" && echo "PASS tamper detected" || { echo "FAIL: $OUT"; exit 1; }
echo "== tampered source package must be refused by hash"
cp registry/* $T/; printf 'x' >> $T/translate-marian-*.src.tar.gz
OUT=$($S install translate-marian --registry $T 2>&1 || true); grep -q "does not match signed" <<<"$OUT" && echo "PASS source hash mismatch refused" || { echo "FAIL: $OUT"; exit 1; }
echo "== install: fetch source, build locally (docker cache makes this fast here), verify, allow"
$S install translate-marian --tag sealed/translate-marian:test-install 2>&1 | grep -E "signature ok|source package|VERIFIED|REJECTED"
$S apps | grep -q translate-marian && echo "PASS installed from source"
docker rmi -f sealed/translate-marian:test-install >/dev/null
rm -rf "$SEALED_HOME" "$T"
echo "== variants: the cuda entry is the same signed source with a build arg; install picks it by --variant"
export SEALED_HOME=$(mktemp -d); $S trust "$PUB" test-publisher >/dev/null
$S catalog | grep -q "translate-marian \[cuda\]" && echo "  PASS catalog lists the variant"
OUT=$($S install translate-marian --variant nope 2>&1 || true); grep -q "variants available" <<<"$OUT" && echo "  PASS unknown variant refused with the list"
if [ -e /dev/nvidiactl ]; then
  $S install translate-marian --variant cuda --gpu --tag sealed/translate-marian:test-cuda 2>&1 | grep -E "signature ok|VERIFIED|REJECTED"
  .venv/bin/python -c "
from sealed import registry; e=[v for v in registry.load().values() if v['image']=='sealed/translate-marian:test-cuda'][0]; assert e['gpu_verified'], e; print('  PASS gpu capability recorded on the allowlist entry')"
  docker rmi -f sealed/translate-marian:test-cuda >/dev/null
else
  echo "  (no GPU on this host, variant build skipped)"
fi
rm -rf "$SEALED_HOME"
