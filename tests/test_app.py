import asyncio
import time

from fastapi.testclient import TestClient

from gaia_rhythms.events import GaiaEvent
from gaia_rhythms_host import service
from gaia_rhythms_host.app import create_app


class FakeUsgs:
    def __init__(self, events=()):
        self.events = events

    def fetch(self):
        return self.events


def test_web_app_captures_and_reports_status(tmp_path):
    source = FakeUsgs(
        (
            GaiaEvent(
                "usgs",
                "one",
                "earthquake",
                2_000_000_000,
                strength=0.6,
                traits={"magnitude": 3.8, "depth_km": 4.0, "place": "Test Ridge"},
            ),
        )
    )
    app = create_app(tmp_path, auto_capture=False, usgs_client=source)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        home = client.get("/")
        assert home.status_code == 200
        assert 'class="project-version"' in home.text
        assert app.version in home.text
        assert "USGS Earthquake Hazards Program data" not in home.text
        assert 'id="settingsDialog"' in home.text
        assert home.text.count("preview-instrument-button") == 4
        assert "Open-Meteo surf & tides" in home.text
        assert "<h2>Live Events</h2>" in home.text
        assert 'id="liveMode"' in home.text
        assert '/static/gaia-rhythms-icon.svg' in home.text
        assert f'/static/app.js?v={app.version}' in home.text
        assert f'/static/app.css?v={app.version}' in home.text
        capture = client.post("/api/capture", json={})
        status = client.get("/api/status")

    assert capture.json()["inserted"] == 1
    assert status.json()["history"]["event_count"] == 1
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "gaia_rhythms.sqlite3").exists()


def test_live_mode_persists_and_controls_continuous_task(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        enabled = client.put("/api/live/mode", json={"mode": "continuous"})
        assert enabled.status_code == 200
        assert enabled.json()["mode"] == "continuous"
        assert enabled.json()["running"] is True
        paused = client.post("/api/live/stop", json={})
        assert paused.json()["running"] is False

    assert app.state.config.live_mode == "continuous"
    assert '"live_mode": "continuous"' in (tmp_path / "config.json").read_text(encoding="utf-8")


def test_ambient_cue_overlaps_the_next_continuous_interval(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    ocean = GaiaEvent(
        "open_meteo_marine", "swell", "ocean_swell", time.time(),
        latitude=54.54, longitude=-8.37, strength=0.5, traits={"place": "Bundoran"},
    )
    app.state.service.store.add_events((ocean,))
    played = []
    app.state.service.renderer.play = lambda cue, instrument=None: played.append(cue)

    assert asyncio.run(app.state.service.play_next_ambient_event()) is True
    assert played[0].duration == app.state.config.continuous_interval_seconds + 1.5
    original_velocity = 20 + round(ocean.strength * 107.0)
    original_amplitude = 0.08 + ((original_velocity - 20) / 107.0 * 0.5)
    reduced_amplitude = 0.08 + ((played[0].velocity - 20) / 107.0 * 0.5)
    assert abs(reduced_amplitude - (original_amplitude * 0.75)) < 0.003


def test_audio_settings_persist_and_update_live_renderer(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": [],
                "event_instruments": {"earthquake": "tectonic_drone"},
            },
        )
        capture = client.post("/api/capture", json={})

    assert response.status_code == 200
    assert response.json()["event_instruments"]["earthquake"] == "tectonic_drone"
    assert app.state.service.renderer.instrument_mappings["earthquake"] == "tectonic_drone"
    assert capture.json()["disabled"] is True
    assert '"tectonic_drone"' in (tmp_path / "config.json").read_text(encoding="utf-8")


def test_invalid_instrument_does_not_replace_live_mapping(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": ["usgs"],
                "event_instruments": {"earthquake": "not_a_synth"},
            },
        )

    assert response.status_code == 422
    assert app.state.config.event_instruments["earthquake"] == "earthquake"
    assert app.state.service.renderer.instrument_mappings["earthquake"] == "earthquake"


def test_instrument_preview_plays_selected_voice_without_saving(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue, instrument))
    )

    with TestClient(app) as client:
        initial_cues = client.get("/api/cues")
        response = client.post(
            "/api/instruments/preview", json={"instrument": "seismic_bells"}
        )
        emitted = client.get("/api/cues", params={"after": 0})

    assert initial_cues.json() == {"latest_sequence": 0, "cues": []}
    assert response.json() == {
        "played": True, "instrument": "seismic_bells", "kind": "earthquake"
    }
    assert played[0][0].kind == "earthquake"
    assert played[0][0].velocity == 116
    assert played[0][0].duration == 2.4
    assert played[0][0].event.traits["magnitude"] == 6.0
    assert played[0][1] == "seismic_bells"
    assert emitted.json()["latest_sequence"] == 1
    assert emitted.json()["cues"][0]["event"]["kind"] == "earthquake"
    assert emitted.json()["cues"][0]["event"]["traits"]["magnitude"] == 6.0


def test_replay_validates_json_body(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.post(
            "/api/performance/replay",
            content="[]",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400


def test_homebrew_supercollider_bundle_is_detected(tmp_path, monkeypatch):
    sclang = tmp_path / "SuperCollider.app/Contents/MacOS/sclang"
    scsynth = tmp_path / "SuperCollider.app/Contents/Resources/scsynth"
    for executable in (sclang, scsynth):
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setattr(service.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        service,
        "_bundle_candidates",
        lambda name: (sclang,) if name == "sclang" else (scsynth,),
    )

    status = service.detect_supercollider()

    assert status["available"] is True
    assert status["sclang"].endswith("SuperCollider.app/Contents/MacOS/sclang")
    assert status["scsynth"].endswith("SuperCollider.app/Contents/Resources/scsynth")


def test_app_migrates_legacy_database_filename(tmp_path):
    initial_app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    initial_app.state.service.store.add_events(
        (GaiaEvent("usgs", "saved", "earthquake", 100, strength=0.4),)
    )
    legacy_path = tmp_path / "earth_rhythms.sqlite3"
    initial_app.state.service.store.path.replace(legacy_path)

    migrated_app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    assert migrated_app.state.service.store.count() == 1
    assert (tmp_path / "gaia_rhythms.sqlite3").exists()
    assert not legacy_path.exists()
