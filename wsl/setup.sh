#!/usr/bin/env bash
set -euo pipefail
VENV="${KIRO_VOICE_WSL_VENV:-$HOME/.venvs/kiro-voice}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$HERE/requirements.txt"

echo
if command -v kiro-cli >/dev/null 2>&1; then
  echo "Kiro CLI: $(command -v kiro-cli)"
  kiro-cli --version || true
else
  echo "Kiro CLI not found."
  echo "Install with: curl -fsSL https://cli.kiro.dev/install | bash"
fi
echo
echo "WSL voice venv: $VENV"
echo "Run: $HERE/run.sh"
