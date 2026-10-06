"""Install per-user click-to-launch icons independently of auto-start.

The installer supplies its selected runtime explicitly. Creating icons never
starts Gaiascapes, initializes GTK, or loads or writes runtime configuration.
The existing Windows installer provides its own native desktop shortcuts.
"""

import argparse
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import sys

from .desktop import (
    LINUX_APP_ID, MACOS_ICON_PATH, _desktop_exec_arg, _macos_bundle_version,
    write_linux_app_launcher,
)

MACOS_LAUNCHER_ID = "earth.gaiascape.GaiaScape.launcher"


def write_macos_app_launcher(runtime_dir: Path) -> Path:
    """Create a Finder-launchable app pointing to the installed GUI launcher."""
    bundle = Path.home() / "Applications" / "Gaiascapes.app"
    info = bundle / "Contents" / "Info.plist"
    if bundle.exists():
        if not info.is_file() or plistlib.loads(info.read_bytes()).get(
            "CFBundleIdentifier"
        ) != MACOS_LAUNCHER_ID:
            raise FileExistsError(f"Refusing to overwrite another application: {bundle}")
    executable_dir = bundle / "Contents" / "MacOS"
    resources = bundle / "Contents" / "Resources"
    executable_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    version = _macos_bundle_version()
    document = {
        "CFBundleDisplayName": "Gaiascapes",
        "CFBundleName": "Gaiascapes",
        "CFBundleExecutable": "Gaiascapes",
        "CFBundleIdentifier": MACOS_LAUNCHER_ID,
        "CFBundleIconFile": MACOS_ICON_PATH.stem,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "GaiascapesInstallDirectory": str(runtime_dir),
    }
    info.write_bytes(plistlib.dumps(document))
    shutil.copyfile(MACOS_ICON_PATH, resources / MACOS_ICON_PATH.name)
    executable = executable_dir / "Gaiascapes"
    # Only the installation path is embedded, never the installer's environment.
    executable.write_text(
        "#!/bin/bash\n"
        f"runtime_dir={shlex.quote(str(runtime_dir))}\n"
        'log_file="$runtime_dir/data/desktop-launch.log"\n'
        'if "$runtime_dir/scripts/run_gaiascapes_gui.sh" "$@" >>"$log_file" 2>&1; then\n'
        '  exit 0\n'
        'fi\n'
        '/usr/bin/osascript - "$log_file" <<\'APPLESCRIPT\'\n'
        'on run argv\n'
        '  display alert "Gaiascapes could not start" message '
        '("Run the installer again to repair the application. Details: " & item 1 of argv) as critical\n'
        'end run\n'
        'APPLESCRIPT\n'
        'exit 1\n', encoding="utf-8",
    )
    executable.chmod(0o755)
    return bundle


def remove_launch_icon(runtime_dir: Path) -> None:
    """Remove only the launch icon associated with this installation."""
    if sys.platform == "darwin":
        bundle = Path.home() / "Applications" / "Gaiascapes.app"
        info = bundle / "Contents" / "Info.plist"
        if info.is_file():
            document = plistlib.loads(info.read_bytes())
            if (document.get("CFBundleIdentifier") == MACOS_LAUNCHER_ID
                    and document.get("GaiascapesInstallDirectory") == str(runtime_dir)):
                shutil.rmtree(bundle)
    elif sys.platform.startswith("linux"):
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser()
        entry = root / "applications" / f"{LINUX_APP_ID}.desktop"
        expected = f"Exec={_desktop_exec_arg(str(runtime_dir / 'scripts/run_gaiascapes_gui.sh'))}"
        if entry.is_file() and expected in entry.read_text(encoding="utf-8").splitlines():
            entry.unlink()
            (root / "icons/hicolor/512x512/apps" / f"{LINUX_APP_ID}.png").unlink(missing_ok=True)


def main() -> int:
    """Install or remove the selected installation's native launch icon."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    runtime_dir = args.runtime_dir.resolve()
    try:
        if args.remove:
            remove_launch_icon(runtime_dir)
        else:
            launcher = runtime_dir / "scripts/run_gaiascapes_gui.sh"
            if not launcher.is_file():
                raise FileNotFoundError(f"Installed GUI launcher is missing: {launcher}")
            if sys.platform == "darwin":
                path = write_macos_app_launcher(runtime_dir)
            elif sys.platform.startswith("linux"):
                path = write_linux_app_launcher(runtime_dir)
                if path is None:
                    return 1
            else:
                parser.error("Launch icons are provided by the Windows installer on Windows.")
            print(f"Click-to-launch icon: {path}")
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        print(f"Gaiascapes launch icon could not be updated: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
