"""Launch Gaia Scape in a native pywebview desktop window.

Desktop startup reuses or supervises the local web server and applies
platform-specific application identity and icon behavior where available.
"""

from __future__ import annotations

import ctypes
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import AppConfig, resolve_data_dir


STATIC_DIR = Path(__file__).resolve().parent / "static"
DESKTOP_ICON_PATH = STATIC_DIR / "gaia-scape-desktop-icon.png"
WINDOWS_ICON_PATH = STATIC_DIR / "gaia-scape-desktop-icon.ico"
MACOS_ICON_PATH = STATIC_DIR / "gaia-scape-desktop-icon.icns"
LINUX_APP_ID = "earth.gaia_scape.GaiaScape"
MACOS_APP_NAME = "Gaia Scape"
MACOS_BUNDLE_IDENTIFIER = "earth.gaiascape.GaiaScape"
MACOS_RELAUNCH_MARKER = "GAIA_SCAPE_MACOS_APP_RELAUNCHED"
MACOS_HEADLESS_MARKER = "GAIA_SCAPE_HEADLESS"
DEFAULT_WINDOW_WIDTH = 1500
DEFAULT_WINDOW_HEIGHT = 960
DEFAULT_MIN_WIDTH = 960
DEFAULT_MIN_HEIGHT = 640

_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_windows_icon: Any = None


def _macos_application_support_dir() -> Path:
    """Return the per-user directory containing macOS integration metadata."""
    return Path.home() / "Library" / "Application Support" / MACOS_APP_NAME


def _path_is_in_app_bundle(path: Path) -> bool:
    """Return whether a lexical path is inside a macOS application bundle."""
    return any(parent.suffix.lower() == ".app" for parent in path.parents)


def _should_relaunch_for_macos_identity() -> bool:
    """Return whether this desktop process needs a macOS bundle identity."""
    if sys.platform != "darwin":
        return False
    if os.environ.get(MACOS_RELAUNCH_MARKER):
        return False
    if os.environ.get(MACOS_HEADLESS_MARKER):
        return False
    if getattr(sys, "frozen", False):
        return False
    return not _path_is_in_app_bundle(Path(sys.executable))


def _ensure_macos_app_bundle() -> Path:
    """Create or repair the lightweight bundle used for macOS process identity."""
    bundle_path = _macos_application_support_dir() / f"{MACOS_APP_NAME}.app"
    contents_path = bundle_path / "Contents"
    executable_dir = contents_path / "MacOS"
    resources_dir = contents_path / "Resources"
    executable_path = executable_dir / MACOS_APP_NAME
    info_path = contents_path / "Info.plist"

    executable_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    icon_name = MACOS_ICON_PATH.name
    icon_path = resources_dir / icon_name
    if (
        not icon_path.is_file()
        or icon_path.read_bytes() != MACOS_ICON_PATH.read_bytes()
    ):
        temporary_icon = icon_path.with_name(f".{icon_name}.{os.getpid()}.tmp")
        shutil.copyfile(MACOS_ICON_PATH, temporary_icon)
        temporary_icon.replace(icon_path)

    document = {
        "CFBundleDisplayName": MACOS_APP_NAME,
        "CFBundleName": MACOS_APP_NAME,
        "CFBundleExecutable": MACOS_APP_NAME,
        "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
        "CFBundleIconFile": icon_name,
        "CFBundlePackageType": "APPL",
    }
    plist_data = plistlib.dumps(document, sort_keys=True)
    if not info_path.is_file() or info_path.read_bytes() != plist_data:
        temporary_info = info_path.with_name(f".Info.plist.{os.getpid()}.tmp")
        temporary_info.write_bytes(plist_data)
        temporary_info.replace(info_path)

    python_path = Path(sys.executable)
    if not python_path.is_absolute():
        python_path = Path.cwd() / python_path
    target = str(python_path)
    if not executable_path.is_symlink() or os.readlink(executable_path) != target:
        temporary_executable = executable_path.with_name(
            f".{MACOS_APP_NAME}.{os.getpid()}.tmp"
        )
        temporary_executable.unlink(missing_ok=True)
        temporary_executable.symlink_to(target)
        temporary_executable.replace(executable_path)
    return executable_path


