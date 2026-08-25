"""Tests for command-line and native desktop launch behavior.

The suite verifies quiet server startup, packaged icons, process ownership,
health probing, and platform-specific desktop integration.
"""

import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import struct
import zlib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from gaia_scape_host import __main__ as cli
from gaia_scape_host import desktop


def test_cli_disables_uvicorn_access_log(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))

    cli.main(["--no-capture"])

    assert calls[0]["access_log"] is False
    assert calls[0]["log_level"] == "info"
    assert calls[0]["timeout_graceful_shutdown"] == 4


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.returncode = 0


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def _fake_webview(calls):
    window = SimpleNamespace(
        events=SimpleNamespace(shown=FakeEvent()),
        native=SimpleNamespace(Icon=None),
    )

    def create_window(*args, **kwargs):
        calls.append(("create", args, kwargs))
        return window

    return SimpleNamespace(
        create_window=create_window,
        start=lambda *args, **kwargs: calls.append(("start", args, kwargs)),
    ), window


def test_desktop_icon_assets_are_packaged():
    png = desktop.DESKTOP_ICON_PATH.read_bytes()
    ico = desktop.WINDOWS_ICON_PATH.read_bytes()
    icns = desktop.MACOS_ICON_PATH.read_bytes()

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (1024, 1024)
    assert png[25] == 6  # RGBA
    offset = 8
    compressed = bytearray()
    while offset < len(png):
        length = struct.unpack(">I", png[offset : offset + 4])[0]
        kind = png[offset + 4 : offset + 8]
        if kind == b"IDAT":
            compressed.extend(png[offset + 8 : offset + 8 + length])
        offset += length + 12
    first_scanline = zlib.decompress(compressed)[: 1 + (1024 * 4)]
    assert first_scanline[4] == 0  # Upper-left pixel alpha is transparent.
    assert ico[:4] == b"\x00\x00\x01\x00"
    assert struct.unpack("<H", ico[4:6])[0] >= 7
    assert icns[:4] == b"icns"


def test_macos_identity_bundle_contains_plist_icon_and_python_link(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        desktop, "_macos_application_support_dir", lambda: tmp_path
    )
    monkeypatch.setattr(desktop, "_macos_bundle_version", lambda: "26.237.15")

    executable = desktop._ensure_macos_app_bundle()
    bundle_path = tmp_path / "Gaia Scape.app"
    with (bundle_path / "Contents" / "Info.plist").open("rb") as source:
        document = plistlib.load(source)

    assert document == {
        "CFBundleDisplayName": "Gaia Scape",
        "CFBundleName": "Gaia Scape",
        "CFBundleExecutable": "Gaia Scape",
        "CFBundleIdentifier": "earth.gaiascape.GaiaScape",
        "CFBundleIconFile": "gaia-scape-desktop-icon",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "26.237.15",
        "CFBundleVersion": "26.237.15",
    }
    assert executable.is_symlink()
    assert os.readlink(executable) == sys.executable
    installed_icon = (
        bundle_path / "Contents" / "Resources" / desktop.MACOS_ICON_PATH.name
    )
    assert installed_icon.read_bytes() == desktop.MACOS_ICON_PATH.read_bytes()


def test_macos_identity_relaunch_uses_module_arguments_and_recursion_guard(
    tmp_path, monkeypatch
):
    calls = []
    executable = tmp_path / "Gaia Scape.app" / "Contents" / "MacOS" / "Gaia Scape"
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop.sys, "argv", ["desktop.py", "--example"])
    monkeypatch.delenv(desktop.MACOS_RELAUNCH_MARKER, raising=False)
    monkeypatch.delenv(desktop.MACOS_HEADLESS_MARKER, raising=False)
    monkeypatch.setattr(desktop, "_ensure_macos_app_bundle", lambda: executable)
    monkeypatch.setattr(
        desktop, "_register_macos_app_bundle", lambda path: calls.append(("register", path))
    )
    monkeypatch.setattr(
        desktop.os,
        "execve",
        lambda path, arguments, environment: calls.append(
            (path, arguments, environment)
        ),
    )

    assert desktop.relaunch_for_macos_app_identity() is True
    assert calls[0] == ("register", executable.parents[2])
    path, arguments, environment = calls[1]
    assert path == str(executable)
    assert arguments == [
        str(executable),
        "-m",
        "gaia_scape_host.desktop",
        "--example",
    ]
    assert environment[desktop.MACOS_RELAUNCH_MARKER] == "1"
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == str(
        Path(desktop.__file__).resolve().parents[1]
    )

    monkeypatch.setenv(desktop.MACOS_RELAUNCH_MARKER, "1")
    assert desktop.relaunch_for_macos_app_identity() is False
    assert len(calls) == 2


