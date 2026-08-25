# Gaia_Scape agent guidance

- The project checkout path is `~/Projects/Gaia_Scape` (that is,
  `/Users/twfarley/Projects/Gaia_Scape`). Never rename, move, or temporarily
  relocate this directory, and never use `Gaia_Rhythms` or `Earth_Rhythms` as
  the project folder name.
- Gaia_Scape is a host-first Python application for macOS, Linux, and
  Raspberry Pi. ESP32 support may be added later as a companion device.
- The default HTTP port is 8768. Ports 8000, 8765, and 8767 belong to sibling
  projects and must not become defaults here.
- Keep normalized events, score construction, and renderer interfaces
  provider-independent.
- Runtime state belongs under the selected installation's `data/` directory,
  never inside the installed Python package.
- SuperCollider is the preferred renderer but must not be required for event
  capture, history, or the web UI to operate.
- Run `python -m pytest -q` and `python -m compileall -q src tests` after code
  changes.
- Version runtime changes in `pyproject.toml` using `v0.<yy>.<doy>.<patch>`.
