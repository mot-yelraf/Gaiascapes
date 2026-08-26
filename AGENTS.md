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

## Code Generation Rules

- Keep edits minimal, targeted, and easy to review.
- Do not reformat unrelated code.
- Prefer clear, explicit naming over abstraction for its own sake.
- Keep modules cohesive and avoid deep or circular import chains.
- Prefer the Python standard library unless a dependency is clearly justified.
- Avoid heavy dependencies unless necessary.
- Prefer explicit error handling and clear operator-visible failures over
  layered silent fallbacks.
- Add concise docstrings to module level with explanatory paragraph after the concise description.
- Add concise docstrings to public classes and functions when touching public
  interfaces.
- Do not add noisy logging in hot paths.


## Safety Rules

- Do not run destructive commands without explicit user request.
- Prefer idempotent operations.
- Avoid broad search-and-replace edits unless the task specifically requires
  them.
- Never run previews, browser checks, tests, or diagnostic servers against the
  installed runtime's `data/` directory. Create a dedicated temporary data
  directory and set `GAIA_SCAPE_DATA_DIR` to that exact directory before
  starting the test process.
- Treat test-only HTTP, OSC, host, audio-device, and other environment
  overrides as process-local values. Never save, copy, migrate, or otherwise
  materialize them into the installed `config.json` or other runtime state.
- Do not use the installed Gaia Scape process for UI tests that can persist
  settings. After any test involving runtime overrides, verify that the
  installed configuration still uses the intended production parameters,
  including HTTP port `8768` and OSC port `57130`, before installation or
  handoff.
- Treat settings materialization, normalized metric names, SQLite persistence,
  and gateway polling behavior as compatibility-sensitive.
- Surface major concurrency or storage refactors before implementation.

## Versioning Rule

When you make a code content change, update the canonical `__version__` in
`caelus/__init__.py` using:

```text
v0.<year>.<doy>.<x>
```

- `<year>`: 2-digit year.
- `<doy>`: 3-digit day of year.
- `<x>`: per-day incrementing patch counter.

If the date matches today, increment `<x>` by 1. If the date has changed,
reset `<x>` to `1`.

Documentation-only changes, including edits to this file, do not require a
version bump.
