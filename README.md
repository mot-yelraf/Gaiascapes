# Gaia Scape

Gaia Scape captures live terrestrial events and turns their time, location,
and intensity into generative soundscapes. The primary runtime is
Python on macOS, Linux, or Raspberry Pi. SuperCollider is the preferred audio
engine; capture, history, and the web interface continue to work when it is not
installed.

## Who this is for

- Makers and students who want a real-world python example.
- Contributors who want a small, readable Python codebase.

The first source is the USGS all-day earthquake feed. Events are normalized,
deduplicated in SQLite, and retained locally. The Live Events tile offers two modes:
Capture replays a selected history window, while Continuous sounds newly captured
earthquakes immediately and rotates ambient data globally. The selected ocean-swell
or Storm Outlook background remains continuous while event voices play over it.
Event 1, Event 2, and Event 3 are independent: Earthquake and Seismic Bell voices
follow USGS earthquakes, Tidal Bell follows modeled tide turns, and Lightning R2D2
or Natural Thunder follows normalized lightning-flash observations. Selecting the
same voice in multiple slots emits each configured cue for every matching event.
Continuous mode does not derive ocean sound from the listener’s location. Ambient
cues play at 75% of their mapped level so full-level earthquake cues remain distinct.
The global Background Sounds location rotates every 23 seconds. Background cues span 24.5
seconds, retaining a 1.5-second overlap while the next location fades in.
Lightning R2D2 uses a short crack, descending pitch contour, glassy decay, and
pentatonic flash-by-flash pitch variation at least four semitones above other
events, paired with a yellow-gold map pulse. Each slot's volume also scales its
map-pulse radius, so quiet lightning remains visible as a compact burst without
overwhelming the background animation. Natural Thunder replaces pitched oscillators with an irregular filtered-noise
crack, strength-weighted brown-noise rumble, deep body, randomized envelope-shaped
reflections, compression, and peak limiting. The reflections avoid per-cue delay
buffers, and the audio server reserves additional real-time memory so the voice remains
lightweight enough for dense lightning fields. NOAA GOES-East and GOES-West GLM LCFA granules are checked
independently every 20 seconds. Quality-accepted flashes
are normalized with their observation timestamp, position, optical energy, area,
duration, satellite, and granule identity.

Optional Open-Meteo sources add:

- modeled swell conditions at twelve global surf locations;
- modeled high and low tide turns when a local sea-level extremum is present;
- global Storm Outlook forecasts derived from CAPE and thunderstorm weather codes.

The NOAA GLM source is enabled during installation or one-time configuration
migration. Each granule may contain hundreds of flashes, so Gaia records a bounded
database sample while this experiment chronologically selects quality-accepted
flashes for sound. A field-wide ceiling distributes at most 120 cues across each
20-second update so corrupt or exceptional satellite data cannot overwhelm the audio
engine. When either lightning voice is selected, its unlabeled sample-rate
slider can select every first through every eleventh flash. The saved setting applies
to the lightning feed regardless of which event slot displays the voice. Those notes
retain their original observed time gaps, preserving
the natural bursts and pauses in the lightning field. If NOAA has not published
a newer granule by the next polling cycle, Gaia replays the last non-empty flash
field with the same relative timing until fresh lightning information replaces it. GLM
flashes remain available for deduplication and replay but are intentionally omitted
from Environmental Event History, its Events count, and the Event Sounds status
field. Live yellow-gold pulses still show their observed positions. The console and
`/api/status` report granules, raw flashes, sampled flashes, inserts, and errors, for
example: `NOAA GLM update: 2 granules, 534 raw flashes, 8 sampled, 8 new, 47 sonified`.
Gaia also quarantines exceptionally dense tropical GOES-19 fields during NOAA's
documented 15:00–19:00 UTC false-alarm window, active since July 17, 2026.

Storm potential is not an observed lightning-flash feed. Marine values are
model output and are not suitable for navigation. Open-Meteo marine data
combines models from DWD, ECMWF, Météo-France, NOAA, and other contributing
agencies; source attribution is shown in Settings. Gaia refreshes these forecasts
once per hour and honors provider throttling while retaining the last
successful forecast.

Event History adds a Storm Outlook or ocean-swell location when the continuous
background first visits it, then replaces that location only when its forecast
values change. Unchanged global rotations still update Background Sounds without
adding redundant history. Earthquake, tide-turn, and other event history remains
chronological. Captured forecast records remain available to the replay engine.

## Ports

- HTTP: `8768` (`GAIA_SCAPE_HTTP_PORT`)
- OSC UDP: `57130` (`GAIA_SCAPE_OSC_PORT`)

