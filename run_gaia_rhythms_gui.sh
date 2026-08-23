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

supercollider_pid=""
if ! pgrep -f "$RUNTIME_DIR/supercollider/gaia-rhythms.scd" >/dev/null 2>&1; then
  "$RUNTIME_DIR/run_supercollider.sh" &
  supercollider_pid=$!
  sleep 2
  if ! kill -0 "$supercollider_pid" >/dev/null 2>&1; then
    wait "$supercollider_pid" || true
    printf 'SuperCollider did not remain running; Gaia Rhythms will start without audio.\n' >&2
    supercollider_pid=""
  fi
fi

cleanup() {
  if [[ -n "$supercollider_pid" ]]; then
    kill -TERM "$supercollider_pid" >/dev/null 2>&1 || true
    wait "$supercollider_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$PYTHON_BIN" -m gaia_rhythms_host.desktop "$@"
