"""Verify installer launch icons without starting an installed application.

Disposable homes and fake GUI scripts exercise Finder launcher execution,
Linux menu entries, repairs, and installation-specific uninstall ownership.
"""

import os
from pathlib import Path
import plistlib
import shlex
import subprocess

import pytest

from gaiascapes_host import desktop, launch_icons


@pytest.mark.skipif(os.name == "nt", reason="POSIX application launcher")
def test_macos_icon_launches_selected_runtime_and_repairs(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    runtime = tmp_path / "Earth's $HOME `echo nope` map"
    (runtime / "scripts").mkdir(parents=True)
    (runtime / "data").mkdir()
    script = runtime / "scripts/run_gaiascapes_gui.sh"
    script.write_text('#!/bin/bash\nprintf "launched:%s\\n" "$1"\n')
    script.chmod(0o755)
    bundle = launch_icons.write_macos_app_launcher(runtime)
    executable = bundle / "Contents/MacOS/Gaiascapes"
    assert plistlib.loads((bundle / "Contents/Info.plist").read_bytes())[
        "GaiascapesInstallDirectory"
    ] == str(runtime)
    assert (bundle / "Contents/Resources" / desktop.MACOS_ICON_PATH.name).read_bytes() == desktop.MACOS_ICON_PATH.read_bytes()
    subprocess.run(["bash", "-n", str(executable)], check=True)
    subprocess.run([str(executable), "map preview"], check=True)
    assert (runtime / "data/desktop-launch.log").read_text() == "launched:map preview\n"
    assert not (runtime / "data/config.json").exists()
    assert "GAIA_SCAPE_HTTP" not in executable.read_text()
    assert "GAIA_SCAPE_OSC" not in executable.read_text()
    assert "display alert" in executable.read_text()
    other = tmp_path / "new runtime"
    assert launch_icons.write_macos_app_launcher(other) == bundle
    monkeypatch.setattr(launch_icons.sys, "platform", "darwin")
    launch_icons.remove_launch_icon(runtime)
    assert bundle.exists()
    launch_icons.remove_launch_icon(other)
    assert not bundle.exists()


def test_macos_icon_preserves_unrelated_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bundle = tmp_path / "Applications/Gaiascapes.app"
    bundle.mkdir(parents=True)
    sentinel = bundle / "personal-file"
    sentinel.write_text("keep")
    with pytest.raises(FileExistsError):
        launch_icons.write_macos_app_launcher(tmp_path / "runtime")
    assert sentinel.read_text() == "keep"


def test_linux_install_creates_menu_entry_without_running_gui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "desktop"))
    monkeypatch.setattr(launch_icons.sys, "platform", "linux")
    runtime = tmp_path / 'Earth map $money `literal` 50% "quoted"'
    (runtime / "scripts").mkdir(parents=True)
    script = runtime / "scripts/run_gaiascapes_gui.sh"
    script.write_text("must not run")
    monkeypatch.setattr(launch_icons.sys, "argv", ["launch_icons", str(runtime)])
    assert launch_icons.main() == 0
    entry = tmp_path / "desktop/applications" / f"{desktop.LINUX_APP_ID}.desktop"
    text = entry.read_text()
    assert "Terminal=false" in text
    assert "Categories=AudioVideo;Audio;" in text
    exec_value = next(line[5:] for line in text.splitlines() if line.startswith("Exec="))
    # Undo the desktop string escaping, then quoted argument escaping/field codes.
    command = exec_value.replace("\\\\", "\\")
    # shlex keeps the escapes for dollar signs and backticks inside double quotes.
    decoded = shlex.split(command)[0].replace("\\$", "$").replace("\\`", "`")
    assert decoded.replace("%%", "%") == str(script)
    assert not (runtime / "data").exists()
    assert launch_icons.main() == 0
    assert entry.read_text() == text
    launch_icons.remove_launch_icon(tmp_path / "different installation")
    assert entry.exists()
    launch_icons.remove_launch_icon(runtime)
    assert not entry.exists()
    assert not (tmp_path / "desktop/icons/hicolor/512x512/apps" / f"{desktop.LINUX_APP_ID}.png").exists()


def test_icon_creation_is_independent_of_auto_start_and_headless_mode():
    installer = Path("install.sh").read_text()
    creation = installer.index("-m gaiascapes_host.launch_icons")
    assert installer.rfind('if [[ "$INSTALL_MODE" == desktop ]]; then', 0, creation) > installer.index('data/install-mode')
    assert creation < installer.index('enable_autostart=')
    uninstaller = Path("uninstall.sh").read_text()
    assert uninstaller.index("-m gaiascapes_host.launch_icons") < uninstaller.index('rm -rf "$INSTALL_DIR/.venv"')
