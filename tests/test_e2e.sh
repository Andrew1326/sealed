#!/usr/bin/env bash
# End-to-end: text jobs, document jobs (docx/txt/pdf), warm pool through the gateway.
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
D=tests/data
OUT=$(mktemp -d)
echo "== translate (text, warm pool inside one CLI call)"
echo "This agreement is confidential. The buyer pays 250,000 euros on delivery." | $S run translate-marian --op translate -p source=en -p target=de
echo "== translate documents: docx -> docx, txt -> txt, pdf -> pdf (pdf2docx + docx2pdf)"
$S run translate-marian --op translate -p source=en -p target=de --file $D/contract.docx --out $OUT/contract.de.docx
$S run translate-marian --op translate -p source=en -p target=fr --file $D/memo.txt --out $OUT/memo.fr.txt
$S run translate-marian --op translate -p source=en -p target=ru --file $D/contract.pdf --out $OUT/contract.ru.pdf
.venv/bin/python - "$OUT" <<'PY'
import sys, docx
from pathlib import Path
out = Path(sys.argv[1])
d = docx.Document(out / "contract.de.docx")
assert any(r.bold for p in d.paragraphs for r in p.runs), "bold run lost"
assert d.tables[0].rows[4].cells[1].text == "300", "table cell lost"
assert "Vereinbarung" in d.paragraphs[1].text or "Abkommen" in d.paragraphs[0].text, d.paragraphs[1].text
assert "CONFIDENTIEL" in (out / "memo.fr.txt").read_text().upper()
from pypdf import PdfReader
r = PdfReader(out / "contract.ru.pdf")
assert len(r.pages) >= 2 and "Соглашение" in r.pages[0].extract_text(), "pdf -> pdf translation lost content"
print("documents ok: formatting, table and content preserved; pdf came back as a 2-page pdf")
PY
echo "== non-AI app: docx -> pdf with LibreOffice in the same sandbox"
$S run docx2pdf --op convert --file $D/contract.docx --out $OUT/contract.pdf
head -c 5 $OUT/contract.pdf | grep -q "%PDF-" && echo "  pdf ok ($(stat -c%s $OUT/contract.pdf) bytes)"
echo "== extract + summarize on documents"
$S run extract-qwen --op extract --file $D/contract.docx | head -c 300; echo
$S run extract-qwen --op summarize -p max_words=40 --file $D/memo.txt
if $S apps | grep -q qwen3-4b; then
  echo "== quality tier (qwen3-4b, GPU if present)"
  $S run qwen3-4b --op classify -p 'labels=["contract","invoice","memo"]' --file $D/memo.txt
fi
echo "== gateway: warm pool latency and file upload"
nohup $S serve --port 8471 > $OUT/gateway.log 2>&1 & GW=$!
sleep 3
for i in 1 2 3; do
  curl -sf -X POST localhost:8471/v1/jobs -H 'content-type: application/json' \
    -d '{"app":"translate-marian","op":"translate","input":"Request number '$i'.","params":{"source":"en","target":"de"}}' \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'  job {$i}: {d[\"seconds\"]}s -> {d[\"output\"]}')"
done
curl -sf -o $OUT/contract.fr.docx -F file=@$D/contract.docx -F app=translate-marian -F op=translate -F 'params={"source":"en","target":"fr"}' localhost:8471/v1/files
[ -s $OUT/contract.fr.docx ] && echo "  file upload ok ($(stat -c%s $OUT/contract.fr.docx) bytes)"
curl -sf -o $OUT/gw.pdf -F file=@$D/contract.docx -F app=docx2pdf -F op=convert localhost:8471/v1/files
head -c 5 $OUT/gw.pdf | grep -q "%PDF-" && echo "  gateway convert ok ($(stat -c%s $OUT/gw.pdf) bytes)"
curl -sf localhost:8471/v1/pool | python3 -c "import json,sys;[print('  warm:',w['image'],w['jobs'],'jobs') for w in json.load(sys.stdin)]"
kill $GW; sleep 2
[ -z "$(docker ps -q --filter name=sealed-warm)" ] && echo "  warm containers cleaned up on shutdown"
echo "== audit tail"
$S audit-log -n 2
rm -rf "$OUT"
