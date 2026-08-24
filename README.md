# Gaia Rhythms

Gaia Rhythms captures live terrestrial events and turns their time, location,
and intensity into generative musical performances. The primary runtime is
Python on macOS, Linux, or Raspberry Pi. SuperCollider is the preferred audio
engine; capture, history, and the web interface continue to work when it is not
installed.

The first source is the USGS all-day earthquake feed. Events are normalized,
deduplicated in SQLite, and retained locally. The Live Events tile offers two modes:
Capture replays a selected history window, while Continuous sounds newly captured
earthquakes immediately and rotates ambient data globally. The selected ocean-swell
or storm-rain background remains continuous while earthquake and tide event voices
play over it.
Continuous mode does not derive ocean sound from the listener’s location. Ambient
cues play at 75% of their mapped level so full-level earthquake cues remain distinct.

Optional Open-Meteo sources add:

- modeled swell conditions at twelve global surf locations;
- modeled high and low tide turns when a local sea-level extremum is present;
- global forecast storm potential derived from CAPE and thunderstorm weather codes.

Storm potential is not an observed lightning-strike feed. Marine values are
model output and are not suitable for navigation. Open-Meteo marine data
combines models from DWD, ECMWF, Météo-France, NOAA, and other contributing
agencies; source attribution is shown in Settings.

## Ports

- HTTP: `8768` (`GAIA_RHYTHMS_HTTP_PORT`)
- OSC UDP: `57130` (`GAIA_RHYTHMS_OSC_PORT`)

The supplied launchers bind to `0.0.0.0` for private-LAN access by default. Browse
to `http://<gaia-host-ip>:8768` from another computer. Set
`GAIA_RHYTHMS_HTTP_HOST=127.0.0.1` for access from this computer only.

## Installation

Python 3.10 or newer and internet access are required during installation.
Python packages are declared in `pyproject.toml` and mirrored in `requirements.txt`.
Astral 3.2 is included for location-aware solar and lunar calculations. System and
SuperCollider prerequisites are listed in `SYSTEM_REQUIREMENTS.md`. SuperCollider
may be installed before or after Gaia Rhythms.

On macOS:

```sh
./scripts/install_macos.sh
```

On Linux or Raspberry Pi OS:

```sh
sudo apt install python3 python3-venv
./scripts/install_linux.sh
```

The installer presents a folder selector, remembers the chosen location,
creates a private `.venv`, installs a self-contained Python application, and
preserves the selected installation's `data/` directory during updates. For an
unattended installation:

```sh
GAIA_RHYTHMS_INSTALL_DIR=/absolute/path/Gaia_Rhythms ./install.sh
```

Set `GAIA_RHYTHMS_AUTO_START=yes` to install a user-level systemd service on
Linux/Raspberry Pi or a LaunchAgent on macOS.

Run `./uninstall.sh` from the installed directory to remove the application and
auto-start service while preserving captured data. To remove the data as well:

```sh
GAIA_RHYTHMS_REMOVE_DATA=yes ./uninstall.sh
```

The GUI launcher starts and supervises SuperCollider automatically:

```sh
./run_gaia_rhythms_gui.sh
```

To select and remember a particular audio output, write its exact
SuperCollider device name to `data/audio-device`. For example:

```sh
printf '%s\n' 'DELL S2725QC' > data/audio-device
```

For separate-process operation, run `./run_supercollider.sh` in one terminal
and `./run_gaia_rhythms_gui.sh` in another. You can override the remembered
device for one launch with `GAIA_RHYTHMS_AUDIO_DEVICE` or `--audio-device`.
Passing `GAIA_RHYTHMS_AUDIO_DEVICE` to the installer saves that selection in
the installed data directory.

For unattended operation, use `./run_gaia_rhythms.sh`. Open
`http://127.0.0.1:8768` locally or `http://<computer-ip>:8768` on the same LAN.

## OSC cue contract

Gaia Rhythms sends immediate UDP messages to `/gaia/cue` with these ordered
arguments:

```text
event_id, kind, instrument, pitch, velocity, duration, pan, strength,
longitude, latitude, raw_magnitude, depth_km
```

Continuous ocean or storm state uses the same arguments at `/gaia/layer`; repeated
messages smoothly update one persistent synth instead of replacing it. Storm
forecast strength controls rainfall density and intensity. `/gaia/layer/stop`
releases the synth when continuous mode stops or the background selection changes.

The included `supercollider/gaia-rhythms.scd` listens on UDP 57130 and provides
earthquake, seismic-bell, ocean-swell, tidal-bell, and storm-rain voices. The
Settings menu selects capture sources, two event voices, and one continuous
background. Each musical role can also be set to None. OSC host and port can be overridden with
`GAIA_RHYTHMS_OSC_HOST` and `GAIA_RHYTHMS_OSC_PORT`; change `oscPort` in the
SuperCollider script when selecting another receive port.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
GAIA_RHYTHMS_DATA_DIR=/tmp/gaia-rhythms-dev .venv/bin/python Gaia_Rhythms.py
```

Runtime state consists of `config.json` and `gaia_rhythms.sqlite3` under the
installation's `data/` directory.
