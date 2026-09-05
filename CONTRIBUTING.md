# Contributing to Gaia Scape

Thank you for helping improve Gaia Scape.

Gaia Scape is a host-first Python application that captures terrestrial events
and turns their timing, location, and intensity into generative music. It runs
on macOS, Linux, and Raspberry Pi OS. SuperCollider is the preferred audio
renderer, but event capture, history, and the web interface must remain useful
without it.

Please follow the project [Code of Conduct](CODE_OF_CONDUCT.md) in all project
spaces.

## Workflow

1. Fork the repository.
2. Create a focused feature branch from `trunk`.
3. Make and test one logical change.
4. Open a pull request against `trunk` with a clear summary and verification
   notes.

Avoid unrelated formatting or refactoring churn. Propose broad architectural
changes in an issue before beginning a large rewrite.

## Development setup

Python 3.10 or newer is required. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,lightning,eumetsat]'
```

Run a development instance with an isolated data directory so captured events
and settings do not enter the checkout:

```sh
GAIA_SCAPE_DATA_DIR=/tmp/gaia-scape-dev \
  .venv/bin/python Gaia_Scape.py
```

The default HTTP port is `8768`. Do not change the project default to `8000`,
`8765`, or `8767`, which belong to sibling applications. OSC defaults to UDP
port `57130`.

## Areas where contributions are welcome

- Environmental source adapters and normalization fixtures
- Generative score construction and renderer-independent cue behavior
- SuperCollider voices and audio-output reliability
- Event history, deduplication, retention, and migration behavior
- Web UI clarity, accessibility, responsiveness, and map behavior
- macOS, Linux, and Raspberry Pi installation and launcher improvements
- Documentation and automated test coverage

ESP32 support may be added later as a companion device. Gaia Scape remains a
host-first application.

## Architecture boundaries

Keep these boundaries intact:

- `src/gaia_scape/` contains provider-independent normalized events and score
  construction.
- `src/gaia_scape_host/usgs.py`, `open_meteo.py`, and `noaa_glm.py` retrieve
  and normalize provider data.
- `src/gaia_scape_host/capture.py` owns SQLite persistence.
- `src/gaia_scape_host/service.py` coordinates capture, history, continuous
  playback, and renderer calls.
- `src/gaia_scape_host/osc.py` implements the renderer interface used by the
  host service.
- `supercollider/gaia-scape.scd` implements the preferred audio renderer.
- `src/gaia_scape_host/templates/` and `static/` implement the web interface.

Normalized events, score construction, and renderer interfaces must remain
provider-independent. Do not make core scoring or persistence depend on a
particular feed's transport format.

Keep FastAPI route handlers thin. Network requests, SQLite operations, and
renderer calls are blocking work and must not stall the async event loop. Use
the existing service patterns and preserve prompt cancellation and shutdown.

## Environmental data sources

Provider adapters must:

- Validate document shape, values, coordinates, and timestamps.
- Bound response sizes and network timeouts.
- Preserve stable provider event identifiers for deduplication.
- Keep raw provider details in event traits without leaking them into core
  interfaces.
- Distinguish observations from forecasts and modeled conditions.
- Preserve required provider attribution in the UI and documentation.
- Use fixtures or fakes in automated tests; tests must not require live
  network services.

Do not describe Open-Meteo storm potential as observed lightning, or modeled
marine values as suitable for navigation.

## Runtime state and database changes

Runtime state belongs under the selected installation's `data/` directory,
never inside an installed Python package. The current files are
`data/config.json`, `data/gaia_scape.sqlite3`, and optional audio-device state.

Do not commit runtime copies containing captured events, settings, precise
personal locations, private network details, or credentials. Tests must use
pytest's `tmp_path` or another temporary directory.

If changing persistence or configuration:

- Preserve existing installations whenever practical.
- Add migration or compatibility behavior for renamed fields or databases.
- Keep event deduplication, retention, and chronological queries working.
- Close SQLite connections deterministically.
- Add focused regression tests for old and new state formats.

Installers and uninstallers must preserve the selected installation's `data/`
directory unless the user explicitly requests its removal.

## Renderer and UI changes

SuperCollider must not be required for capture, history, status, or the web
interface. Renderer failures should remain visible to operators without
discarding normalized events.

When changing OSC messages, update the sender, SuperCollider receiver, tests,
and the contract documented in `README.md` together. Keep renderer interfaces
usable by future renderers.

For web changes, verify keyboard behavior, accessible names, responsive
layouts, and the browser console as appropriate. Keep static asset cache keys
tied to the application version.

## Dependency policy

Gaia Scape intentionally keeps its dependency set small.

- Prefer the Python standard library and existing utilities where practical.
- Explain why a new dependency is necessary.
- Consider macOS, Linux, Raspberry Pi OS, and Python 3.10 compatibility.
- Do not make optional audio or desktop components mandatory for the headless
  service.
- Update `pyproject.toml`, `requirements.txt`, installation tests, and
  `THIRD_PARTY_NOTICES.md` when a dependency change requires it.

## Testing

Run the smallest relevant tests while developing. Before submitting a code
change, run the repository-required checks:

```sh
GAIA_SCAPE_DATA_DIR=$(mktemp -d) python -m pytest -q
python -m compileall -q src tests
```

Changes to installers or launchers should include the relevant tests under
`tests/test_install_scripts.py` or `tests/test_launchers.py`. Hardware,
SuperCollider, and live-provider behavior should be represented by fakes or
fixtures in the automated suite, with any manual verification described in
the pull request.

## Versioning

Runtime changes update `__version__` in `src/gaia_scape/__init__.py`;
`pyproject.toml` reads it dynamically. Use:

```text
v0.<two-digit-year>.<day-of-year>.<patch>
```

For example, the first runtime release on day 237 of 2026 is `v0.26.237.1`.
Documentation-only changes do not require a runtime version bump.

## Pull request checklist

A pull request should include:

- A concise explanation of what changed and why
- Tests and manual checks performed
- Platform and Python version when platform behavior is relevant
- Screenshots for material UI changes
- Migration, installer, or data-retention implications
- Documentation and attribution updates required by the change
- Any behavior that remains unverified

Gaia Scape is a pre-1.0 project under active development. Internal structure
may evolve, but normalized event contracts, persisted user state, and existing
installations should remain compatible whenever practical.

See [ARCHITECTURE.md](ARCHITECTURE.md) for normalized metric units, provider
threading constraints, settings commit ordering, and platform validation.
