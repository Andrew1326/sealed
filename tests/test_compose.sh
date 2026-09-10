#!/usr/bin/env bash
# Privilege separation: gateway has no Docker socket; launcher is internal-only and runs allowlisted images only.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose build -q && docker compose up -d >/dev/null 2>&1; sleep 4
trap 'docker compose down >/dev/null 2>&1' EXIT
echo "== job through gateway -> launcher"
curl -sf -X POST localhost:8470/v1/jobs -H 'content-type: application/json' \
  -d '{"app":"translate-marian","op":"translate","input":"Privilege separation works.","params":{"source":"en","target":"de"}}' \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print('  ->',d['output'])"
echo "== gateway container must have no docker socket and a read-only rootfs"
docker compose exec -T gateway sh -c '[ ! -e /var/run/docker.sock ] && echo "  no socket: PASS"; touch /x 2>/dev/null && echo "  FAIL rootfs writable" || echo "  read-only: PASS"'
echo "== launcher must refuse image IDs outside the allowlist"
docker compose exec -T gateway python3 -c "
import urllib.request,json
req=urllib.request.Request('http://launcher:8473/run',data=json.dumps({'image_id':'sha256:'+'0'*64,'op':'translate','input':'x'}).encode(),headers={'content-type':'application/json'})
try: urllib.request.urlopen(req); print('  FAIL')
except urllib.error.HTTPError as e: print('  refused', e.code, ': PASS')"
echo "== launcher must not be reachable from the host"
curl -s -m 2 localhost:8473/health >/dev/null && echo "  FAIL exposed" || echo "  not exposed: PASS"
echo "== binary app through the split stack"
curl -sf -o /dev/null -w "  docx2pdf HTTP %{http_code} %{size_download} bytes: PASS\n" -F file=@tests/data/contract.docx -F app=docx2pdf -F op=convert localhost:8470/v1/files
