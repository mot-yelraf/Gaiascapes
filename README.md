# Gaiascapes

Gaiascapes captures live terrestrial events and turns their time, location,
and intensity into generative soundscapes. The primary runtime is
Python on macOS, Linux, Raspberry Pi, or Windows 10/11. SuperCollider is the preferred audio
engine; capture, history, and the web interface continue to work when it is not
installed.

For illustrated operating instructions, settings, and credential setup, see the
[User Guide](USER_GUIDE.md). Installation instructions remain in this README.

Gaiascapes is intended for personal, educational, and other noncommercial use.
Birdsong and Frog Calls can include Xeno-canto recordings licensed
[CC BY-NC-SA](https://creativecommons.org/licenses/by-nc-sa/4.0/). Use those
recordings noncommercially, retain attribution and license links, identify
modifications, and apply the required ShareAlike license when sharing adaptations.
The existing recording attribution shows each recording's license and source.
The application code remains BSD-2-Clause licensed; third-party recordings retain
their own licenses. This statement of intended use does not change either license.

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
Wikimedia Commons recordings. Gaiascapes resolves files through the keyless Commons
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
CC BY, CC BY-SA, and CC BY-NC-SA licenses. The background status strip reports loading and
lookup failures, including regions without suitable recordings.
The default frog centers are checked using those same filters, with a sample
download from every region; see the [verification report](docs/frog-locations-audit.json).
Seven originally empty regions have been replaced. Existing installations migrate
unchanged default entries and the old automatically inserted **My location** entry
once, while preserving custom locations and avoiding duplicate coordinates.
Frog Calls no longer substitutes the host location automatically; add a local
frog region manually if desired. Catalog availability can change after verification.

To recheck all default frog regions, run this from the checkout with its Python
environment (catalogs and downloads use disposable temporary storage):

```bash
PYTHONPATH=src python scripts/audit_frog_locations.py \
  --config "$HOME/Gaiascapes/data/config.json" \
  --output /tmp/gaiascapes-frog-audit.json
```

The command reads only the API key from the configuration, writes a public report,
and exits unsuccessfully if any region has no eligible downloadable sample.

Birdsong, Frog Calls, Whale Song, and Dolphin Calls play each selected clip once
per location visit, without looping short clips. On the next full pass through
the locations, every recorded-sound provider selects the next available recording
for each location, wrapping after its last recording. Each catalog has 19 default
locations; a location with only one verified recording repeats it on each pass. These recordings play to the end instead of being cut off by the
23-second location interval. The browser requests the next location during the
final three seconds (or final 10% of short clips), fading between recordings.
First-use downloads can leave a gap. Keep the browser or desktop player open
to hear recordings. Failed loads and playback errors skip to the next selection;
30 seconds without playback progress also triggers recovery. Completion requests
time out after 10 seconds and retry while the player is current. The server
releases a recording after 90 seconds without progress, checked independently
every five seconds, so a disconnected player cannot hold rotation indefinitely.
Healthy long recordings keep their place by reporting progress. Confirmed decoding
failures cause one cache repair; a second failure quarantines that recording for
the rest of the session. Previews remain limited to eight seconds.

Whale Song and Dolphin Calls each have 19 verified default recording locations.
Whale Song includes natural-speed songs and calls from several whale species,
using NOAA NCEI / SanctSound. Dolphin Calls supplements NOAA with documented
Figshare, Zenodo, Commons, and Freesound recordings, including river dolphins
and a recording captured above water off Portugal. No API key is required.
Choose included sites in Sound locations; each site shows its recording count.
At least one site must remain selected. Map points identify documented recording
positions or explicitly approximate regions, not exact animal positions.

The whale catalog has 59 recordings and the dolphin catalog has 30. Most
recordings download on first use and are cached beneath `data/media/whale_song/`
and `data/media/dolphin_calls/`, with a 64 MiB per-file limit and pinned checksums.
Four short CC BY Xiamen dolphin whistles are bundled at their original speed,
resampled to 48 kHz to avoid a 129 MB archive download and support browser playback.
Each cue retains contributor credit, source, license, and available recording dates.
The application's license does not relicense archive audio; some Freesound and
Xeno-canto recordings are restricted to noncommercial use.

The Commons bird catalog contains 68 distinct recordings across 19 documented
regions, separate from the editable Xeno-canto regions. Every recording has an
identified bird and source coordinates. Two Commons regions currently have one
verified recording; the other 17 have multiple entries. Marine catalogs also
retain single-recording sites where additional suitable samples were not found.
The coverage and first two playback passes are recorded in
[`docs/recorded-catalogs-audit.json`](docs/recorded-catalogs-audit.json).
Run a fresh verification without changing installed runtime state:

```sh
PYTHONPATH=src python scripts/audit_recorded_catalogs.py --config /path/to/data/config.json --output /tmp/recorded-catalogs-audit.json
```

On upgrade, complete legacy marine defaults expand to the new 19-site catalogs;
custom site subsets are preserved. Restore defaults includes all 19 sites again.

The Birdsong tile in Sound Sources enables archived recordings and selects
Wikimedia Commons or Xeno-canto. For Xeno-canto, enter a personal API key there.
Select Birdsong as the Background in Instruments to control volume and preview it.
Disabling the Birdsong source stops playback while preserving the selected background. The key is stored in the local `data/config.json`
and is omitted from browser responses. The provider searches within 100 km of each of the 19 saved Birdsong locations for
A/B-quality CC BY, CC BY-SA, and CC BY-NC-SA recordings, skips missing or restricted coordinates, and
uses the recording's actual location on the map. These are archived recordings;
the playback event time is current, while the original date and time remain in
the event's `recorded_date` and `recorded_time` traits. Catalogs are cached for
24 hours and audio under `data/media/birdsong/xeno-canto/`; successive rotations
select further recordings from each country. Downloads are limited to 64 MiB
and recordings to 10–180 seconds. An unavailable country or provider reports an
error rather than substituting another source. See the
[Xeno-canto API documentation](https://xeno-canto.org/explore/api).

For Xeno-canto Birdsong locations whose names include **New Mexico** or **NM**,
including GeoIP's **My location** entry, Gaiascapes selects the state bird:
Richard E. Webster's [Greater Roadrunner song, XC254791](https://xeno-canto.org/254791),
recorded in Rodeo, Hidalgo County (1:14, quality B, CC BY-NC-SA 4.0).
This state-specific selection can be outside the usual 100 km search radius.
Playback retains the recording's actual coordinates and attribution. If the
recording becomes unavailable, the app reports that explicitly. Frog Calls and
other Birdsong regions continue to use their regional catalogs.
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
Gaiascapes API responses. Leave both fields blank on later saves to retain the
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
show their observed positions. Console log entries include the local date and time
(`YYYY-MM-DD HH:MM:SS`). The console reports each
dispatched sonification with its source, instrument,
channel, volume, duration, strength, and location. Lightning is grouped: each played
NOAA field reports granules, raw flashes, samples, inserts, and the number actually
sonified, with any safety reduction in the same line. Cached-field playback explains
that it is waiting for new granules. MTG and history replay groups report when
playback begins. Enabled sources and queued sounds alone do not produce playback
reports; capture counts remain available through `/api/status`.
Gaia also quarantines exceptionally dense tropical GOES-19 fields during NOAA's
documented 15:00–19:00 UTC false-alarm window, active since July 17, 2026.

### Network recovery

Gaiascapes keeps capture, history, the web interface, and available audio layers
running when an environmental provider becomes unavailable. Each source reports
an online, degraded, offline, or recovering state through `/api/status`. Failed
sources retry independently with bounded exponential backoff and jitter, so one
outage does not interrupt healthy feeds. Built-in capture operations have a
45-second process deadline; recording retrieval has a 60-second deadline. Timed-out
workers are terminated before retrying, so stuck network or native-library calls
cannot permanently occupy a provider. Standalone NetCDF decoding has a 20-second
process deadline.

Browser requests time out instead of leaving cue polling stuck. Device listening
reconnects synthesized audio with a delay capped at 30 seconds while recordings
remain available; Mute cancels reconnection. MTG timelines retry transient transport
failures up to three times per flash, within the existing lateness allowance,
without repeating successful voices or abandoning the remaining timeline.

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
result is cached in process memory. At startup it also replaces location 1 of
the 19 Sound locations for Xeno-canto Birdsong and Storm Outlook,
and those sampling centers are saved in `data/config.json`. The other 18 slots
remain unchanged unless one matches the host; that slot swaps with the previous
first entry to retain 19 distinct locations. Restore defaults also puts the
detected host first for those catalogs. Frog Calls retains its verified defaults
or manually edited regions. Commons Birdsong retains its curated recording locations.
If GeoIP is unavailable, saved locations remain in use. To disable lookups and
automatic location updates, clear **Show
this host’s approximate location on the map** in **Settings → Sound Choices**. System and SuperCollider prerequisites
are listed in `SYSTEM_REQUIREMENTS.md`. SuperCollider may be installed before
or after Gaiascapes.

On Windows 10/11 (64-bit), install Python 3.13 and the WebView2 Runtime, extract
the source ZIP, and double-click `install.cmd`. It creates a desktop shortcut
and a private installation in `%USERPROFILE%\Gaiascapes`. See
[Windows installation](WINDOWS_INSTALL.md) for custom paths, audio, and repairs.

On macOS:

```sh
./scripts/install_macos.sh
```

On Linux or Raspberry Pi OS:

```sh
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
./scripts/install_linux.sh
```

On macOS and Linux, the default installation and launch directory is `~/Gaiascapes`. The installer
presents a folder selector, remembers the chosen location,
creates a private `.venv`, installs a self-contained Python application, and
preserves the selected installation's `data/` directory during updates.
Run the shell launchers from the selected installation directory (by default,
`cd ~/Gaiascapes`). Direct Python and console launches default to
`~/Gaiascapes/data`; set `GAIA_SCAPE_DATA_DIR` for a custom runtime.

For a headless installation without pywebview or GTK/WebKit:

```sh
GAIA_SCAPE_INSTALL_MODE=headless GAIA_SCAPE_INSTALL_DIR="$HOME/Gaiascapes" ./install.sh
```

For an
unattended desktop installation:

```sh
GAIA_SCAPE_INSTALL_DIR="$HOME/Gaiascapes" ./install.sh
```

Set `GAIA_SCAPE_AUTO_START=yes` to install a user-level systemd service on
Linux/Raspberry Pi or a LaunchAgent on macOS.

Run `./uninstall.sh` from the installed directory to remove the application and
auto-start service while preserving captured data. To remove the data as well:

```sh
GAIA_SCAPE_REMOVE_DATA=yes ./uninstall.sh
```

The GUI launcher starts and supervises SuperCollider automatically, starts the
local web service when needed, and opens Gaiascapes in a native pywebview window:

```sh
./scripts/run_gaiascapes_gui.sh
```

Closing the window stops the web service started by that window. If a Gaiascapes
service is already listening on the configured port, the desktop app attaches to
it and leaves it running. Window size and position can be overridden with
`GAIA_SCAPE_GUI_WIDTH`, `GAIA_SCAPE_GUI_HEIGHT`, `GAIA_SCAPE_GUI_X`, and
`GAIA_SCAPE_GUI_Y`.

On macOS, the GUI creates a lightweight identity bundle at
`~/Library/Application Support/Gaia Scape/Gaiascapes.app` and relaunches through
it with the display name, bundle name, and executable name Gaiascapes. The support
directory retains its legacy name. Install the update and fully quit and reopen
the desktop app to refresh its Dock identity.
Set `GAIA_SCAPE_HEADLESS=1` to suppress this GUI-only relaunch when embedding the
desktop module in an unattended process.

By default, Gaiascapes follows the sound output selected in the operating
system each time it starts. To pin a particular audio output instead, write
its exact SuperCollider device name to `data/audio-device`. For example:

```sh
printf '%s\n' 'DELL S2725QC' > data/audio-device
```

Write `system` to that file to restore system-output following. On macOS,
`data/audio-device-map` may contain tab-separated system and SuperCollider
device names. This supports output-only Bluetooth aggregate devices without
pinning other system outputs.

For separate-process operation, run `./scripts/run_supercollider.sh` in one terminal
and `./scripts/run_gaiascapes_gui.sh` in another. You can override the remembered
device for one launch with `GAIA_SCAPE_AUDIO_DEVICE` or `--audio-device`.
Passing `GAIA_SCAPE_AUDIO_DEVICE` to the installer saves that selection in
the installed data directory.

For unattended operation, use `./scripts/run_gaiascapes.sh`. Open
`http://127.0.0.1:8768` locally or `http://<computer-ip>:8768` on the same LAN.

## OSC cue contract

Gaiascapes sends immediate UDP messages to `/gaia/cue` with these ordered
arguments:

```text
event_id, kind, instrument, pitch, velocity, duration, pan, strength,
longitude, latitude, raw_magnitude, depth_km, gain, output_channel
```

`gain` is a linear output multiplier calculated as `(slider / 100)²`, separate
from musical velocity. `output_channel` identifies `background`, `event_1`,
`event_2`, `event_3`, or an unassigned `preview`. `/gaia/volumes` carries four
linear gains in Background, Event 1, Event 2, Event 3 order, updating active synths
when settings are saved. Each channel is independent, including duplicate voices.
The receiver accepts older cues without these two trailing arguments at unity
gain. Update and restart both the host and SuperCollider for the new volume behavior;
older receivers ignore the new output-gain controls.

Continuous ocean or storm state uses the same arguments at `/gaia/layer`; repeated
messages smoothly update one persistent synth instead of replacing it. Storm
forecast strength controls rainfall density and intensity. `/gaia/layer/stop`
releases the synth when continuous mode stops or the background selection changes.
Birdsong uses the renderer-neutral emitted-cue stream and is played from Gaiascapes's
local media cache by the web view, so it does not require a SuperCollider sampler.

LAN browsers can choose **Listen on this device** in **Settings → Sound Choices**, to the left of Units to hear the
complete soundscape, or **Mute this device** to stop only their own playback.
Update and restart both Python and `supercollider/gaia-scape.scd` for this feature.
The receiver routes Gaiascapes through a private stereo bus and copies completed
512-frame blocks from an in-memory ring buffer over loopback OSC. Python relays
framed float PCM through `/api/audio/stream`; the browser mixes this with the
existing animal-recording playback. Other applications' audio is not captured.
No extra Python dependency, virtual audio driver, or on-disk audio cache is used
for synthesized audio. Browser playback uses Web Audio and works over LAN HTTP.

Capture starts on the first listener, stops after the last disconnects, and
expires in SuperCollider after six seconds without a relay heartbeat. Each
listener has a bounded queue; slow clients drop old audio rather than delaying
others. At 48 kHz the stream uses approximately 0.4 MB/s per listener, with a
maximum of 16 simultaneous listeners. SuperCollider must run on the web server's
host. If it is unavailable, the API reports a clear error and capture, history,
and the UI remain available. With OSC disabled, browsers can still listen to
animal recordings. Browser listening choices are never stored in installation
settings. See the [listening guide](USER_GUIDE.md#listening-from-another-device).

The included `supercollider/gaia-scape.scd` listens on UDP 57130 and provides
earthquake, seismic-bell, Lightning R2D2, Thunder, ocean-swell, tidal-bell, and Storm Outlook
voices. The
Settings menu selects capture sources, three independent event voices, and one continuous
background, including Birdsong Atlas. Each musical role can also be set to None. The persisted Units setting
displays swell and tide heights in meters or feet and earthquake depth in kilometers
or miles. The Dashboard or Map selection is also stored with the installation and
restored when Gaiascapes starts. Both views show three separate status tiles, side by side at the bottom on desktop
and stacked on mobile, with the
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
GAIA_SCAPE_DATA_DIR=/tmp/gaia-scape-dev .venv/bin/python Gaiascapes.py
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

## Naming transition

The Python distribution is now `gaiascapes`, with domain code in `gaiascapes`
and host code in `gaiascapes_host`. Use `gaiascapes-server`, `gaiascapes-gui`,
`python -m gaiascapes_host`, or the source launcher `Gaiascapes.py`. Python
imports using `gaia_scape` or `gaia_scape_host` must be updated.

The shell launchers are `scripts/run_gaiascapes.sh` and `scripts/run_gaiascapes_gui.sh`;
the source launcher is `Gaiascapes.py`. The source checkout remains at
`~/Projects/Gaiascapes`, and the default installation is `~/Gaiascapes`.
The repository is [mot-yelraf/Gaiascapes](https://github.com/mot-yelraf/Gaiascapes).

The transition preserves `GAIA_SCAPE_*` environment variables,
`gaia_scape.sqlite3`, browser storage keys, asset filenames, OS integration
identifiers. HTTP remains on 8768 and OSC on 57130.
Installed runtime state is not migrated by these source changes.

## Privacy and security

LAN access remains enabled by default on port 8768 so other devices can browse
and listen. Devices that can reach the app can also change its settings; there
is no login, and HTTP traffic is not encrypted. Use it on a trusted LAN and do
not expose it directly to the internet.

See [Privacy](PRIVACY.md) for outbound services and local data storage, and
[Security](SECURITY.md) for private vulnerability reporting.

To repair an installation, run its `install.sh`; it delegates to the recorded
source checkout and preserves the selected installation and install mode.
Keep that checkout available. If it has moved or is missing, run `install.sh`
from a current source checkout with `GAIA_SCAPE_INSTALL_DIR` set explicitly.
When moving an installation, recreate its `.venv` from the source checkout;
virtual environments contain absolute paths. Keep the `data/` folder.