The supplied launchers bind to `0.0.0.0` for private-LAN access by default. Browse
to `http://<gaia-host-ip>:8768` from another computer. Set
`GAIA_SCAPE_HTTP_HOST=127.0.0.1` for access from this computer only.

## Installation

Python 3.10 or newer and internet access are required during installation.
Python packages are declared in `pyproject.toml` and mirrored in `requirements.txt`.
Astral 3.2 is included for location-aware solar and lunar calculations. System and
SuperCollider prerequisites are listed in `SYSTEM_REQUIREMENTS.md`. SuperCollider
may be installed before or after Gaia Scape.

On macOS:

```sh
./scripts/install_macos.sh
```

On Linux or Raspberry Pi OS:

```sh
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
./scripts/install_linux.sh
```

The installer presents a folder selector, remembers the chosen location,
creates a private `.venv`, installs a self-contained Python application, and
preserves the selected installation's `data/` directory during updates. For an
unattended installation:

```sh
GAIA_SCAPE_INSTALL_DIR=/absolute/path/Gaia_Scape ./install.sh
```

Set `GAIA_SCAPE_AUTO_START=yes` to install a user-level systemd service on
Linux/Raspberry Pi or a LaunchAgent on macOS.

Run `./uninstall.sh` from the installed directory to remove the application and
auto-start service while preserving captured data. To remove the data as well:

```sh
GAIA_SCAPE_REMOVE_DATA=yes ./uninstall.sh
```

The GUI launcher starts and supervises SuperCollider automatically, starts the
local web service when needed, and opens Gaia Scape in a native pywebview window:

```sh
./run_gaia_scape_gui.sh
```

Closing the window stops the web service started by that window. If a Gaia Scape
service is already listening on the configured port, the desktop app attaches to
it and leaves it running. Window size and position can be overridden with
`GAIA_SCAPE_GUI_WIDTH`, `GAIA_SCAPE_GUI_HEIGHT`, `GAIA_SCAPE_GUI_X`, and
`GAIA_SCAPE_GUI_Y`.

On macOS, the GUI creates a lightweight identity bundle at
`~/Library/Application Support/Gaia Scape/Gaia Scape.app` and relaunches through
it so system interfaces identify the process as Gaia Scape instead of Python.
Set `GAIA_SCAPE_HEADLESS=1` to suppress this GUI-only relaunch when embedding the
desktop module in an unattended process.

To select and remember a particular audio output, write its exact
SuperCollider device name to `data/audio-device`. For example:

```sh
printf '%s\n' 'DELL S2725QC' > data/audio-device
```

For separate-process operation, run `./run_supercollider.sh` in one terminal
and `./run_gaia_scape_gui.sh` in another. You can override the remembered
device for one launch with `GAIA_SCAPE_AUDIO_DEVICE` or `--audio-device`.
Passing `GAIA_SCAPE_AUDIO_DEVICE` to the installer saves that selection in
the installed data directory.

For unattended operation, use `./run_gaia_scape.sh`. Open
`http://127.0.0.1:8768` locally or `http://<computer-ip>:8768` on the same LAN.

## OSC cue contract

Gaia Scape sends immediate UDP messages to `/gaia/cue` with these ordered
arguments:

```text
event_id, kind, instrument, pitch, velocity, duration, pan, strength,
longitude, latitude, raw_magnitude, depth_km
```

Continuous ocean or storm state uses the same arguments at `/gaia/layer`; repeated
messages smoothly update one persistent synth instead of replacing it. Storm
forecast strength controls rainfall density and intensity. `/gaia/layer/stop`
releases the synth when continuous mode stops or the background selection changes.

The included `supercollider/gaia-scape.scd` listens on UDP 57130 and provides
earthquake, seismic-bell, Lightning R2D2, Natural Thunder, ocean-swell, tidal-bell, and Storm Outlook
voices. The
Settings menu selects capture sources, three independent event voices, and one continuous
background. Each musical role can also be set to None. The persisted Units setting
displays swell and tide heights in meters or feet and earthquake depth in kilometers
or miles. Independent 0–100% volume sliders sit beneath each Preview button for
Event 1, Event 2, Event 3, and Background; the Lightning R2D2 default in Event 3
starts at 45% to leave headroom for dense flash fields. OSC host and port can be overridden with
`GAIA_SCAPE_OSC_HOST` and `GAIA_SCAPE_OSC_PORT`; change `oscPort` in the
SuperCollider script when selecting another receive port.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
GAIA_SCAPE_DATA_DIR=/tmp/gaia-scape-dev .venv/bin/python Gaia_Scape.py
```

Runtime state consists of `config.json` and `gaia_scape.sqlite3` under the
installation's `data/` directory.
