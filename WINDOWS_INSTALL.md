# Windows 10 / 11 installation

Use 64-bit Windows 10 or Windows 11. The installer runs under the built-in
Windows PowerShell 5.1 and installs for your user account without requiring
Git, WSL, Bash, or administrator access. Python 3.13 x64 is the recommended
interpreter; this is a script-based installation, not a bundled executable.

## Install

1. Install [Python 3.13 for Windows](https://www.python.org/downloads/windows/)
   using the **64-bit installer**, including pip and the Python launcher.
2. Ensure the [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
   is installed. It is included with Windows 11 and most Windows 10 systems.
   Having the Edge browser alone is not sufficient. The installer checks for
   the Runtime and gives a download link if it is missing.
3. Download the Gaiascapes source ZIP from GitHub and **extract the entire ZIP**.
   Keep this source folder for future updates and repairs.
4. Double-click **`install.cmd`** in the extracted folder. The default destination
   is `%USERPROFILE%\Gaiascapes`. Installation output is saved in `install.log`
   there, and errors remain visible in the console.
5. Open the **Gaiascapes** desktop shortcut. A console stays open while the app
   runs so startup and provider errors are visible. Close the app window to exit.

The installer creates a private `.venv`, includes the NOAA and EUMETSAT satellite
dependencies, and preserves `data\` during upgrades. It does not start the app,
change firewall rules, register a Windows service, or enable login autostart.
The CMD wrapper and shortcuts use `-ExecutionPolicy Bypass` only for their own
PowerShell process; they do not change your saved execution policy. Organization
policy may still require your administrator to approve the scripts.

For a custom folder, open PowerShell in the extracted source folder and run:

```powershell
.\install.cmd -InstallDir "D:\Applications\Gaiascapes"
```

To select an existing interpreter explicitly:

```powershell
.\install.cmd -Python "C:\Path\To\Python313\python.exe"
```

Python must be 64-bit and version 3.10 or newer. Use Python 3.13 if newer Python
versions encounter dependency wheel or .NET bridge compatibility errors.
For a desktop backend import failure, verify WebView2 and .NET Framework 4.8.

## Sound

Install the Windows package from [SuperCollider](https://supercollider.github.io/downloads).
Gaiascapes searches `PATH` and `C:\Program Files\SuperCollider*\sclang.exe`.
For a nonstandard location, set `GAIA_SCAPE_SCLANG` to the full path of
`sclang.exe` in your Windows user environment settings, then reopen Gaiascapes.

The desktop launcher starts SuperCollider automatically when it is available
and no receiver is listening on UDP 57130. Closing the desktop also stops the
renderer it started. An already-running renderer is left alone. Without
SuperCollider, event capture, history, and the UI still operate.

The **Gaiascapes Audio** shortcut starts the renderer separately, useful with
the browser UI. Close that audio console when finished. For a specific output
device, put its exact SuperCollider device name on the first line of
`data\audio-device`, or launch from the installation directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_gaiascapes.ps1 -Mode Desktop -AudioDevice "Windows WASAPI : Speakers (Your device)"
```

Use a name reported by SuperCollider on your computer; the example is not a
universal device name. See SuperCollider's
[Windows instructions](https://github.com/supercollider/supercollider/blob/develop/README_WINDOWS.md)
for device and driver troubleshooting.

## Browser-only operation

To skip pywebview and the WebView2 prerequisite:

```powershell
.\install.cmd -Mode Headless
```

The Gaiascapes shortcut then starts the server in a console. Open
**http://127.0.0.1:8768** in your browser and use Ctrl+C to stop the server.
You can also start it from the installation directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_gaiascapes.ps1 -Mode Server
```

The default HTTP port is **8768**; SuperCollider receives OSC on **57130** and
uses **57131** for its language port. For access from other computers, allow
TCP 8768 on your private network in Windows Firewall. OSC stays local.

## Update, repair, and removal

Close Gaiascapes and update the source folder, then run `install.cmd` again
with the same destination. Alternatively, run the installed `install.cmd`;
it uses `data\install-source` and `data\install-mode` to preserve the destination
and mode. If the source folder moved, run the new source's installer with
`-InstallDir` pointing to the existing installation. Recreate the environment
when moving an installation; virtual environments are not portable.

To remove Gaiascapes, close its app and audio consoles, back up `data\`, delete
the two desktop shortcuts, then remove the dedicated installation folder.
Python, WebView2, and SuperCollider are separate installations and remain installed.

## Validation scope

Windows CI exercises PowerShell 5.1 installation, paths containing spaces,
shortcut targets, repair with data preservation, desktop dependency imports,
and the installed offline web API. A real Windows 10/11 desktop and audio device
are still needed to verify native window interaction and audible playback.

Prerequisite references:
[Python on Windows](https://docs.python.org/3.13/using/windows.html),
[WebView2 distribution](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution),
[pywebview engines](https://pywebview.flowrl.com/guide/web_engine).
