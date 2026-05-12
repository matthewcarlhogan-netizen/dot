#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_BASE="${CONDA_BASE:-$HOME/miniforge3}"
ENV_NAME="${DOT_ENV:-dot}"
PYTHON_BIN=""
ENV_PYTHON="$CONDA_BASE/envs/$ENV_NAME/bin/python"

cd "$ROOT_DIR"

if [[ -d "$ROOT_DIR/dot/.git" ]]; then
  echo "[dot] WARNING: nested repository detected at $ROOT_DIR/dot" >&2
  echo "[dot] Run from only one checkout to avoid stale code paths." >&2
fi

if [[ -x "$ENV_PYTHON" ]]; then
  PYTHON_BIN="$ENV_PYTHON"
elif [[ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  export CONDA_SOLVER="${CONDA_SOLVER:-classic}"
  if ! conda activate "$ENV_NAME"; then
    echo "[dot] Could not activate conda env '$ENV_NAME'." >&2
    exit 1
  fi
  PYTHON_BIN="$(command -v python || true)"
else
  echo "[dot] Could not find '$ENV_PYTHON' or conda activation script." >&2
  echo "[dot] Set CONDA_BASE/DOT_ENV correctly." >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[dot] Python binary is not executable: $PYTHON_BIN" >&2
  exit 1
fi

if [[ "${DOT_SKIP_PREFLIGHT:-0}" != "1" ]]; then
  if ! "$PYTHON_BIN" - <<'PY'
import importlib
import sys

required = ("cv2", "numpy", "psutil", "torch", "yaml")
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("[dot] Missing Python packages:", ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
print("[dot] Preflight OK")
PY
  then
    echo "[dot] Preflight failed. Fix environment before running live mode." >&2
    exit 1
  fi
fi

exec "$PYTHON_BIN" live.py "$@"
