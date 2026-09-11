#!/usr/bin/env bash
set -euo pipefail
VENV="${AGENT_VOICE_WSL_VENV:-${KIRO_VOICE_WSL_VENV:-$HOME/.venvs/kiro-voice}}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${AGENT_VOICE_PROJECT:-${KIRO_VOICE_PROJECT:-$HOME}}"
BACKEND="${AGENT_VOICE_BACKEND:-${KIRO_VOICE_BACKEND:-kiro}}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Agent Voice WSL venv missing. Run: bash '$HERE/setup.sh'" >&2
  exit 1
fi

exec "$VENV/bin/python" "$HERE/kiro_voice.py" --project "$PROJECT" --backend "$BACKEND"