def test_macos_identity_registers_bundle_with_launch_services(tmp_path, monkeypatch):
    calls = []
    bundle_path = tmp_path / "Gaia Scape.app"
    monkeypatch.setattr(
        desktop.subprocess,
        "run",
        lambda *args, **kwargs: (
            calls.append((args, kwargs)),
            SimpleNamespace(returncode=0, stderr=""),
        )[1],
    )

    desktop._register_macos_app_bundle(bundle_path)

    assert calls == [
        (
            ([str(desktop.MACOS_LSREGISTER_PATH), "-f", str(bundle_path)],),
            {"check": False, "capture_output": True, "text": True},
        )
    ]


@pytest.mark.parametrize(
    ("platform", "headless", "frozen", "executable", "expected"),
    (
        ("linux", False, False, "/usr/bin/python3", False),
        ("darwin", True, False, "/usr/bin/python3", False),
        ("darwin", False, True, "/usr/bin/python3", False),
        (
            "darwin",
            False,
            False,
            "/Applications/Gaia Scape.app/Contents/MacOS/Gaia Scape",
            False,
        ),
        ("darwin", False, False, "/usr/bin/python3", True),
    ),
)
def test_macos_identity_relaunch_platform_headless_and_package_guards(
    monkeypatch, platform, headless, frozen, executable, expected
):
    monkeypatch.setattr(desktop.sys, "platform", platform)
    monkeypatch.setattr(desktop.sys, "executable", executable)
    monkeypatch.setattr(desktop.sys, "frozen", frozen, raising=False)
    monkeypatch.delenv(desktop.MACOS_RELAUNCH_MARKER, raising=False)
    if headless:
        monkeypatch.setenv(desktop.MACOS_HEADLESS_MARKER, "1")
    else:
        monkeypatch.delenv(desktop.MACOS_HEADLESS_MARKER, raising=False)

    assert desktop._should_relaunch_for_macos_identity() is expected


