#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
S=.venv/bin/sealed
echo "== translate through the confidential policy"
echo "This agreement is confidential. The buyer pays 250,000 euros on delivery." | $S run translate-marian --op translate -p source=en -p target=de
echo "== extract"
echo "On 12 March 2026, Acme GmbH signed with Nordwind AB for EUR 250,000. Contact Maria Lindqvist in Stockholm." | $S run extract-qwen --op extract
echo "== summarize"
cat apps/extract/tests/summarize.json | python3 -c "import json,sys;print(json.load(sys.stdin)[0]['input'])" | $S run extract-qwen --op summarize -p max_words=30
echo "== audit tail"
$S audit-log -n 3
