#!/usr/bin/env bash
# Remote providers + pseudonymization: what a remote sees, what the caller gets back, what confidential refuses.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
export SEALED_HOME=$(mktemp -d); T=$SEALED_HOME
cp ~/.sealed/allowlist.json $T/
# fake OpenAI-compatible provider: records the last request, replies with the user text prefixed (translate) or JSON (extract)
.venv/bin/python - $T <<'PY' &
import http.server, json, sys
T = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        open(f"{T}/seen.json", "w").write(json.dumps(body))
        user = body["messages"][1]["content"]; system = body["messages"][0]["content"]
        if "JSON object with keys" in system:
            content = json.dumps({"organizations": ["[[TERM_1]]"], "people": ["[[NAME_1]]"], "dates": ["[[DATE_1]]"], "amounts": ["[[MONEY_1]]"], "locations": []})
        else:
            content = "ÜBERSETZT: " + user.replace("[[ EMAIL_1 ]]", "[[EMAIL_1]]")
        out = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", 8498), H).serve_forever()
PY
FAKE=$!
trap 'kill $FAKE 2>/dev/null; rm -rf "$T"' EXIT
sleep 1
cat > $T/remotes.yaml <<'Y'
fake-cloud:
  base_url: http://127.0.0.1:8498/v1
  model: test-model
  api_key_env: FAKE_KEY
Y
cat > $T/standard.yaml <<'Y'
name: standard
tier: standard
require_verified: false
allowed_ops: ["*"]
allow_remote: true
pseudonymize: true
pseudonymize_terms: [Acme GmbH, Nordwind AB]
output:
  max_chars: 200000
Y
DOC='On 12 March 2026 Acme GmbH agreed with Nordwind AB to pay EUR 250,000. Contact Maria Lindqvist at maria.lindqvist@nordwind.se or +46 8 123 4567, IBAN SE35 5000 0000 0549 1000 0003.'
echo "== confidential policy refuses a remote provider"
OUT=$(echo "$DOC" | $S run fake-cloud --op translate -p source=en -p target=de 2>&1 || true)
grep -q "does not allow data to leave" <<<"$OUT" && echo "  PASS"
echo "== standard policy: translate via remote with masking"
OUT=$(echo "$DOC" | $S run fake-cloud --op translate --policy $T/standard.yaml -p source=en -p target=de 2>$T/err)
cat $T/err | sed 's/^/  /'
SEEN=$(.venv/bin/python -c "import json;print(json.load(open('$T/seen.json'))['messages'][1]['content'])")
echo "  remote saw: $SEEN"
for leak in "Acme GmbH" "Nordwind" "Lindqvist" "maria.lindqvist" "123 4567" "SE35" "250,000" "12 March"; do
  grep -q "$leak" <<<"$SEEN" && { echo "  FAIL leaked: $leak"; exit 1; }
done
echo "  PASS nothing identifying reached the remote"
grep -q "ÜBERSETZT" <<<"$OUT" && grep -q "maria.lindqvist@nordwind.se" <<<"$OUT" && grep -q "Maria Lindqvist" <<<"$OUT" && grep -q "Acme GmbH" <<<"$OUT" && echo "  PASS placeholders restored in the result"
echo "== extract via remote: JSON values restored"
OUT=$(echo "$DOC" | $S run fake-cloud --op extract --policy $T/standard.yaml 2>/dev/null)
grep -q '"Acme GmbH"' <<<"$OUT" && grep -q '"Maria Lindqvist"' <<<"$OUT" && grep -q '"EUR 250,000"' <<<"$OUT" && echo "  PASS" || { echo "  FAIL: $OUT"; exit 1; }
echo "== audit line marks the job as remote with mask counts"
tail -n1 $T/audit.jsonl | .venv/bin/python -c "import json,sys;a=json.load(sys.stdin);assert a['remote'] and a['masked'].get('TERM')==2 and a['masked'].get('EMAIL')==1, a;print('  PASS', a['masked'])"
echo "== gateway: same behaviour over HTTP"
cp policies/confidential.yaml $T/; SEALED_POLICY_DIR=$T $S serve --port 8497 > $T/g.log 2>&1 & GW=$!; sleep 2
R=$(curl -sf -X POST localhost:8497/v1/jobs -H 'content-type: application/json' -d "$(python3 -c "import json;print(json.dumps({'app':'fake-cloud','op':'translate','input':'''$DOC''','params':{'source':'en','target':'de'},'policy':'standard'}))")")
grep -q "Maria Lindqvist" <<<"$R" && echo "  PASS gateway restores"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8497/v1/jobs -H 'content-type: application/json' -d '{"app":"fake-cloud","op":"translate","input":"x","policy":"confidential"}')" = 403 ] && echo "  PASS gateway refuses remote under confidential" || echo "  FAIL"
kill $GW