def relaunch_for_macos_app_identity() -> bool:
    """Replace this process with one launched through the Gaia Scape bundle."""
    if not _should_relaunch_for_macos_identity():
        return False
    try:
        executable_path = _ensure_macos_app_bundle()
        environment = os.environ.copy()
        environment[MACOS_RELAUNCH_MARKER] = "1"
        package_root = str(Path(__file__).resolve().parents[1])
        python_paths = [
            item
            for item in environment.get("PYTHONPATH", "").split(os.pathsep)
            if item
        ]
        if package_root not in python_paths:
            python_paths.insert(0, package_root)
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        arguments = [
            str(executable_path),
            "-m",
            "gaia_scape_host.desktop",
            *sys.argv[1:],
        ]
        os.execve(str(executable_path), arguments, environment)
    except OSError as exc:
        print(
            f"Gaia Scape could not establish its macOS application identity: {exc}",
            file=sys.stderr,
        )
        return False
    return True


def _base_url() -> str:
    configured = os.environ.get("GAIA_SCAPE_GUI_URL")
    if configured:
        return configured.rstrip("/") + "/"
    config = AppConfig.load(resolve_data_dir() / "config.json")
    return f"http://127.0.0.1:{config.http_port}/"


def _int_env(name: str, default: int | None) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _available_screen_size() -> tuple[int, int] | None:
    """Return the primary display size when the platform exposes it."""
    try:
        if sys.platform == "darwin":
            from AppKit import NSScreen

            screen = NSScreen.mainScreen()
            if screen is not None:
                size = screen.visibleFrame().size
                return int(size.width), int(size.height)
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        if sys.platform.startswith("linux"):
            import gi

            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk

            display = Gdk.Display.get_default()
            if display is not None:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor is not None:
                    area = monitor.get_workarea()
                    return int(area.width), int(area.height)
    except Exception:
        pass
    return None


def _window_geometry() -> dict[str, int | None]:
    width = max(
        640, _int_env("GAIA_SCAPE_GUI_WIDTH", DEFAULT_WINDOW_WIDTH) or DEFAULT_WINDOW_WIDTH
    )
    height = max(
        480,
        _int_env("GAIA_SCAPE_GUI_HEIGHT", DEFAULT_WINDOW_HEIGHT)
        or DEFAULT_WINDOW_HEIGHT,
    )
    if screen_size := _available_screen_size():
        width = min(width, screen_size[0])
        height = min(height, screen_size[1])
    return {
        "width": width,
        "height": height,
        "x": _int_env("GAIA_SCAPE_GUI_X", None),
        "y": _int_env("GAIA_SCAPE_GUI_Y", None),
    }


