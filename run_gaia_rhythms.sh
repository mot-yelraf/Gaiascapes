#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Gaia Rhythms virtual environment is missing. Run %s/install.sh again.\n' "$RUNTIME_DIR" >&2
  exit 1
fi

export GAIA_RHYTHMS_DATA_DIR="$RUNTIME_DIR/data"
export GAIA_RHYTHMS_HTTP_HOST="${GAIA_RHYTHMS_HTTP_HOST:-0.0.0.0}"
cd "$RUNTIME_DIR"
exec "$PYTHON_BIN" -m gaia_rhythms_host "$@"