@pytest.mark.skipif(
    sys.platform != "darwin" or importlib.util.find_spec("Foundation") is None,
    reason="requires macOS and PyObjC",
)
def test_macos_symlinked_executable_resolves_as_main_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        desktop, "_macos_application_support_dir", lambda: tmp_path
    )
    executable = desktop._ensure_macos_app_bundle()
    probe = """
import json
from Foundation import NSBundle
bundle = NSBundle.mainBundle()
print(json.dumps({
    "name": bundle.objectForInfoDictionaryKey_("CFBundleDisplayName"),
    "identifier": bundle.bundleIdentifier(),
    "bundle": str(bundle.bundlePath()),
    "executable": str(bundle.executablePath()),
}))
"""

    completed = subprocess.run(
        [str(executable), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    identity = json.loads(completed.stdout.strip())

    assert identity["name"] == desktop.MACOS_APP_NAME
    assert identity["identifier"] == desktop.MACOS_BUNDLE_IDENTIFIER
    assert identity["bundle"] == str(tmp_path / "Gaia Scape.app")
    assert identity["executable"] == str(executable)


def test_macos_symlinked_executable_imports_installed_desktop_module(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        desktop, "_macos_application_support_dir", lambda: tmp_path
    )
    executable = desktop._ensure_macos_app_bundle()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(desktop.__file__).resolve().parents[1])

    completed = subprocess.run(
        [
            str(executable),
            "-c",
            "from gaia_scape_host import desktop; print(desktop.MACOS_APP_NAME)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )

    assert completed.stdout.strip() == desktop.MACOS_APP_NAME


def test_desktop_starts_native_window_and_stops_owned_server(tmp_path, monkeypatch):
    calls = []
    process = FakeProcess()
    fake_webview, window = _fake_webview(calls)
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GAIA_SCAPE_GUI_URL", raising=False)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setenv(desktop.MACOS_RELAUNCH_MARKER, "1")
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: False)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, _process: True)
    monkeypatch.setattr(desktop, "_start_server", lambda: process)
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop.main() == 0

    assert process.terminated is True
    assert calls[0][0] == "create"
    assert calls[0][1][:2] == (
        "Gaia Scape · Living Earth",
        "http://127.0.0.1:8768/",
    )
    assert calls[0][2]["width"] == 1500
    assert calls[0][2]["min_size"] == (960, 640)
    assert calls[1] == ("start", (), {})
    assert window.events.shown.handlers == [desktop.set_macos_app_icon]


def test_desktop_attaches_without_stopping_existing_server(tmp_path, monkeypatch):
    calls = []
    fake_webview, _window = _fake_webview(calls)
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setenv(desktop.MACOS_RELAUNCH_MARKER, "1")
    monkeypatch.setattr(desktop, "_is_healthy", lambda _url: True)
    monkeypatch.setattr(desktop, "_wait_for_health", lambda _url, process: process is None)
    monkeypatch.setattr(desktop, "_start_server", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(desktop, "_available_screen_size", lambda: None)

    assert desktop.main() == 0
    assert calls[-1] == ("start", (), {})


def test_desktop_health_probe_bypasses_http_proxy(monkeypatch):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        desktop,
        "_direct_opener",
        SimpleNamespace(
            open=lambda url, timeout: (calls.append((url, timeout)), Response())[1]
        ),
    )

    assert desktop._is_healthy("http://127.0.0.1:8768/", timeout=2.0)
    assert calls == [("http://127.0.0.1:8768/healthz", 2.0)]


def test_linux_identity_installs_matching_icon(tmp_path: Path, monkeypatch):
    calls = []
    fake_gi = ModuleType("gi")
    fake_gi.__path__ = []
    fake_repository = ModuleType("gi.repository")
    fake_repository.GLib = SimpleNamespace(
        set_prgname=lambda value: calls.append(("id", value)),
        set_application_name=lambda value: calls.append(("name", value)),
    )
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", fake_repository)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(tmp_path / "runtime" / "data"))

    desktop_path = desktop.configure_linux_app_identity()

    assert calls == [("id", desktop.LINUX_APP_ID), ("name", "Gaia Scape")]
    assert desktop_path == tmp_path / "applications" / f"{desktop.LINUX_APP_ID}.desktop"
    text = desktop_path.read_text(encoding="utf-8")
    assert f"Icon={desktop.LINUX_APP_ID}\n" in text
    assert f"StartupWMClass={desktop.LINUX_APP_ID}\n" in text
    installed_icon = (
        tmp_path / "icons" / "hicolor" / "512x512" / "apps" / f"{desktop.LINUX_APP_ID}.png"
    )
    assert installed_icon.read_bytes() == desktop.DESKTOP_ICON_PATH.read_bytes()


def test_macos_icon_callback_uses_desktop_png(monkeypatch):
    calls = []
    icon = object()

    class FakeNSImage:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithContentsOfFile_(self, path):
            calls.append(("load", path))
            return icon

    application = SimpleNamespace(
        setApplicationIconImage_=lambda value: calls.append(("set", value))
    )
    appkit = ModuleType("AppKit")
    appkit.NSApplication = SimpleNamespace(sharedApplication=lambda: application)
    appkit.NSImage = FakeNSImage
    pyobjc_tools = ModuleType("PyObjCTools")
    pyobjc_tools.AppHelper = SimpleNamespace(callAfter=lambda callback: callback())
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "PyObjCTools", pyobjc_tools)

    desktop.set_macos_app_icon()

    assert calls == [("load", str(desktop.DESKTOP_ICON_PATH)), ("set", icon)]
