#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VOICE=0
BOOTSTRAP=1
for arg in "$@"; do
  case "$arg" in
    --voice) VOICE=1 ;;
    --no-bootstrap) BOOTSTRAP=0 ;;
    *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done
UV="$(command -v uv || true)"
if [[ -z "$UV" ]]; then
  UV="$HOME/.local/bin/uv"
  if [[ ! -x "$UV" ]]; then
    [[ "$BOOTSTRAP" == 1 ]] || { echo 'Install uv first.' >&2; exit 1; }
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    curl -fsSL https://astral.sh/uv/0.10.0/install.sh -o "$tmp"
    UV_NO_MODIFY_PATH=1 sh "$tmp"
  fi
fi
# Never share the Windows environment's executables/site-packages with Linux.
export UV_PROJECT_ENVIRONMENT="$ROOT/.venv-wsl"
export UV_LINK_MODE=copy
"$UV" python install 3.12
sync=(sync --project "$ROOT" --python 3.12 --no-dev)
[[ ! -f "$ROOT/uv.lock" ]] || sync+=(--locked)
[[ "$VOICE" == 0 ]] || sync+=(--extra voice)
"$UV" "${sync[@]}"
"$ROOT/.venv-wsl/bin/python" -m quack_actual config init
printf '\nQuack Actual installed. Authenticate your agent in this operating system.\n'
printf 'Start: bash "%s/launch.sh" start --backend copilot --project ~/src/your-project\n' "$ROOT"
printf 'WSL voice uses the Windows .venv created by install.ps1 in this shared checkout.\n'
