#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_BASE="${CONDA_BASE:-$HOME/miniforge3}"
ENV_NAME="${DOT_ENV:-dot}"

cd "$ROOT_DIR"

if [[ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
  source "$CONDA_BASE/etc/profile.d/conda.sh"
  conda activate "$ENV_NAME"
fi

exec python live.py "$@"
