#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Gaiascapes virtual environment is missing. Run %s/install.sh again.\n' "$RUNTIME_DIR" >&2
  exit 1
fi

export GAIA_SCAPE_DATA_DIR="$RUNTIME_DIR/data"
export GAIA_SCAPE_HTTP_HOST="${GAIA_SCAPE_HTTP_HOST:-0.0.0.0}"
cd "$RUNTIME_DIR"
exec "$PYTHON_BIN" -m gaiascapes_host "$@"

