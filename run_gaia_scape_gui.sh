#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Gaia Scape virtual environment is missing. Run %s/install.sh again.\n' "$RUNTIME_DIR" >&2
  exit 1
fi

export GAIA_SCAPE_DATA_DIR="$RUNTIME_DIR/data"
export GAIA_SCAPE_HTTP_HOST="${GAIA_SCAPE_HTTP_HOST:-0.0.0.0}"
cd "$RUNTIME_DIR"

supercollider_pid=""
desktop_pid=""
if ! pgrep -f "$RUNTIME_DIR/supercollider/gaia-scape.scd" >/dev/null 2>&1; then
  "$RUNTIME_DIR/run_supercollider.sh" &
  supercollider_pid=$!
  sleep 2
  if ! kill -0 "$supercollider_pid" >/dev/null 2>&1; then
    wait "$supercollider_pid" || true
    printf 'SuperCollider did not remain running; Gaia Scape will start without audio.\n' >&2
    supercollider_pid=""
  fi
fi

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$desktop_pid" ]]; then
    kill -TERM "$desktop_pid" >/dev/null 2>&1 || true
    wait "$desktop_pid" 2>/dev/null || true
    desktop_pid=""
  fi
  if [[ -n "$supercollider_pid" ]]; then
    supercollider_children="$(pgrep -P "$supercollider_pid" 2>/dev/null || true)"
    kill -TERM "$supercollider_pid" >/dev/null 2>&1 || true
    wait "$supercollider_pid" 2>/dev/null || true
    for child_pid in $supercollider_children; do
      kill -TERM "$child_pid" >/dev/null 2>&1 || true
    done
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$PYTHON_BIN" -m gaia_scape_host.desktop "$@" &
desktop_pid=$!
wait "$desktop_pid"
desktop_status=$?
desktop_pid=""
exit "$desktop_status"
