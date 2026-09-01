#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SC_SCRIPT="$RUNTIME_DIR/supercollider/gaia-scape.scd"
AUDIO_DEVICE_FILE="$RUNTIME_DIR/data/audio-device"
AUDIO_DEVICE_MAP_FILE="$RUNTIME_DIR/data/audio-device-map"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

if [[ "${1:-}" == "--audio-device" ]]; then
  [[ -n "${2:-}" ]] || { printf '%s\n' 'Usage: run_supercollider.sh --audio-device "Device Name"' >&2; exit 2; }
  export GAIA_SCAPE_AUDIO_DEVICE="$2"
  shift 2
elif [[ -z "${GAIA_SCAPE_AUDIO_DEVICE:-}" && -f "$AUDIO_DEVICE_FILE" ]]; then
  IFS= read -r GAIA_SCAPE_AUDIO_DEVICE < "$AUDIO_DEVICE_FILE" || true
  export GAIA_SCAPE_AUDIO_DEVICE
fi

if [[ -z "${GAIA_SCAPE_AUDIO_DEVICE:-}" || "$GAIA_SCAPE_AUDIO_DEVICE" == system ]]; then
  unset GAIA_SCAPE_AUDIO_DEVICE
  if [[ "$(uname -s)" == Darwin && -x "$PYTHON_BIN" ]]; then
    selected_device="$($PYTHON_BIN "$RUNTIME_DIR/scripts/resolve_macos_audio.py" 2>/dev/null || true)"
    if [[ -n "$selected_device" ]]; then
      resolved_device="$selected_device"
      if [[ -f "$AUDIO_DEVICE_MAP_FILE" ]]; then
        while IFS=$'\t' read -r system_device safe_device; do
          if [[ "$system_device" == "$selected_device" && -n "$safe_device" ]]; then
            resolved_device="$safe_device"
            break
          fi
        done < "$AUDIO_DEVICE_MAP_FILE"
      fi
      GAIA_SCAPE_AUDIO_DEVICE="$resolved_device"
      export GAIA_SCAPE_AUDIO_DEVICE
      printf 'Following system audio output: %s\n' "$selected_device"
    fi
  fi
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

if [[ -n "${GAIA_SCAPE_AUDIO_DEVICE:-}" ]]; then
  printf 'Requesting SuperCollider output device: %s\n' "$GAIA_SCAPE_AUDIO_DEVICE"
fi
SCLANG_PORT="${GAIA_SCAPE_SCLANG_PORT:-57131}"
exec "$SCLANG" -u "$SCLANG_PORT" "$SC_SCRIPT" "$@"
