"""Verify frozen process routing and installer startup boundaries.

These checks protect worker pipes and keep per-user configuration independent
of immutable application resources and process-only environment overrides.
"""

from pathlib import Path
import sys

import pytest

from gaiascapes_host import bundled, runtime, worker


def test_source_module_command_uses_python():
    assert runtime.module_command("gaiascapes_host.worker") == [
        sys.executable, "-m", "gaiascapes_host.worker",
    ]


def test_frozen_subprocesses_use_console_helper(tmp_path, monkeypatch):
    helper = tmp_path / ("gaiascapes-runtime.exe" if sys.platform == "win32" else "gaiascapes-runtime")
    helper.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Gaiascapes"))
    assert runtime.module_command("gaiascapes_host.worker") == [str(helper), "--worker"]
    assert runtime.module_command("gaiascapes_host") == [str(helper), "--server"]
    helper.unlink()
    with pytest.raises(RuntimeError, match="runtime helper is missing"):
        runtime.module_command("gaiascapes_host")


def test_worker_dispatch_does_not_initialize_user_data(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "main", lambda: calls.append("worker"))
    monkeypatch.setattr(bundled, "resolve_data_dir", lambda: pytest.fail("Worker initialized app state"))
    assert bundled.main(["--worker"]) == 0
    assert calls == ["worker"]


def test_bundled_server_forwards_options_and_preserves_saved_ports(tmp_path, monkeypatch):
    from gaiascapes_host import __main__ as server
    from gaiascapes_host.config import AppConfig
    data = tmp_path / "data"
    data.mkdir()
    saved = data / "config.json"
    AppConfig().save(saved)
    original = saved.read_bytes()
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(data))
    monkeypatch.setenv("GAIA_SCAPE_HTTP_PORT", "18769")
    calls = []
    monkeypatch.setattr(server, "main", lambda arguments: calls.append(arguments))
    assert bundled.main(["--server", "--no-capture", "--host", "127.0.0.1"]) == 0
    assert calls == [["--no-capture", "--host", "127.0.0.1"]]
    assert saved.read_bytes() == original


def test_external_audio_environment_restores_system_library_paths(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/libraries")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/libraries")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/bundle/mac-libraries")
    monkeypatch.delenv("DYLD_LIBRARY_PATH_ORIG", raising=False)
    environment = bundled.external_environment()
    assert environment["LD_LIBRARY_PATH"] == "/system/libraries"
    assert "DYLD_LIBRARY_PATH" not in environment
    assert bundled.os.environ["LD_LIBRARY_PATH"] == "/bundle/libraries"


def test_installer_defaults_use_murmuration_aurora():
    from gaiascapes_host.config import AppConfig
    config = AppConfig()
    assert config.background_animation == "murmuration"
    assert config.background_murmuration_palette == "aurora"
