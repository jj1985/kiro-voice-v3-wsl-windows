#!/usr/bin/env bash
set -euo pipefail
VENV="${AGENT_VOICE_WSL_VENV:-${KIRO_VOICE_WSL_VENV:-$HOME/.venvs/kiro-voice}}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$HERE/requirements.txt"

echo
echo "Detected agent CLIs:"
if command -v kiro-cli >/dev/null 2>&1; then
  echo "  Kiro:   $(command -v kiro-cli)"
  kiro-cli --version || true
else
  echo "  Kiro:   not found"
  echo "          install: curl -fsSL https://cli.kiro.dev/install | bash"
fi

if command -v claude >/dev/null 2>&1; then
  echo "  Claude: $(command -v claude)"
  claude --version || true
else
  echo "  Claude: not found"
  echo "          install: curl -fsSL https://claude.ai/install.sh | bash"
fi

if command -v codex >/dev/null 2>&1; then
  echo "  Codex:  $(command -v codex)"
  codex --version || true
else
  echo "  Codex:  not found"
  echo "          install: curl -fsSL https://chatgpt.com/codex/install.sh | sh"
fi

echo
echo "WSL voice venv: $VENV"
echo "Default backend: ${AGENT_VOICE_BACKEND:-kiro}"
echo "Run: $HERE/run.sh"
echo "Examples:"
echo "  AGENT_VOICE_BACKEND=claude $HERE/run.sh"
echo "  AGENT_VOICE_BACKEND=codex  $HERE/run.sh"
