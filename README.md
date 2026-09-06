# Gaia Scape

Gaia Scape captures live terrestrial events and turns their time, location,
and intensity into generative soundscapes. The primary runtime is
Python on macOS, Linux, or Raspberry Pi. SuperCollider is the preferred audio
engine; capture, history, and the web interface continue to work when it is not
installed.

For illustrated operating instructions, settings, and credential setup, see the
[User Guide](USER_GUIDE.md). Installation instructions remain in this README.

## Who this is for

- Makers and students who want a real-world python example.
- Contributors who want a small, readable Python codebase.

The first source is the USGS all-day earthquake feed. Events are normalized,
deduplicated in SQLite, and retained locally. The Live Events tile offers two modes:
Capture replays a selected history window, while Continuous sounds newly captured
earthquakes immediately and rotates ambient data globally. The selected ocean-swell,
Storm Outlook, or Birdsong Atlas background remains continuous while event voices play
over it.
Event 1, Event 2, and Event 3 are independent: Earthquake and Seismic Bell voices
follow USGS earthquakes, Tidal Bell follows modeled tide turns, and Lightning R2D2
or Thunder follows normalized lightning-flash observations. Selecting the
same voice in multiple slots emits each configured cue for every matching event.
The Earthquake voice uses depth-damped sub-bass and irregular low-frequency
surface/body-wave modulation, with strength-scaled cues lasting up to seven seconds.
Continuous mode does not derive ocean sound from the listener’s location. Ambient
cues play at 75% of their mapped level so full-level earthquake cues remain distinct.
The global Background Sounds location rotates every 23 seconds. Background cues span 24.5
seconds, retaining a 1.5-second overlap while the next location fades in.
Birdsong Atlas cycles through 19 regions on six continents using freely licensed
Wikimedia Commons recordings. Gaia Scape resolves files through the keyless Commons
API, accepts only public-domain, CC0, CC BY, or CC BY-SA audio, and caches each selected
recording under `data/media/birdsong/`. The interface displays the recording's creator,
license, and Commons source page; no Wikimedia account or API key is required.
Frog Calls is another browser-played background, with its own source switch and
19 editable global regions in Sound locations. Select Frog Calls in Instruments
for volume and Preview controls. It uses Xeno-canto frog and toad recordings
within 100 km of each region center, retaining the recording's actual location
and attribution. Birdsong and Frog Calls share one Xeno-canto API key: enter or
replace it in either source tile. Blank fields preserve the saved key. Frog Calls
is disabled by default and caches its media under `data/media/frog_calls/`.
Frog searches include ungraded recordings and calls of 1–180 seconds, accepting
CC BY and CC BY-SA licenses. The background status strip reports loading and
lookup failures, including regions without suitable recordings.

Whale Song and Dolphin Calls use NOAA NCEI / SanctSound recordings without an
API key. Enable their tiles under Background sound sources, select one in
Instruments, and choose included sites in Sound locations. Whale Song includes
six hydrophone sites in the Hawaiian Islands, Channel Islands, and Olympic
Coast. Dolphin Calls includes eleven sites across the Hawaiian Islands,
Papahānaumokuākea, California, Olympic Coast, Florida Keys, Gray’s Reef, and
Stellwagen Bank. At least one site must remain selected. These are archived
recordings, and map points identify hydrophones rather than animal positions.

