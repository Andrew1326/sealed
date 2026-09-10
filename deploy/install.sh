#!/usr/bin/env bash
# One-line runner install for a fresh Ubuntu/Debian machine or VM (your laptop, office server, or a VM in your cloud account).
#   curl -fsSL https://raw.githubusercontent.com/Andrew1326/sealed/master/deploy/install.sh | bash
# Optional: SEALED_CONTROL=https://control.example.com SEALED_ENROLL_TOKEN=enr_xxx  to enrol with a control plane.
#           SEALED_APPS="translate-marian docx2pdf"  apps to install from the registry (default: those two).
set -euo pipefail
REPO=${SEALED_REPO:-https://github.com/Andrew1326/sealed.git}
DIR=${SEALED_DIR:-$HOME/sealed}
APPS=${SEALED_APPS:-"translate-marian docx2pdf"}

echo "== docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
  echo "docker installed; you may need to log out and back in for group membership. Re-run this script afterwards."
  exit 0
fi
echo "== python venv + git"
sudo apt-get install -y -q python3-venv git >/dev/null 2>&1 || true
[ -d "$DIR" ] || git clone -q "$REPO" "$DIR"
cd "$DIR"; git pull -q
python3 -m venv .venv && .venv/bin/pip install -q -e ./runner
S=.venv/bin/sealed
echo "== verify tools (static strace from alpine)"
$S tools >/dev/null
echo "== trust the community publisher key from the registry"
KEY=$(python3 -c "import json;print(json.load(open('registry/index.json'))['apps'][0]['entry'])")
PUB=$(python3 -c "import json;print(json.load(open('registry/$KEY'))['publisher_key'])")
$S trust "$PUB" "sealed-community"
for a in $APPS; do
  echo "== install $a (builds locally, downloads pinned weights on first run)"
  $S install "$a" --registry "$DIR/registry"
done
if [ -n "${SEALED_CONTROL:-}" ] && [ -n "${SEALED_ENROLL_TOKEN:-}" ]; then
  echo "== enrol with control plane"
  $S enroll "$SEALED_CONTROL" "$SEALED_ENROLL_TOKEN"
fi
echo "== start gateway + launcher (+ agent if enrolled)"
export SEALED_UID=$(id -u) SEALED_GID=$(id -g)
if [ -f "$HOME/.sealed/agent.json" ]; then docker compose --profile managed up -d; else docker compose up -d; fi
echo
echo "sealed is running. Try:"
echo "  echo 'Hello confidential world' | $DIR/$S run translate-marian --op translate -p source=en -p target=de"
echo "  curl -F file=@doc.docx -F app=docx2pdf -F op=convert http://127.0.0.1:8470/v1/files -o doc.pdf"
