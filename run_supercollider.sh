#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SC_SCRIPT="$RUNTIME_DIR/supercollider/gaia-rhythms.scd"
AUDIO_DEVICE_FILE="$RUNTIME_DIR/data/audio-device"

if [[ "${1:-}" == "--audio-device" ]]; then
  [[ -n "${2:-}" ]] || { printf '%s\n' 'Usage: run_supercollider.sh --audio-device "Device Name"' >&2; exit 2; }
  export GAIA_RHYTHMS_AUDIO_DEVICE="$2"
  shift 2
elif [[ -z "${GAIA_RHYTHMS_AUDIO_DEVICE:-}" && -f "$AUDIO_DEVICE_FILE" ]]; then
  IFS= read -r GAIA_RHYTHMS_AUDIO_DEVICE < "$AUDIO_DEVICE_FILE" || true
  export GAIA_RHYTHMS_AUDIO_DEVICE
fi

if command -v sclang >/dev/null 2>&1; then
  SCLANG="$(command -v sclang)"
elif [[ -x /Applications/SuperCollider.app/Contents/MacOS/sclang ]]; then
  SCLANG=/Applications/SuperCollider.app/Contents/MacOS/sclang
elif [[ -x "$HOME/Applications/SuperCollider.app/Contents/MacOS/sclang" ]]; then
  SCLANG="$HOME/Applications/SuperCollider.app/Contents/MacOS/sclang"
else
  printf 'SuperCollider sclang was not found. Install SuperCollider, then run this launcher again.\n' >&2
  exit 1
fi

if [[ -n "${GAIA_RHYTHMS_AUDIO_DEVICE:-}" ]]; then
  printf 'Requesting SuperCollider output device: %s\n' "$GAIA_RHYTHMS_AUDIO_DEVICE"
fi

SCLANG_PORT="${GAIA_RHYTHMS_SCLANG_PORT:-57131}"
exec "$SCLANG" -u "$SCLANG_PORT" "$SC_SCRIPT" "$@"
