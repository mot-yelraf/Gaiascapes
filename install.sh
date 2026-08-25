#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="${GAIA_SCAPE_PYTHON:-python3}"
DEFAULT_INSTALL_DIR="${HOME}/Gaia_Scape"
STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/gaia-scape"
STATE_FILE="$STATE_DIR/install-location"

fail() { printf 'Gaia Scape installation failed: %s\n' "$1" >&2; exit 1; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3.10 or newer was not found."
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || fail "Python 3.10 or newer is required."

remembered="$DEFAULT_INSTALL_DIR"
if [[ -f "$STATE_FILE" ]]; then IFS= read -r remembered < "$STATE_FILE" || true; fi
case "$remembered" in ""|/|"$HOME") remembered="$DEFAULT_INSTALL_DIR" ;; esac

choose_location() {
  local initial="$1"
  case "$(uname -s)" in
    Darwin)
      osascript - "$initial" <<'APPLESCRIPT'
on run argv
  set chosenFolder to choose folder with prompt "Choose the Gaia Scape folder or a parent folder." default location POSIX file (item 1 of argv)
  return POSIX path of chosenFolder
end run
APPLESCRIPT
      ;;
    Linux)
      if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v zenity >/dev/null 2>&1; then
        zenity --file-selection --directory --title="Choose the Gaia Scape folder or its parent" --filename="${initial}/"
      elif [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v kdialog >/dev/null 2>&1; then
        kdialog --getexistingdirectory "$initial" --title "Choose the Gaia Scape folder or its parent"
      else
        return 2
      fi
      ;;
    *) return 2 ;;
  esac
}

resolve_install_dir() {
  local selected="${1%/}"
  [[ "$(basename -- "$selected")" == "Gaia_Scape" ]] && printf '%s\n' "$selected" || printf '%s/Gaia_Scape\n' "$selected"
}

if [[ -n "${GAIA_SCAPE_INSTALL_DIR:-}" ]]; then
  INSTALL_DIR="$GAIA_SCAPE_INSTALL_DIR"
else
  initial="$remembered"
  [[ -d "$initial" ]] || initial="$(dirname -- "$initial")"
  [[ -d "$initial" ]] || initial="$HOME"
  selection_status=0
  selected="$(choose_location "$initial")" || selection_status=$?
  if [[ $selection_status -eq 1 ]]; then
    fail "Installation was cancelled."
  elif [[ $selection_status -eq 0 && -n "$selected" ]]; then
    INSTALL_DIR="$(resolve_install_dir "$selected")"
  elif [[ -t 0 ]]; then
    read -r -p "Choose the Gaia Scape folder or its parent [$initial] " selected
    INSTALL_DIR="$(resolve_install_dir "${selected:-$initial}")"
  else
    INSTALL_DIR="$remembered"
    printf 'No graphical folder chooser is available; using %s\n' "$INSTALL_DIR"
  fi
fi

