#!/usr/bin/env bash
# TLS: self-signed certs, fingerprint pinning for runners, refusal to bind non-localhost without TLS.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed; CTL=.venv/bin/sealed-control
export SEALED_HOME=$(mktemp -d); T=$SEALED_HOME
cp ~/.sealed/allowlist.json $T/
echo "== control plane cert"
$CTL cert --host 127.0.0.1 --host control.local --out $T/ctls | tail -3
FP=$(.venv/bin/python -c "from sealed.certs import fingerprint;print(fingerprint(open('$T/ctls/control.crt','rb').read()))")
echo "  fingerprint $FP"
echo "== control plane refuses a public bind without TLS"
OUT=$(SEALED_CONTROL_HOST=0.0.0.0 SEALED_CONTROL_DB=$T/x.sqlite SEALED_CONTROL_ADMIN_TOKEN=a $CTL 2>&1 || true); grep -q "refusing to bind" <<<"$OUT" && echo "  PASS"
echo "== control plane over https"
SEALED_CONTROL_CERT=$T/ctls/control.crt SEALED_CONTROL_KEY=$T/ctls/control.key SEALED_CONTROL_DB=$T/c.sqlite SEALED_CONTROL_ADMIN_TOKEN=adm_tls SEALED_CONTROL_PORT=8482 $CTL > $T/c.log 2>&1 & CP=$!
trap 'kill $CP ${GW:-} 2>/dev/null; rm -rf "$T"' EXIT
sleep 2
C=https://127.0.0.1:8482
curl -sk $C/v1/fingerprint | grep -q "$FP" && echo "  PASS serves https, fingerprint endpoint matches"
TOK=$(curl -sk -X POST $C/v1/admin/enroll-tokens -H "authorization: Bearer adm_tls" -H 'content-type: application/json' -d '{"label":"tls-runner"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
echo "== enrol without a pin against a self-signed cert must fail (system CA store)"
OUT=$($S enroll $C $TOK 2>&1 || true); grep -qiE "certificate|SSL|refused" <<<"$OUT" && echo "  PASS rejected: $(head -c 80 <<<"$OUT")"
echo "== enrol with the WRONG fingerprint must fail"
OUT=$($S enroll $C $TOK --fingerprint sha256:$(printf '0%.0s' $(seq 64)) 2>&1 || true); grep -q "does not match pinned" <<<"$OUT" && echo "  PASS pin mismatch refused"
echo "== enrol with the right fingerprint, then heartbeat over pinned https"
$S enroll $C $TOK --fingerprint $FP
$S agent --once | python3 -c "import json,sys;d=json.load(sys.stdin);print('  PASS heartbeat ok, audit +%d' % d['sent_audit'])"
grep -q "\"ca_fingerprint\": \"$FP\"" $T/agent.json && echo "  PASS pin stored"
echo "== token page carries the fingerprint in the one-liner"
J=$T/j; curl -sk -c $J -o /dev/null -X POST $C/ui/login -d token=adm_tls
NEW=$(curl -sk -b $J -o /dev/null -w "%{redirect_url}" -X POST $C/ui/tokens/create -d label=x | sed 's/.*new=//')
curl -sk -b $J "$C/ui/tokens?new=$NEW" | grep -q "SEALED_CONTROL_FINGERPRINT=$FP" && echo "  PASS"
echo "== gateway: refuses public bind without TLS, serves https with a cert"
OUT=$(SEALED_ALLOW_NO_KEYS=1 $S serve --host 0.0.0.0 --port 8483 2>&1 || true); grep -q "refusing to bind 0.0.0.0 without TLS" <<<"$OUT" && echo "  PASS"
$S cert --host 127.0.0.1 --out $T/gtls | tail -1
K=$($S keys create --label t | head -1)
$S serve --host 127.0.0.1 --port 8483 --cert $T/gtls/gateway.crt --key $T/gtls/gateway.key > $T/g.log 2>&1 & GW=$!
sleep 2
curl -sk -H "authorization: Bearer $K" https://127.0.0.1:8483/health | grep -q '"ok":true' && echo "  PASS gateway https"
curl -s -m 2 http://127.0.0.1:8483/health >/dev/null 2>&1 && echo "  FAIL plain http accepted" || echo "  PASS plain http refused on the tls port"
