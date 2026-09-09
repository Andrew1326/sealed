#!/usr/bin/env bash
# The property the whole project rests on: an image that tries to exfiltrate cannot.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
echo "== evil image under the sandbox contract"
CMD=$($S contract sealed/evil-translate:0.1.0)
OUT=$(echo '{"op":"translate","input":"TOP SECRET: merger price 4.2M","params":{"source":"en","target":"de"}}' | $CMD 2>/tmp/evil.stderr)
echo "stderr (attempt log):"; tail -n1 /tmp/evil.stderr | python3 -m json.tool
echo "stdout:"; echo "$OUT"
if grep -q "SUCCEEDED" /tmp/evil.stderr; then echo "FAIL: an exfiltration attempt succeeded"; exit 1; fi
echo "PASS: all attempts blocked"
echo
echo "== evil image must be REJECTED by verify on intent (it tried to reach the network)"
if $S verify sealed/evil-translate:0.1.0 --skip-scan; then echo "FAIL: evil image was verified"; exit 1; fi
echo "PASS: evil image rejected"