case "$INSTALL_DIR" in ""|/|"$HOME") fail "The install location must name a dedicated application directory." ;; /*) ;; *) fail "The install location must be absolute." ;; esac
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/supercollider"
INSTALL_DIR="$(CDPATH= cd -- "$INSTALL_DIR" && pwd -P)"
if [[ -n "${GAIA_SCAPE_AUDIO_DEVICE:-}" ]]; then
  printf '%s\n' "$GAIA_SCAPE_AUDIO_DEVICE" > "$INSTALL_DIR/data/audio-device"
fi
LOG_FILE="$INSTALL_DIR/install.log"
: > "$LOG_FILE"
{
  printf 'Installing Gaia Scape from %s\n' "$SOURCE_DIR"
  printf 'Installation directory: %s\n' "$INSTALL_DIR"
  printf 'Python: %s\n' "$("$PYTHON_BIN" --version 2>&1)"
} | tee -a "$LOG_FILE"

if [[ "$(uname -s)" == Linux ]]; then
  "$PYTHON_BIN" -m venv --system-site-packages "$INSTALL_DIR/.venv" || fail "Could not create the virtual environment. Install python3-venv and retry."
else
  "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv" || fail "Could not create the virtual environment."
fi
if ! "$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade "$SOURCE_DIR" 2>&1 | tee -a "$LOG_FILE"; then
  fail "Python package installation failed. Check $LOG_FILE for details."
fi
"$INSTALL_DIR/.venv/bin/python" -c 'import webview' \
  || fail "pywebview could not be imported after installation."
if [[ "$(uname -s)" == Linux ]]; then
  "$INSTALL_DIR/.venv/bin/python" -c \
    "import gi; gi.require_version('Gtk', '3.0'); gi.require_version('WebKit2', '4.1'); from gi.repository import Gtk, WebKit2" \
    || fail "GTK/WebKit is missing. On Debian, Ubuntu, or Raspberry Pi OS install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 and run this installer again."
fi
"$INSTALL_DIR/.venv/bin/python" -m pip uninstall --yes earth-rhythms >/dev/null 2>&1 || true

if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
  install -m 755 "$SOURCE_DIR/install.sh" "$INSTALL_DIR/install.sh"
  install -m 755 "$SOURCE_DIR/uninstall.sh" "$INSTALL_DIR/uninstall.sh"
  install -m 755 "$SOURCE_DIR/run_gaia_scape.sh" "$INSTALL_DIR/run_gaia_scape.sh"
  install -m 755 "$SOURCE_DIR/run_gaia_scape_gui.sh" "$INSTALL_DIR/run_gaia_scape_gui.sh"
  install -m 755 "$SOURCE_DIR/run_supercollider.sh" "$INSTALL_DIR/run_supercollider.sh"
  install -m 644 "$SOURCE_DIR/supercollider/gaia-scape.scd" "$INSTALL_DIR/supercollider/gaia-scape.scd"
  install -m 644 "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
  install -m 644 "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"
  install -m 644 "$SOURCE_DIR/SYSTEM_REQUIREMENTS.md" "$INSTALL_DIR/SYSTEM_REQUIREMENTS.md"
  rm -f "$INSTALL_DIR/run_earth_rhythms.sh" "$INSTALL_DIR/run_earth_rhythms_gui.sh"
  rm -f "$INSTALL_DIR/supercollider/earth-rhythms.scd"
fi

mkdir -p "$STATE_DIR"
state_temp="$STATE_FILE.tmp.$$"
printf '%s\n' "$INSTALL_DIR" > "$state_temp"
mv "$state_temp" "$STATE_FILE"

enable_autostart="${GAIA_SCAPE_AUTO_START:-}"
if [[ -z "$enable_autostart" && -t 0 ]]; then
  read -r -p "Enable Gaia Scape auto-start for this user? [y/N] " answer
  [[ "$answer" =~ ^[Yy] ]] && enable_autostart=yes || enable_autostart=no
fi

if [[ "$enable_autostart" == yes ]]; then
  if [[ "$(uname -s)" == Linux ]] && command -v systemctl >/dev/null 2>&1; then
    service_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$service_dir"
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/write_systemd_service.py" "$service_dir/gaia-scape.service" "$INSTALL_DIR/run_gaia_scape.sh"
    systemctl --user daemon-reload
    systemctl --user enable --now gaia-scape.service
  elif [[ "$(uname -s)" == Darwin ]]; then
    plist="$HOME/Library/LaunchAgents/local.gaia-scape.plist"
    mkdir -p "$(dirname -- "$plist")"
    "$PYTHON_BIN" "$SOURCE_DIR/scripts/write_launch_agent.py" "$plist" "$INSTALL_DIR/run_gaia_scape.sh" "$INSTALL_DIR/data"
    launchctl unload "$plist" >/dev/null 2>&1 || true
    launchctl load "$plist"
  fi
fi

if command -v sclang >/dev/null 2>&1 || [[ -x /Applications/SuperCollider.app/Contents/MacOS/sclang ]]; then
  printf 'SuperCollider detected.\n'
else
  printf 'SuperCollider was not detected; capture and the web UI will still work.\n'
fi

printf '\nGaia Scape was installed in %s\n' "$INSTALL_DIR"
printf 'Start audio: %s/run_supercollider.sh\n' "$INSTALL_DIR"
printf 'Start the desktop app: %s/run_gaia_scape_gui.sh\n' "$INSTALL_DIR"
printf 'Start headless: %s/run_gaia_scape.sh\n' "$INSTALL_DIR"
printf 'Open locally: http://127.0.0.1:8768\n'
printf 'Open on LAN: http://<gaia-host-ip>:8768\n'
printf 'Application data: %s/data\n' "$INSTALL_DIR"
