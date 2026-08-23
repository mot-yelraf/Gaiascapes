#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/gaia-rhythms"
STATE_FILE="$STATE_DIR/install-location"
INSTALL_DIR="${GAIA_RHYTHMS_INSTALL_DIR:-}"
if [[ -z "$INSTALL_DIR" && -f "$STATE_FILE" ]]; then
  IFS= read -r INSTALL_DIR < "$STATE_FILE" || true
fi
[[ -n "$INSTALL_DIR" ]] || { printf 'No Gaia Rhythms installation location is recorded.\n' >&2; exit 1; }
case "$INSTALL_DIR" in ""|/|"$HOME") printf 'Refusing unsafe uninstall target: %s\n' "$INSTALL_DIR" >&2; exit 1 ;; /*) ;; *) printf 'The uninstall target must be absolute.\n' >&2; exit 1 ;; esac
[[ -d "$INSTALL_DIR" ]] || { printf 'Gaia Rhythms is not installed at %s\n' "$INSTALL_DIR" >&2; exit 1; }

if [[ "$(uname -s)" == Linux ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now gaia-rhythms.service >/dev/null 2>&1 || true
  systemctl --user disable --now earth-rhythms.service >/dev/null 2>&1 || true
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/gaia-rhythms.service"
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/earth-rhythms.service"
  systemctl --user daemon-reload >/dev/null 2>&1 || true
elif [[ "$(uname -s)" == Darwin ]]; then
  plist="$HOME/Library/LaunchAgents/local.gaia-rhythms.plist"
  launchctl unload "$plist" >/dev/null 2>&1 || true
  rm -f "$plist"
  legacy_plist="$HOME/Library/LaunchAgents/local.earth-rhythms.plist"
  launchctl unload "$legacy_plist" >/dev/null 2>&1 || true
  rm -f "$legacy_plist"
fi

rm -rf "$INSTALL_DIR/.venv" "$INSTALL_DIR/supercollider"
rm -f "$INSTALL_DIR/run_gaia_rhythms.sh" "$INSTALL_DIR/run_gaia_rhythms_gui.sh" \
  "$INSTALL_DIR/run_supercollider.sh" "$INSTALL_DIR/README.md" "$INSTALL_DIR/install.sh"

if [[ "${GAIA_RHYTHMS_REMOVE_DATA:-no}" == yes ]]; then
  rm -rf "$INSTALL_DIR/data"
  rm -f "$STATE_FILE"
  rm -f "$INSTALL_DIR/uninstall.sh"
  rmdir "$INSTALL_DIR" >/dev/null 2>&1 || true
  printf 'Gaia Rhythms and its application data were removed from %s.\n' "$INSTALL_DIR"
else
  printf 'Gaia Rhythms was uninstalled. Application data remains in %s/data.\n' "$INSTALL_DIR"
  printf 'To remove it too, run GAIA_RHYTHMS_REMOVE_DATA=yes %s/uninstall.sh\n' "$INSTALL_DIR"
fi
