# Architecture and compatibility contracts

Gaiascapes is a host service with bounded worker subprocesses and optional desktop
and audio components.
The domain package does not import providers, HTTP, SQLite, or SuperCollider.

## Responsibilities

| Module | Responsibility |
| --- | --- |
| `gaiascapes.events`, `gaiascapes.score` | Normalized observations and deterministic score mapping |
| `contracts` | Structural provider and renderer interfaces |
| `polling` | Independent source cadence, timeout dispatch, overlap protection |
| `worker`, `netcdf_worker` | Disposable provider processes and isolated native decoding |
| `capture` | SQLite transactions, deduplication, retention, filtered queries |
| `history` | Visible history assembled from observations and emitted cues |
| `playback`, `performance` | Continuous task ownership and timed score playback |
| `settings`, `config` | Validated candidates, process overrides, atomic persistence |
| `service` | Coordinate these components and apply musical/provider policies |
| `app`, `desktop` | HTTP and native window adapters |

Each provider has a polling task and an async capture lock. Manual captures
share those locks. Built-in clients run in disposable subprocesses: capture has
an overall 45-second deadline and recording retrieval has a 60-second deadline.
Timeouts and cancellations kill and reap the worker before returning. Completed
operations return normalized events and changed client state; state is applied
only if the original client snapshot remains current. Custom in-process provider
adapters retain a lock until their synchronous call drains.

Native NetCDF operations run directly inside provider workers, or in a separate
20-second worker when called standalone. No process runs simultaneous native
decodes. Provider failures retain independent retry/backoff state, and successful
batches become available without waiting for other providers. Recording retrieval
is serialized per kind; the playback-progress watchdog runs independently.

Stop clears the playback-enabled state while leaving the selected mode and
capture unchanged. Continuous tasks are cancelled and awaited. In-flight audio
transport calls drain before Stop completes. Start and Stop are serialized, as
are replay replacements. Stopping transient scheduling does not forcibly cut
short a synth's existing decay; persistent backgrounds receive layer-stop cues.

HTTP settings updates hold a coordination lock, validate a copied candidate,
and finish saving it before updating the live config or pruning retired
locations. Environment override values are preserved only in process memory.
Forecast and credential changes replace clients, so old workers cannot mutate
new caches. Results from replaced clients are discarded. Forecast requests
also snapshot their location catalog for response parsing. Persistence failure
leaves runtime settings and history unchanged. A later renderer/storage apply
failure is reported explicitly as HTTP 503 with the committed settings retained;
restart reapplies those settings. JSON and SQLite are not one cross-file transaction.

SQLite retains its existing tables and keys; the provider/kind/time index is
additive. Visible history filters excluded kinds before limiting newest-first.
Replay remains chronological. NOAA restart fallback queries only NOAA records;
MTG restoration queries only MTG records and resumes the eligible portions of
stored products on their fixed delayed timeline. Caches and restored timelines
remain bounded.

## Normalized event contract

The persistent identity is `(provider, event_id)`. Providers must supply stable
IDs and must not treat repeated observations as new events. `kind` identifies
semantics independently of the provider or selected voice.

| Field | Meaning |
| --- | --- |
| `timestamp` | UTC Unix seconds for observation/model validity, not ingestion time |
| `latitude`, `longitude` | Decimal degrees, north/east positive |
| `strength` | Unitless musical intensity clamped to 0–1 |
| `traits` | JSON-compatible metadata; absent/null measurements mean unavailable |
| `ingested_at` (store only) | UTC Unix seconds when the observation was captured |

Existing trait names and units are compatibility-sensitive. Additional traits
are allowed; renaming a field or changing its unit requires an explicit migration
or a backward-compatible reader. Display-unit selection never changes stored units.

| Event | Trait names and units |
| --- | --- |
| Earthquake | `magnitude` (reported magnitude), `depth_km`, `place`, `url` |
| Ocean swell | `wave_height_m`, `swell_height_m`, `swell_period_s`, `swell_direction_deg`, `sea_level_msl_m`, `modeled` |
| Tide turn | `tide_state` (`high`/`low`), `sea_level_msl_m`, `modeled` |
| Storm potential | `cape_jkg`, `weather_code`, `showers_mm`, `wind_gust_kmh`, `forecast` |
| NOAA lightning | `flash_energy_j`, `flash_area_km2`, `flash_duration_ms`, `quality_flag`, `flash_id`, `satellite`, `granule`, `observed` |
| MTG lightning | `flash_radiance_mw_m2_sr`, `flash_duration_ms`, `flash_footprint_pixels`, `event_count`, `group_count`, `flash_id`, `satellite`, `granule`, `product`, `observed` |
| Birdsong | `media_url`, `title`, `creator`, `license`, `license_url`, `source_url`, `commons_page_id`, `place` |

`magnitude` on non-earthquake events is a legacy rendering/display value, not a
universal physical measurement: swell uses height, tide uses sea level, storm
uses CAPE/1000, lightning uses 2 + 5×strength, and birdsong uses 1. New code should
prefer the explicitly named physical metric. Forecasts are not observations.

## Renderer and package contracts

The OSC positional contract remains the one documented in README. Renderer
return value `False` suppresses cue journaling; `None` permits visual-only cues
when OSC is disabled. Successful UDP transmission does not prove audible output.
Birdsong uses the browser cue stream and local media cache.

`src/gaiascapes/__init__.py::__version__` is the canonical version. Setuptools,
the web UI, and the desktop bundle derive their versions from it. Dependency
ranges live only in `pyproject.toml`; `requirements.txt` delegates to its extras.
Core installation requires neither desktop libraries nor satellite decoders.
An enabled source with a missing optional dependency reports a source error;
other sources and the web application remain available.

## Validation

CI runs Python 3.10 and 3.13 on macOS, Linux x86-64, and Linux ARM64, with isolated
runtime state. It builds a wheel and tests its assets, CLI entry point, and
HTTP routes in a clean environment without desktop or lightning dependencies.
The ARM64 runner verifies software portability, not Raspberry Pi audio devices,
SuperCollider latency, desktop rendering, or live-provider availability.

Before a hardware release, install on a disposable Linux/Raspberry Pi runtime,
check capture/history with SuperCollider absent, then verify audio output,
Stop/Start behavior, restart recovery, and sustained operation with both
lightning providers. Keep test data separate from an existing installation.
