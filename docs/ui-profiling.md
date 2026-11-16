# Complete UI settings profiling

`scripts/ui_profiling.py` drives the real settings interface, verifies saved
values and observable runtime state, and measures browser recording playback.
The default is **three complete runs**, each including a local fixture phase and
a real-provider phase. It has no 30-minute cutoff.

```sh
python -m pip install playwright
python -m playwright install chromium
python scripts/ui_profiling.py --runs 3 \
  --credentials-from ~/Gaiascapes/data/config.json
```

`--credentials-from` reads only the existing Xeno-canto/EUMETSAT credentials into
the private real-mode runtime. It does not edit or exercise password fields and
never changes the source configuration. Fixture mode uses dummy credentials and
does not load that file. Keys are removed from each test configuration after its
server stops. Credentials can alternatively be supplied as
`UI_PROFILING_XENO_CANTO_API_KEY`, `UI_PROFILING_EUMETSAT_CONSUMER_KEY`, and
`UI_PROFILING_EUMETSAT_CONSUMER_SECRET` environment values.

## Coverage

Every non-credential control discovered inside the Settings dialog must be mapped
to a case. Discovery fails if an unknown control is encountered. The plan covers:

- Every offered background and event voice, including returning to recent sounds;
  independent gains, source disable/re-enable, and mute/unmute transitions.
- All themes, animation modes, palettes, Paint shapes, animation filters, units,
  map projections, map centers, and location order choices.
- Both Birdsong providers and both states of every recording, weather, lightning,
  announcement, and approximate-host-location checkbox.
- All announcement dialects, variants, synthesizer choices, and volume boundaries;
  rendered speech responses and their actual engine/fallback are retained.
- Every discrete lightning sample-rate value on each of the three synchronized
  sliders. Continuous percentage sliders cover minimum, midpoint, and maximum;
  sound gains also receive the existing quarter-volume transition checks.
- Names and coordinates for all 19 locations in each editable catalog, marker
  movement through the map, and Restore defaults. Each offered marine site's
  inclusion checkbox receives both states. Commons Birdsong read-only behavior
  is checked explicitly. All edits are confined to disposable runtime data.
- Sound-picker arrow and keyboard navigation, all four Preview buttons, device
  listen/mute controls, and opening the read-only Event History tab.

The test covers settings individually; it does not attempt every combination.
Credential editing is the sole excluded settings category. Main-window controls
unrelated to the Settings dialog, operating-system menus, and physical audio
hardware are outside this profile's scope.

Each case verifies saved configuration against the selected controls. Provider
activation additionally waits for a new successful update after enabling its
source. The real phase uses actual providers and bundled recordings. The local
phase supplies deterministic recording, capture, and location adapters through
the same settings, capture, and scheduling paths; adapters remain deterministic
when a provider/location change rebuilds a client. It exercises actual installed
speech renderers, not a speech stub.

Missing credentials or unavailable services do not count as verified coverage.
Blocked and failed cases remain visible, subsequent cases continue, and later
runs still execute. No partial, filtered, or timed run is labeled fully verified.

## Timing

Sound-affecting cases allow **120 seconds for activation**, then observe for
**45 seconds**, sampling every **2 seconds**. A stalled clock or missing audio
signal lasting **15 seconds** after activation fails the case. Other configuration
cases settle for **5 seconds** after their runtime checks succeed. Previews use
a shorter observation appropriate to their intentionally short playback.

Activation slower than two scheduling intervals plus five seconds is flagged as
delayed even when it eventually passes. The normal 23-second scheduling interval
is retained. Defaults of the current UI produce 237 cases per mode, with about
70 minutes of observation per phase before activation/provider delays. Three
local-and-real runs therefore need at least seven hours and can take longer.
The generated `plan.json` and startup estimate are authoritative if the UI changes.

Recorded backgrounds require a correctly routed cue, matching browser recording
kind and sequence, advancing playback clock, nonzero gain, and measured non-silent
Web Audio output. Retained playback is accepted when a sound remains selected
while other settings change. Natural silent gaps are distinguishable from stalled
clocks in the evidence; `--silence-timeout` controls the allowed gap.

Generated event voices and weather backgrounds receive cue-routing checks only;
**audible SuperCollider output and physical speakers are not verified**. OSC is
disabled, so the tool does not contact the installed renderer. Labeled synthetic
Earth-event probes test event routing in both modes and never enter installed
history. Fixture recordings are local WAV tones. Real Commons recordings may be
downloaded on demand into the isolated cache; cold-cache time is included in
activation latency and recorded loading states.

## Isolation and artifacts

Every run/mode gets new runtime data, an ephemeral loopback HTTP port, and a new
Chromium session. The tool never attaches to the installed process. It removes
inherited HTTP/OSC overrides before starting the child server. Installed
configuration files are fingerprinted for visibility; if the user changes them
while profiling, the change is noted without overwriting it or attributing it to
a test failure.

The printed output directory contains:

- `report.json`: overall run/mode outcomes, completed runs, verified runs, and
  coverage audits. `completed_runs` counts fully attempted plans;
  `verified_runs` additionally requires all their checks to pass.
- `run-01/fixture/`, `run-01/real/`, through `run-03/real/`: independent phase results.
- Each phase's `inventory.json` and `plan.json`: discovered controls and every case.
- `status.json`: the current case and latest observation; kept small for frequent
  updates during long runs.
- `report.json`: compact per-case outcomes, activation latency, and explicit
  unattempted/unverified case lists. Full evidence lives in `step-NNNN.json`.
- `step-NNNN.json`: selected and saved settings, cue evidence, audio samples,
  source health, speech responses, heap/long-task samples, and errors.
- `browser-errors.json`, `server.log`, and failed-step screenshots/traces. Use
  `python -m playwright show-trace /path/to/trace-NNNN.zip` to inspect a trace.
- `runtime/data/`: the private settings/database/recording cache retained for
  diagnosis, with supplied credentials scrubbed after shutdown.

Successful traces are discarded unless `--trace-all` is requested. Samples are
written once per case; live status is separate, avoiding repeated rewriting of
an ever-growing report. Artifact directories are private; review them before
sharing because real media metadata or host-location tests can contain location
information.

Ctrl+C or SIGTERM requests a cooperative stop between bounded browser operations,
saves partial evidence, and reaps the owned server. Exit status is `0` when checks
that ran passed, `1` for failed/blocked cases or errors, and `130` for interruption.
Always inspect coverage audits as well as the exit status.

## Focused development checks

Explicit filters, `--max-steps`, and `--minutes` are diagnostic shortcuts; their
coverage is reported as incomplete. A time cap is split across requested
runs/modes and finishes the current bounded step.

```sh
python scripts/ui_profiling.py --mode fixture --runs 1 --max-steps 1 \
  --dwell-seconds 3
python scripts/ui_profiling.py --mode fixture --runs 1 \
  --case-filter locations/ocean_swell/ --setting-dwell-seconds 2
```

`--start-step N` rotates the plan's starting point. For calibrated silence
failure, use `--mode fixture --runs 1 --fixture-silent-kind birdsong --max-steps 1`.
The intentionally silent recording advances its clock but cannot satisfy the
signal check. Intervals below 10 seconds are rejected because they can enter the
application's short-preview path instead of normal full-recording playback.
