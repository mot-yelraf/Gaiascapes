# System requirements

Gaiascapes provides installers for macOS, Linux, Raspberry Pi OS, and 64-bit
Windows 10/11. See [Windows installation](WINDOWS_INSTALL.md) for setup and
the current validation scope.

## Required

- Python 3.10 or newer, including `venv` and `pip` support.
- Internet access during installation and for environmental data feeds.

## Desktop window

The native desktop launcher uses pywebview. macOS supplies its web view through
the operating system. On Debian, Ubuntu, and Raspberry Pi OS, install the GTK 3
and WebKitGTK bindings:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

Windows uses the Microsoft Edge WebView2 Evergreen Runtime and .NET Framework
4.8. Python 3.13 x64 is recommended. `install.cmd` checks the Runtime before
installing desktop dependencies; `install.cmd -Mode Headless` skips this
requirement and provides the browser UI instead.

The browser-accessible web UI and headless service continue to work without
these desktop-window packages. Use `GAIA_SCAPE_INSTALL_MODE=headless ./install.sh`
to skip their installation checks. A minimal `pip install .` also omits satellite
decoders; `[lightning]` adds NetCDF and `[eumetsat]` adds EUMDAC. The supplied
headless installer includes both satellite extras.

## Audio

SuperCollider is required for synthesized audio rendering, but not for capture,
history, the web UI, or browser playback of animal recordings. The macOS Say
quark needs SuperCollider; eSpeak NG can provide announcements independently.

- macOS: install the SuperCollider application in `/Applications`.
- Debian, Ubuntu, or Raspberry Pi OS: install the `supercollider` package.
- Windows: install the Windows SuperCollider package in its standard
  `Program Files` location, or set `GAIA_SCAPE_SCLANG` to `sclang.exe`.

On macOS with Homebrew, a typical installation is:

```sh
brew install --cask supercollider
```

On Debian-family systems:

```sh
sudo apt update
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 supercollider
```

On macOS, `install.sh` (also invoked by `scripts/install_macos.sh`) checks Python
before changing the installation. If it is missing or older than 3.10, the
installer offers `brew install python@3.13` in an interactive Terminal. Accepting
uses that Homebrew interpreter for the rest of installation, even if an older
`python3` remains first on PATH. Declining, a Homebrew failure, or an unusable
interpreter stops installation with manual setup instructions; all host features
require supported Python.

The installer also offers `brew install --cask supercollider` when `sclang` is
absent from PATH, `/Applications`, and `~/Applications`. Declining or failing this
optional step continues installation with the functionality described above.
Homebrew itself is never installed automatically. If it is unavailable, follow
[Homebrew's installation instructions](https://brew.sh), or obtain compatible
installers directly from [Python](https://www.python.org/downloads/macos/) and
[SuperCollider](https://supercollider.github.io/downloads). Noninteractive runs
do not install dependencies automatically; rerun in Terminal to accept offers.

The Homebrew packages used are [Python 3.13](https://formulae.brew.sh/formula/python@3.13)
and [SuperCollider](https://formulae.brew.sh/cask/supercollider). Their platform
requirements may be newer than Gaiascapes' Python minimum; check compatibility
with your macOS when installing manually or resolving Homebrew failures.

## Network

The supplied launchers default to `0.0.0.0`, making the web UI available on the LAN.
Browse to `http://<gaia-host-ip>:8768` from another computer on the same network.

Port 8768/TCP must be allowed by the host firewall. OSC remains local on UDP 57130.
