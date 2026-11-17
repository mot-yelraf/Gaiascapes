"""Verify frozen process routing and installer startup boundaries.

These checks protect worker pipes and keep per-user configuration independent
of immutable application resources and process-only environment overrides.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from gaiascapes_host import bundled, runtime, worker


def test_frozen_https_uses_included_certificates_without_changing_user_settings(tmp_path, monkeypatch):
    certificates = tmp_path / "cacert.pem"
    certificates.write_text("test CA bundle")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", "")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setitem(sys.modules, "certifi", SimpleNamespace(where=lambda: str(certificates)))
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(tmp_path / "data"))
    bundled.configure_bundled_https()
    assert bundled.os.environ["SSL_CERT_FILE"] == str(certificates)
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("override", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_frozen_https_preserves_custom_trust_stores(monkeypatch, override):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setenv(override, "/custom/trusted-certificates")
    bundled.configure_bundled_https()
    assert bundled.os.environ[override] == "/custom/trusted-certificates"
    if override == "SSL_CERT_DIR":
        assert "SSL_CERT_FILE" not in bundled.os.environ


def test_source_https_keeps_system_trust_configuration(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    bundled.configure_bundled_https()
    assert "SSL_CERT_FILE" not in bundled.os.environ


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


def test_installer_defaults_include_weather_sources_and_murmuration_aurora():
    from gaiascapes_host.config import AppConfig
    config = AppConfig()
    assert {"open_meteo_storm", "open_meteo_marine"} <= set(config.enabled_sources)
    assert config.background_animation == "murmuration"
    assert config.background_murmuration_palette == "aurora"


def test_failed_renderer_start_keeps_desktop_available(tmp_path, monkeypatch):
    import socket
    from gaiascapes_host import desktop
    from gaiascapes_host.config import AppConfig

    data = tmp_path / "data"
    data.mkdir()
    AppConfig().save(data / "config.json")
    monkeypatch.setenv("GAIA_SCAPE_DATA_DIR", str(data))
    monkeypatch.setenv("GAIA_SCAPE_INSTALL_BIRDSONG", "no")

    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            pass

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *args: Probe())
    def fail_audio(_data):
        raise OSError("Renderer unavailable")
    monkeypatch.setattr(bundled, "_audio_command", fail_audio)
    monkeypatch.setattr(desktop, "main", lambda: 0)
    assert bundled.main([]) == 0
    assert "Renderer unavailable" in (data / "desktop.log").read_text()


def test_frozen_windows_server_uses_log_streams_without_a_console(tmp_path, monkeypatch):
    from gaiascapes_host import desktop
    helper = tmp_path / "gaiascapes-runtime.exe"
    helper.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Gaiascapes.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(desktop, "resolve_data_dir", lambda: tmp_path / "data")
    calls = []
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    desktop._start_server()
    assert calls[0][0][0] == [str(helper), "--server"]
    assert calls[0][1]["creationflags"] == 0x08000000
    assert calls[0][1]["stderr"] is sys.stderr