def _is_healthy(base_url: str, timeout: float = 1.0) -> bool:
    try:
        with _direct_opener.open(
            base_url.rstrip("/") + "/healthz", timeout=timeout
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_health(base_url: str, process: subprocess.Popen[Any] | None) -> bool:
    retries = max(1, _int_env("GAIA_SCAPE_GUI_RETRIES", 120) or 120)
    delay = max(0.0, _float_env("GAIA_SCAPE_GUI_RETRY_DELAY", 0.25))
    for _ in range(retries):
        if _is_healthy(base_url):
            return True
        if process is not None and process.poll() is not None:
            return False
        time.sleep(delay)
    return False


def _start_server() -> subprocess.Popen[Any]:
    """Start the web server with this interpreter and installation."""
    return subprocess.Popen(
        [sys.executable, "-m", "gaia_scape_host"],
        cwd=resolve_data_dir().parent,
        env=os.environ.copy(),
    )


def _stop_owned_server(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _desktop_exec_arg(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def configure_linux_app_identity() -> Path | None:
    """Install the per-user Linux desktop identity used by GTK and Wayland."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        from gi.repository import GLib

        GLib.set_prgname(LINUX_APP_ID)
        GLib.set_application_name("Gaia Scape")
    except Exception as exc:
        print(f"Gaia Scape could not set its Linux application ID: {exc}", file=sys.stderr)

    data_root = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ).expanduser()
    applications_dir = data_root / "applications"
    icons_dir = data_root / "icons" / "hicolor" / "512x512" / "apps"
    desktop_path = applications_dir / f"{LINUX_APP_ID}.desktop"
    themed_icon_path = icons_dir / f"{LINUX_APP_ID}.png"
    runtime_dir = resolve_data_dir().parent
    launcher_path = runtime_dir / "run_gaia_scape_gui.sh"
    desktop_text = "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=Gaia Scape",
            "Comment=Open the Gaia Scape living Earth soundscape",
            f"Exec={_desktop_exec_arg(str(launcher_path))}",
            f"Path={runtime_dir}",
            f"Icon={LINUX_APP_ID}",
            "Terminal=false",
            "StartupNotify=true",
            f"StartupWMClass={LINUX_APP_ID}",
            "",
        )
    )
    try:
        applications_dir.mkdir(parents=True, exist_ok=True)
        icons_dir.mkdir(parents=True, exist_ok=True)
        if (
            not themed_icon_path.is_file()
            or themed_icon_path.read_bytes() != DESKTOP_ICON_PATH.read_bytes()
        ):
            temporary_icon = themed_icon_path.with_suffix(".png.tmp")
            shutil.copyfile(DESKTOP_ICON_PATH, temporary_icon)
            temporary_icon.replace(themed_icon_path)
        if not desktop_path.is_file() or desktop_path.read_text(encoding="utf-8") != desktop_text:
            temporary_desktop = desktop_path.with_suffix(".desktop.tmp")
            temporary_desktop.write_text(desktop_text, encoding="utf-8")
            temporary_desktop.replace(desktop_path)
    except OSError as exc:
        print(f"Gaia Scape could not install its Linux desktop entry: {exc}", file=sys.stderr)
        return None
    return desktop_path


def set_macos_app_icon() -> None:
    """Set the running Cocoa application's Dock and app-switcher icon."""
    if not DESKTOP_ICON_PATH.is_file():
        return
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper

        def apply_icon() -> None:
            """Apply the packaged icon on the Cocoa application thread."""
            icon = NSImage.alloc().initWithContentsOfFile_(str(DESKTOP_ICON_PATH))
            if icon is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(icon)

        AppHelper.callAfter(apply_icon)
    except Exception as exc:
        print(f"Gaia Scape could not set its macOS app icon: {exc}", file=sys.stderr)


def set_windows_app_icon(window: Any) -> None:
    """Set the WinForms window and taskbar icon after native creation."""
    global _windows_icon
    if not WINDOWS_ICON_PATH.is_file() or window.native is None:
        return
    try:
        from System.Drawing import Icon

        _windows_icon = Icon(str(WINDOWS_ICON_PATH))
        window.native.Icon = _windows_icon
    except Exception as exc:
        print(f"Gaia Scape could not set its Windows app icon: {exc}", file=sys.stderr)


def main() -> int:
    """Start or attach to Gaia Scape and display its native desktop window."""
    if relaunch_for_macos_app_identity():
        return 0
    base_url = _base_url()
    owned_server: subprocess.Popen[Any] | None = None
    os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

    if sys.platform.startswith("linux"):
        os.environ.setdefault("GDK_BACKEND", "wayland,x11")
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            print(
                "Gaia Scape GUI not started: no DISPLAY or WAYLAND_DISPLAY is set.",
                file=sys.stderr,
            )
            return 1
        configure_linux_app_identity()

    try:
        import webview
    except Exception as exc:
        print(
            f"Gaia Scape GUI not started: pywebview import failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if not _is_healthy(base_url):
        if os.environ.get("GAIA_SCAPE_GUI_URL"):
            print(
                f"Gaia Scape GUI not started: {base_url.rstrip('/')} is not ready.",
                file=sys.stderr,
            )
            return 1
        try:
            owned_server = _start_server()
        except OSError as exc:
            print(f"Gaia Scape GUI could not start its server: {exc}", file=sys.stderr)
            return 1

    if not _wait_for_health(base_url, owned_server):
        _stop_owned_server(owned_server)
        print(
            f"Gaia Scape GUI not started: {base_url.rstrip('/')} did not become ready.",
            file=sys.stderr,
        )
        return 1

    try:
        geometry = _window_geometry()
        window = webview.create_window(
            "Gaia Scape · Living Earth",
            base_url,
            width=geometry["width"],
            height=geometry["height"],
            x=geometry["x"],
            y=geometry["y"],
            min_size=(
                min(DEFAULT_MIN_WIDTH, int(geometry["width"])),
                min(DEFAULT_MIN_HEIGHT, int(geometry["height"])),
            ),
            resizable=True,
            frameless=False,
            confirm_close=True,
        )
        if sys.platform == "darwin":
            window.events.shown += set_macos_app_icon
            webview.start()
        elif sys.platform == "win32":
            window.events.shown += lambda: set_windows_app_icon(window)
            webview.start()
        elif sys.platform.startswith("linux"):
            webview.start(gui="gtk", icon=str(DESKTOP_ICON_PATH))
        else:
            webview.start()
    finally:
        _stop_owned_server(owned_server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