The bundled SanctSound catalog contains eight natural-speed humpback-song clips
and eleven dolphin clips, verified against the public archive on 2026-09-06.
Audio downloads are bounded to 64 MiB and cached beneath `data/media/whale_song/`
and `data/media/dolphin_calls/`, with archive size and checksum verification.
Playback rotates through selected sites and then through each site's clips.
Each cue retains recording date, contributor credit, metadata URL, and the
[NOAA/Navy SanctSound dataset citation and use constraints](https://doi.org/10.25921/saca-sp25).
No access key or live acoustic feed is needed. Source attribution belongs to
the recordings; the application's MIT license does not relicense archive audio.

The Birdsong tile in Sound Sources enables archived recordings and selects
Wikimedia Commons or Xeno-canto. For Xeno-canto, enter a personal API key there.
Select Birdsong as the Background in Instruments to control volume and preview it.
Disabling the Birdsong source stops playback while preserving the selected background. The key is stored in the local `data/config.json`
and is omitted from browser responses. The provider searches within 100 km of each of the 19 saved Birdsong locations for
A/B-quality CC BY-SA recordings, skips missing or restricted coordinates, and
uses the recording's actual location on the map. These are archived recordings;
the playback event time is current, while the original date and time remain in
the event's `recorded_date` and `recorded_time` traits. Catalogs are cached for
24 hours and audio under `data/media/birdsong/xeno-canto/`; successive rotations
select further recordings from each country. Downloads are limited to 64 MiB
and recordings to 10–180 seconds. An unavailable country or provider reports an
error rather than substituting another source. See the
[Xeno-canto API documentation](https://xeno-canto.org/explore/api).
Lightning R2D2 uses a short crack, descending pitch contour, glassy decay, and
pentatonic flash-by-flash pitch variation at least four semitones above other
events, paired with a yellow-gold map pulse. Each slot's volume also scales its
map-pulse radius, so quiet lightning remains visible as a compact burst without
overwhelming the background animation. Thunder replaces pitched oscillators with a
strength-weighted brown-noise rumble, deep body, randomized envelope-shaped
reflections, compression, and peak limiting. The reflections avoid per-cue delay
buffers, and the audio server reserves additional real-time memory so the voice remains
lightweight enough for dense lightning fields. Ocean Swells and Storm Outlook each
sample 19 globally distributed locations. NOAA GOES-East and GOES-West GLM LCFA granules are checked
independently every 20 seconds. Quality-accepted flashes
are normalized with their observation timestamp, position, optical energy, area,
duration, satellite, and granule identity.

An optional EUMETSAT Meteosat Third Generation Lightning Imager source extends
observed lightning coverage across Europe and Africa. It downloads the operational
LI Level 2 Lightning Flashes collection (`EO:EUM:DAT:0691`) through EUMETSAT's
EUMDAC client, normalizes flash time, position, radiance, duration, and composition,
and geographically samples each product to at most 1,000 observations, favoring
stronger flashes within each occupied map region. In Settings → Sound
sources, enable **EUMETSAT MTG Lightning Imager** and enter the Consumer Key and
Consumer Secret issued by the EUMETSAT Data Store. The credentials are saved only
in the selected installation's local `data/config.json`, whose permissions are
restricted to the current user; they are masked in the interface and omitted from
Gaia Scape API responses. Leave both fields blank on later saves to retain the
stored pair.

Each MTG product is presented once on a fixed 12-minute-delayed timeline. The
sampled flashes retain their relative observation timing across the ten-minute
product, so consecutive products form a continuous delayed stream instead of a
loop. Flashes that arrive after their scheduled presentation time are skipped
rather than released in a misleading burst. The map identifies MTG flashes with
a dashed gold pulse and labels them as delayed; NOAA GLM retains its existing
near-live solid pulse and independent 20-second field behavior. MTG timelines
stop quietly when data is missing and never turn cached flashes into new events.

The Sound locations Settings pane displays Ocean Swells, Storm Outlook,
Birdsong, and Frog Calls as 19-point catalogs on an
interactive world map. Select a numbered marker and click the map to relocate
it, or edit its name, latitude, and longitude directly. Catalogs are validated,
stored with the installation, and can be restored to the Gaia defaults.

Optional Open-Meteo sources add:

- modeled swell conditions at 19 global coastal locations;
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
from Environmental Event History and its stored count. Live yellow-gold pulses still
show their observed positions. The console and
`/api/status` report granules, raw flashes, sampled flashes, inserts, and errors, for
example: `NOAA GLM update: 2 granules, 534 raw flashes, 8 sampled, 8 new, 47 sonified`.
Gaia also quarantines exceptionally dense tropical GOES-19 fields during NOAA's
documented 15:00–19:00 UTC false-alarm window, active since July 17, 2026.

### Network recovery

Gaia Scape keeps capture, history, the web interface, and available audio layers
running when an environmental provider becomes unavailable. Each source reports
an online, degraded, offline, or recovering state through `/api/status`. Failed
sources retry independently with bounded exponential backoff and jitter, so one
outage does not interrupt healthy feeds.

Recent Open-Meteo forecasts can remain active for up to three hours, and a recent
NOAA GLM field can replay for up to five minutes. EUMETSAT MTG LI observations
remain fresh for up to 30 minutes, accommodating Data Store publication latency.
These limits prevent indefinitely
sonifying stale conditions. Stored forecast events and sampled GLM flashes provide
a restart-safe fallback when they are still fresh. The desktop displays recovery
changes as stacked notifications; click any notification to dismiss it.

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
Dependency versions are declared in `pyproject.toml`; `requirements.txt` delegates
to its desktop and satellite extras.
The map uses an approximate public-IP location from `ipapi.co`, with `ipwho.is`
as an HTTPS fallback, to mark the host system with a small green circle. The
result is held only in process memory. System and SuperCollider prerequisites
are listed in `SYSTEM_REQUIREMENTS.md`. SuperCollider may be installed before
or after Gaia Scape.

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
preserves the selected installation's `data/` directory during updates.
For a headless installation without pywebview or GTK/WebKit:

```sh
GAIA_SCAPE_INSTALL_MODE=headless GAIA_SCAPE_INSTALL_DIR=/absolute/path/Gaia_Scape ./install.sh
```

For an
unattended desktop installation:

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

By default, Gaia Scape follows the sound output selected in the operating
system each time it starts. To pin a particular audio output instead, write
its exact SuperCollider device name to `data/audio-device`. For example:

```sh
printf '%s\n' 'DELL S2725QC' > data/audio-device
```

Write `system` to that file to restore system-output following. On macOS,
`data/audio-device-map` may contain tab-separated system and SuperCollider
device names. This supports output-only Bluetooth aggregate devices without
pinning other system outputs.

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
Birdsong uses the renderer-neutral emitted-cue stream and is played from Gaia Scape's
local media cache by the web view, so it does not require a SuperCollider sampler.

The included `supercollider/gaia-scape.scd` listens on UDP 57130 and provides
earthquake, seismic-bell, Lightning R2D2, Thunder, ocean-swell, tidal-bell, and Storm Outlook
voices. The
Settings menu selects capture sources, three independent event voices, and one continuous
background, including Birdsong Atlas. Each musical role can also be set to None. The persisted Units setting
displays swell and tide heights in meters or feet and earthquake depth in kilometers
or miles. The Dashboard or Map selection is also stored with the installation and
restored when Gaia Scape starts. Both views show a three-column status strip with the
selected background's location and forecast characteristics, the latest event's type
with its coordinates and event time, and a separately retained latest earthquake area
followed by its magnitude, coordinates, and event time.
Independent 0–100%
volume sliders sit beneath each Preview button for
Event 1, Event 2, Event 3, and Background; the Lightning R2D2 default in Event 3
starts at 45% to leave headroom for dense flash fields. OSC host and port can be overridden with
`GAIA_SCAPE_OSC_HOST` and `GAIA_SCAPE_OSC_PORT`; change `oscPort` in the
SuperCollider script when selecting another receive port.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,lightning,eumetsat]'
GAIA_SCAPE_DATA_DIR=$(mktemp -d) .venv/bin/python -m pytest -q
GAIA_SCAPE_DATA_DIR=/tmp/gaia-scape-dev .venv/bin/python Gaia_Scape.py
```

Runtime state consists of `config.json` and `gaia_scape.sqlite3` under the
installation's `data/` directory.

Architecture, normalized units, lifecycle ownership, and validation boundaries
are documented in [ARCHITECTURE.md](ARCHITECTURE.md).
For a minimal server install use `pip install .`; add `[lightning]` for NOAA,
`[eumetsat]` for MTG, or `[desktop]` for the native window. The supplied headless
installer includes both satellite extras. Stop pauses continuous playback while
capture and retention continue; Start resumes it.

Birdsong regions are editable when Xeno-canto is selected in Sound Sources.
Select a numbered point in Sound locations → Birdsong, then click the map or
edit its name and coordinates; save settings to apply. Restore defaults resets
only the selected catalog. Wikimedia Commons shows its curated locations as
read-only and retains its existing recordings. Xeno-canto keeps the actual
recording coordinates for playback and attribution, searches within 100 km of
the selected center, and never substitutes a recording from outside that region.
If the searched catalog has no suitable recordings, the app reports the region
and advances to the next saved point on the following rotation. Regional
catalogs are cached separately by coordinates; moving a point cannot reuse its
old region's catalog. Each search checks up to five pages per geographic box.
