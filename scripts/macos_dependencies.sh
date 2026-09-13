#!/usr/bin/env bash
# macOS prerequisite checks, sourced by install.sh before runtime files change.
# Dependency installation requires an explicit interactive answer; Homebrew itself
# is never installed automatically. PYTHON_BIN is updated to the chosen interpreter.

supported_python() {
  command -v "$PYTHON_BIN" >/dev/null 2>&1 &&
    "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_homebrew() {
  BREW_BIN="$(command -v brew 2>/dev/null || true)"
  if [[ -z "$BREW_BIN" ]]; then
    for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [[ -x "$candidate" ]]; then BREW_BIN="$candidate"; break; fi
    done
  fi
  [[ -n "$BREW_BIN" ]]
}

confirm_dependency() {
  local answer=""
  if [[ ! -t 0 ]]; then
    printf '%s\n' 'No interactive terminal; no dependency will be installed automatically. Run the installer in Terminal to accept the offer.' >&2
    return 1
  fi
  read -r -p "$1 [y/N] " answer || return 1
  case "$answer" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

python_install_help() {
  cat >&2 <<'HELP'
Gaiascapes requires Python 3.10 or newer, including venv and pip.
Install Homebrew using https://brew.sh and follow its shell setup instructions,
then run: brew install python@3.13
Rerun Gaiascapes with the installed interpreter:
  GAIA_SCAPE_PYTHON="$(brew --prefix python@3.13)/bin/python3.13" ./scripts/install_macos.sh
Alternatively, install a supported macOS Python from https://www.python.org/downloads/macos/
and set GAIA_SCAPE_PYTHON to its full executable path.
Without supported Python this installation cannot continue: capture, history,
the web UI, and audio all need the Python host. Existing installation data is unchanged.
HELP
}

ensure_macos_python() {
  MACOS_PYTHON_INSTALLED=no
  if supported_python; then return 0; fi
  printf 'Python is missing, cannot run, or is too old (%s). Minimum required: Python 3.10.\n' "$PYTHON_BIN" >&2
  if ! find_homebrew; then
    printf 'Homebrew was not found; automatic Python installation is unavailable.\n' >&2
    python_install_help
    return 1
  fi
  if ! confirm_dependency 'Install supported Python 3.13 through Homebrew (brew install python@3.13)?'; then
    printf 'Python installation was not accepted.\n' >&2
    python_install_help
    return 1
  fi
  if ! "$BREW_BIN" install python@3.13; then
    printf 'Homebrew Python installation failed. Check the Homebrew error above, resolve it, then retry.\n' >&2
    python_install_help
    return 1
  fi
  local python_prefix
  if ! python_prefix="$("$BREW_BIN" --prefix python@3.13)" || [[ -z "$python_prefix" ]]; then
    printf 'Could not locate the Homebrew Python installation.\n' >&2
    python_install_help
    return 1
  fi
  PYTHON_BIN="$python_prefix/bin/python3.13"
  if ! supported_python; then
    printf 'Homebrew completed, but its Python interpreter could not pass the version check.\n' >&2
    python_install_help
    return 1
  fi
  MACOS_PYTHON_INSTALLED=yes
  printf 'Using Homebrew Python for the remaining installation: %s\n' "$PYTHON_BIN"
}

prepare_macos_venv() {
  if [[ "${MACOS_PYTHON_INSTALLED:-no}" == yes && -d "$INSTALL_DIR/.venv" ]]; then
    local backup
    backup="$(mktemp -d "$INSTALL_DIR/.venv-previous.XXXXXX")" || return 1
    mv "$INSTALL_DIR/.venv" "$backup/venv" || return 1
    printf 'Previous virtual environment preserved at %s/venv; creating a fresh environment with the selected Homebrew Python.\n' "$backup"
  fi
}

supercollider_installed() {
  command -v sclang >/dev/null 2>&1 ||
    [[ -x /Applications/SuperCollider.app/Contents/MacOS/sclang ]] ||
    [[ -x "$HOME/Applications/SuperCollider.app/Contents/MacOS/sclang" ]]
}

supercollider_install_help() {
  cat >&2 <<'HELP'
Continuing without SuperCollider: event capture, history, the web UI, and browser
playback of animal recordings remain available. Synthesized event/background
audio and the macOS Say quark announcements need SuperCollider; eSpeak NG
announcements remain available if eSpeak NG is installed separately.
To add SuperCollider later, install Homebrew from https://brew.sh, then run:
  brew install --cask supercollider
Or download a version compatible with your macOS from https://supercollider.github.io/downloads
and place SuperCollider.app in /Applications or ~/Applications. Restart Gaiascapes afterward.
HELP
}

ensure_macos_supercollider() {
  if supercollider_installed; then
    printf 'SuperCollider detected.\n'
    return 0
  fi
  printf 'SuperCollider is missing. It is required for synthesized audio rendering.\n' >&2
  if ! find_homebrew; then
    printf 'Homebrew was not found; automatic SuperCollider installation is unavailable.\n' >&2
  elif confirm_dependency 'Install SuperCollider through Homebrew (brew install --cask supercollider)?'; then
    if "$BREW_BIN" install --cask supercollider; then
      if supercollider_installed; then
        printf 'SuperCollider installed and detected.\n'
        return 0
      fi
      printf 'Homebrew completed, but SuperCollider sclang was not found in PATH or the standard Applications folders.\n' >&2
    else
      printf 'Homebrew SuperCollider installation failed. Check the error above and macOS compatibility before retrying.\n' >&2
    fi
  else
    printf 'SuperCollider installation was not accepted.\n' >&2
  fi
  supercollider_install_help
}
