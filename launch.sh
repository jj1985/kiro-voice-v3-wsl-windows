#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv-wsl/bin/python"
[[ -x "$PYTHON" ]] || { echo 'Run bash install.sh first.' >&2; exit 1; }
if [[ "$#" == 0 ]]; then set -- start; fi
exec "$PYTHON" -m quack_actual "$@"
