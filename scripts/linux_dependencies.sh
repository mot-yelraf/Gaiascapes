#!/usr/bin/env bash
# Linux host and renderer prerequisites, sourced by install.sh before runtime files change.
# Debian-family systems (including Raspberry Pi OS) use their native packages.

install_linux_packages() {
  local package_command=(apt-get)
  command -v apt-get >/dev/null 2>&1 || {
    printf 'Automatic dependency installation requires apt-get. Install manually: %s\n' "$*" >&2
    return 1
  }
  if [[ "$(id -u)" != 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {
      printf 'Dependency installation requires sudo or root privileges. Install manually: %s\n' "$*" >&2
      return 1
    }
    package_command=(sudo apt-get)
  fi
  "${package_command[@]}" update && "${package_command[@]}" install -y "$@"
}

ensure_linux_host_dependencies() {
  local packages=(python3 python3-venv python3-pip) package status
  local missing=()
  if [[ "$INSTALL_MODE" == desktop ]]; then
    packages+=(python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 wireplumber)
  fi
  # Other distributions retain their existing interpreter/backend checks.
  command -v apt-get >/dev/null 2>&1 || return 0
  for package in "${packages[@]}"; do
    status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null)" || status=""
    if [[ "$status" != 'install ok installed' ]]; then missing+=("$package"); fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    printf 'Installing required Linux host packages: %s\n' "${missing[*]}"
    install_linux_packages "${missing[@]}" || return 1
  fi
}

linux_supercollider_installed() {
  command -v sclang >/dev/null 2>&1 && command -v scsynth >/dev/null 2>&1
}

linux_supercollider_install_help() {
  cat >&2 <<'HELP'
Continuing without verified audio dependencies: capture, history, the web UI,
and browser animal recordings still work. Synthesized audio may be unavailable.
On Debian, Ubuntu, or Raspberry Pi OS, run:
  sudo apt-get update
  sudo apt-get install supercollider-language supercollider-server pipewire-jack
On other distributions, install SuperCollider using your system package manager:
  https://supercollider.github.io/downloads
Then rerun the Gaiascapes installer to verify sclang, scsynth, and pw-jack are on PATH.
HELP
}

ensure_linux_supercollider() {
  if linux_supercollider_installed && command -v pw-jack >/dev/null 2>&1; then
    printf 'SuperCollider and PipeWire JACK support detected.\n'
    return 0
  fi
  if [[ "${GAIA_SCAPE_INSTALL_SUPERCOLLIDER:-yes}" == no ]]; then
    printf 'SuperCollider installation skipped by GAIA_SCAPE_INSTALL_SUPERCOLLIDER=no.\n' >&2
    linux_supercollider_install_help
    return 0
  fi
  printf 'Installing SuperCollider and PipeWire JACK support through apt-get.\n'
  if install_linux_packages supercollider-language supercollider-server pipewire-jack; then
    if linux_supercollider_installed && command -v pw-jack >/dev/null 2>&1; then
      printf 'SuperCollider and PipeWire JACK support installed and detected.\n'
      return 0
    fi
    printf 'Package installation completed, but sclang, scsynth, and/or pw-jack are missing from PATH.\n' >&2
  else
    printf 'SuperCollider package installation failed. Check the package-manager error above.\n' >&2
  fi
  linux_supercollider_install_help
}
