# System requirements

Gaiascapes supports macOS, Linux, and Raspberry Pi OS.

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

The browser-accessible web UI and headless service continue to work without
these desktop-window packages. Use `GAIA_SCAPE_INSTALL_MODE=headless ./install.sh`
to skip their installation checks. A minimal `pip install .` also omits satellite
decoders; `[lightning]` adds NetCDF and `[eumetsat]` adds EUMDAC. The supplied
headless installer includes both satellite extras.

## Audio

SuperCollider is required for sound output but not for capture, history, or the web UI.

- macOS: install the SuperCollider application in `/Applications`.
- Debian, Ubuntu, or Raspberry Pi OS: install the `supercollider` package.

On macOS with Homebrew, a typical installation is:

```sh
brew install --cask supercollider
```

On Debian-family systems:

```sh
sudo apt update
sudo apt install python3 python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 supercollider
```

`install.sh` verifies Python and reports whether SuperCollider was detected.

## Network

The supplied launchers default to `0.0.0.0`, making the web UI available on the LAN.
Browse to `http://<gaia-host-ip>:8768` from another computer on the same network.

Port 8768/TCP must be allowed by the host firewall. OSC remains local on UDP 57130.
