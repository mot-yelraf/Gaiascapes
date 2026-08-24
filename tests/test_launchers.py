from gaia_rhythms_host import __main__ as cli
from gaia_rhythms_host import desktop


def test_cli_disables_uvicorn_access_log(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("GAIA_RHYTHMS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs))

    cli.main(["--no-capture"])

    assert calls[0]["access_log"] is False
    assert calls[0]["log_level"] == "info"
    assert calls[0]["timeout_graceful_shutdown"] == 4


def test_desktop_disables_uvicorn_access_log(tmp_path, monkeypatch):
    calls = []

    class FakeTimer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setenv("GAIA_RHYTHMS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(desktop.threading, "Timer", FakeTimer)
    monkeypatch.setattr(
        desktop.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    desktop.main()

    assert calls[0]["access_log"] is False
    assert calls[0]["log_level"] == "info"
    assert calls[0]["timeout_graceful_shutdown"] == 4
