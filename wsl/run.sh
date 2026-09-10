#!/usr/bin/env bash
set -euo pipefail
VENV="${KIRO_VOICE_WSL_VENV:-$HOME/.venvs/kiro-voice}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="${KIRO_VOICE_PROJECT:-$HOME}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Kiro Voice WSL venv missing. Run: bash '$HERE/setup.sh'" >&2
  exit 1
fi

exec "$VENV/bin/python" "$HERE/kiro_voice.py" --project "$PROJECT"
