# Gaiascapes installer apps

Native installer outputs and their SHA-256 manifests are written here. Generated
binaries, download caches, and build folders are ignored by Git. Build recipes
live in `packaging/`; build with `python scripts/build_installers.py`.

## Installing

- **macOS:** open the `.dmg` and drag **Gaiascapes.app** to Applications, or
  run the `.pkg`. These are alternative installers for the same app. Open
  Gaiascapes from Applications. No separate Python or Homebrew is needed.
- **Debian/Ubuntu/Raspberry Pi OS:** open the `.deb` with the distribution's
  package installer, or run `sudo apt install ./Gaiascapes-*.deb`. Use the package
  matching the machine's architecture. ARM64 is for 64-bit Raspberry Pi OS.
  The package manager installs GTK/WebKit and SuperCollider/audio prerequisites.
  No separate Python installation is required. Run Gaiascapes from the app menu.
- **Windows 10/11 x64:** run the setup `.exe`. It installs for the current user,
  adds Start Menu shortcuts, and offers a desktop shortcut. Setup installs
  Microsoft's WebView2 Runtime if missing. .NET Framework 4.8 must be available
  through Windows Update. No separate Python installation is required.

macOS and Windows builds include a private SuperCollider 3.14.1 renderer and its
matching upstream source archive. Linux uses system audio packages. Speech
announcements remain optional: eSpeak NG or the macOS Say quark may be installed
separately. Build option `--without-audio` deliberately omits private SuperCollider.

## macOS unidentified developer approval

These installers are ad-hoc signed for local execution, without a paid Apple
Developer ID or notarization. macOS may block a downloaded app or package on
first opening. Attempt to open it, then choose **System Settings → Privacy &
Security → Open Anyway** and confirm the app/installer. The `.pkg` may require
an administrator password to install into Applications. Organization-managed Macs
may restrict this approval. This does not require disabling Gatekeeper globally.

Apple's instructions: https://support.apple.com/en-us/102445

## Data, internet, and documentation

Internet access is required for live data feeds and first-use media downloads.
Bundled applications use their included CA certificates for verified HTTPS;
explicit `SSL_CERT_FILE` or `SSL_CERT_DIR` settings retain a custom trust store.
On desktop launch, missing Commons Birdsong recordings download in the
background; later launches retry incomplete downloads. Some sources require
personal API credentials. The startup log reports download and audio errors.

User state is stored under `~/Gaiascapes/data` (Windows:
`%USERPROFILE%\Gaiascapes\data`) unless `GAIA_SCAPE_DATA_DIR` selects another
installation's `data/` directory. Application updates and normal uninstallation
preserve that directory. Existing settings take precedence over new defaults.
Close Gaiascapes before updating. Upgrades do not depend on a source checkout.

Default HTTP port: **8769**. Local SuperCollider OSC port: **57130**.
Desktop diagnostics: `data/desktop.log`.

Every installer includes **user_guide.pdf**:

- macOS: in the disk image and inside the app's
  `Contents/Resources/gaiascapes_host/installation/` folder.
- Linux/Pi: `/usr/share/doc/gaiascapes/user_guide.pdf`.
- Windows: in the installation folder, with a Start Menu shortcut.

The executable also accepts `--user-guide`. The console helper
`gaiascapes-runtime` (`gaiascapes-runtime.exe` on Windows) accepts `--server`
for browser-only operation and `--install-media` to populate/repair Commons
Birdsong. On macOS the helper is inside `Gaiascapes.app/Contents/MacOS`;
on Linux it is `/opt/gaiascapes/gaiascapes-runtime`.

## Building

Build on each target OS/CPU; PyInstaller is not a cross compiler. Build-time
Python must be 3.11 or newer. Use a dedicated environment:

```sh
python3 -m venv /tmp/gaiascapes-build
/tmp/gaiascapes-build/bin/python -m pip install -r packaging/requirements-build.txt '.[desktop,lightning,eumetsat]'
/tmp/gaiascapes-build/bin/python scripts/build_installers.py
```

On Windows use a dedicated venv with its `Scripts\python.exe`, and install
**Inno Setup 6**. On Linux use Debian 12/bookworm's system Python with
`python3 -m venv --system-site-packages ...` after installing `python3-gi`,
GTK 3, and WebKitGTK 4.1 development/runtime packages. This includes the GTK
bindings in the bundle without requiring Python on the destination machine.

The manual **Build installer apps** GitHub Actions workflow builds macOS ARM64
and Intel, Windows x64, Linux amd64, and Linux ARM64/Pi installers. Linux is built
on Debian 12 to target glibc 2.36 or newer; 32-bit Pi OS and non-Debian Linux
distributions are not currently packaged. CI artifacts can be downloaded into
this directory with `gh run download RUN_ID --dir installers`.

Each build smoke-tests the actual frozen console helper with temporary data,
a real native NetCDF decode in a worker subprocess, offline HTTP routes, web
assets, and the included PDF. Native desktop interaction, audible output, and
the OS installation/upgrade UI still require checks on the target machines.
Build manifests identify the build OS, Python, architecture, and installer hashes.
Building on a newer macOS can raise the minimum supported macOS version.

Downloads of SuperCollider binaries and source are pinned by SHA-256 in
`packaging/audio.py`. Windows WebView2's current Microsoft bootstrapper is
checked for a valid Microsoft Authenticode signature. Python dependency
versions actually bundled are recorded by the retained distribution metadata.

To check only the frozen app, use `--bundle-only`. Build work folders are retained
for inspection. Run `python scripts/smoke_bundle.py /path/to/Gaiascapes.app` (or
the frozen application folder on Windows/Linux) to repeat the offline check.
