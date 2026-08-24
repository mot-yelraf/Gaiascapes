import asyncio
import re
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
        assert home.text.count("preview-instrument-button") == 3
        assert home.text.count('<option value="none"') == 3
        assert 'id="event1Instrument"' in home.text
        assert 'id="event2Instrument"' in home.text
        assert 'id="backgroundInstrument"' in home.text
        event_1_markup = home.text.split('id="event1Instrument"', 1)[1].split(
            "</select>", 1
        )[0]
        event_2_markup = home.text.split('id="event2Instrument"', 1)[1].split(
            "</select>", 1
        )[0]
        expected_event_choices = ["earthquake", "tidal_bell", "seismic_bells", "none"]
        assert re.findall(r'<option value="([^"]+)"', event_1_markup) == expected_event_choices
        assert re.findall(r'<option value="([^"]+)"', event_2_markup) == expected_event_choices
        assert "Open-Meteo surf & tides" in home.text
        assert "<h2>Live Events</h2>" in home.text
        assert "Waiting for application status" not in home.text
        assert home.text.index('class="actions"') < home.text.index(
            'class="mode-note continuous-only"'
        )
        assert '>Start</button>' in home.text
        assert 'id="startButton"' in home.text
        assert 'id="captureButton"' not in home.text
        assert 'id="refreshButton"' not in home.text
        assert 'id="locationStatus"' in home.text
        assert 'id="scStatus"' not in home.text
        assert 'id="oscStatus"' not in home.text
        assert home.text.index('<section class="workspace">') < home.text.index(
            '<section class="metrics"'
        )
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


def test_continuous_cycle_overlays_independent_ambient_layers(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    now = time.time()
    events = (
        GaiaEvent(
            "open_meteo_marine", "swell", "ocean_swell", now,
            latitude=54.54, longitude=-8.37, strength=0.5,
            traits={"place": "Bundoran", "swell_period_s": 11.0},
        ),
        GaiaEvent(
            "open_meteo_storm", "storm", "storm_potential", now,
            latitude=1.0, longitude=35.0, strength=0.6,
            traits={"place": "Rift Valley"},
        ),
        GaiaEvent(
            "open_meteo_marine", "tide", "tide_turn", now,
            latitude=39.6, longitude=-9.09, strength=0.4,
            traits={"place": "Nazaré", "tide_state": "high"},
        ),
    )
    app.state.service.store.add_events(events)
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append(("cue", cue))
    )
    app.state.service.renderer.update_layer = (
        lambda cue, instrument=None: played.append(("layer", cue))
    )

    kinds = asyncio.run(app.state.service.play_next_ambient_layers())

    assert kinds == ("ocean_swell", "tide_turn")
    assert {cue.kind for _, cue in played} == set(kinds)
    assert [mode for mode, cue in played if cue.kind == "ocean_swell"] == ["layer"]
    assert [mode for mode, cue in played if cue.kind != "ocean_swell"] == ["cue"]
    ocean_cue = next(cue for _, cue in played if cue.kind == "ocean_swell")
    assert ocean_cue.duration == app.state.config.continuous_interval_seconds + 1.5
    original_velocity = 20 + round(events[0].strength * 107.0)
    original_amplitude = 0.08 + ((original_velocity - 20) / 107.0 * 0.5)
    reduced_amplitude = 0.08 + ((ocean_cue.velocity - 20) / 107.0 * 0.5)
    assert abs(reduced_amplitude - (original_amplitude * 0.75)) < 0.003



def test_storm_background_replaces_ocean_with_persistent_rain_layer(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    now = time.time()
    app.state.service.store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "swell", "ocean_swell", now,
                traits={"place": "Bundoran", "swell_period_s": 11.0},
            ),
            GaiaEvent(
                "open_meteo_storm", "storm", "storm_potential", now,
                strength=0.8, traits={"place": "Rift Valley", "showers_mm": 12.0},
            ),
            GaiaEvent(
                "open_meteo_marine", "tide", "tide_turn", now,
                traits={"place": "Nazaré", "tide_state": "high"},
            ),
        )
    )
    app.state.service.apply_audio_settings(
        ["open_meteo_storm"],
        {
            "earthquake": "earthquake",
            "ocean_swell": "none",
            "tide_turn": "tidal_bell",
            "storm_potential": "storm_potential",
        },
    )
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append(("cue", cue))
    )
    app.state.service.renderer.update_layer = (
        lambda cue, instrument=None: played.append(("layer", cue))
    )

    kinds = asyncio.run(app.state.service.play_next_ambient_layers())

    assert kinds == ("storm_potential", "tide_turn")
    assert [mode for mode, cue in played if cue.kind == "storm_potential"] == ["layer"]
    assert not any(cue.kind == "ocean_swell" for _, cue in played)


def test_audio_settings_persist_and_update_live_renderer(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": [],
                "instrument_slots": {
                    "event_1": "seismic_bells",
                    "event_2": "earthquake",
                    "background": "storm_potential",
                },
            },
        )
        capture = client.post("/api/capture", json={})

    assert response.status_code == 200
    assert response.json()["instrument_slots"] == {
        "event_1": "seismic_bells",
        "event_2": "earthquake",
        "background": "storm_potential",
    }
    assert app.state.service.renderer.instrument_mappings == {
        "earthquake": "seismic_bells",
        "ocean_swell": "none",
        "tide_turn": "earthquake",
        "storm_potential": "storm_potential",
    }
    assert capture.json()["disabled"] is True
    assert '"storm_potential": "storm_potential"' in (
        tmp_path / "config.json"
    ).read_text(encoding="utf-8")


def test_invalid_instrument_does_not_replace_live_mapping(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": ["usgs"],
                "instrument_slots": {
                    "event_1": "not_a_synth",
                    "event_2": "tidal_bell",
                    "background": "ocean_swell",
                },
            },
        )

    assert response.status_code == 422
    assert app.state.config.event_instruments["earthquake"] == "earthquake"
    assert app.state.service.renderer.instrument_mappings["earthquake"] == "earthquake"


def test_audio_settings_allow_silencing_each_event_kind(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.renderer.active_layers.update(
        {"ocean_swell", "storm_potential"}
    )
    stopped = []

    def stop_layer(kind, release=3.0):
        stopped.append(kind)
        app.state.service.renderer.active_layers.discard(kind)
        return True

    app.state.service.renderer.stop_layer = stop_layer

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": ["usgs"],
                "instrument_slots": {
                    "event_1": "none",
                    "event_2": "none",
                    "background": "none",
                },
            },
        )

    assert response.status_code == 200
    assert set(response.json()["instrument_slots"].values()) == {"none"}
    assert set(response.json()["event_instruments"].values()) == {"none"}
    assert set(app.state.service.renderer.instrument_mappings.values()) == {"none"}
    assert app.state.service.renderer.active_layers == set()
    assert {"ocean_swell", "storm_potential"}.issubset(stopped)


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
        status = client.get("/api/status")

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
    assert status.json()["cues"]["latest_location"] == {
        "name": "Earthquake preview",
        "latitude": 18.0,
        "longitude": -35.0,
    }


def test_cue_long_poll_releases_shutdown_connections_promptly(tmp_path, monkeypatch):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    observed_timeouts = []

    async def expire_immediately(awaitable, timeout):
        awaitable.close()
        observed_timeouts.append(timeout)
        raise asyncio.TimeoutError

    monkeypatch.setattr(service.asyncio, "wait_for", expire_immediately)

    result = asyncio.run(app.state.service.emitted_cues(after=0))

    assert result == {"latest_sequence": 0, "cues": ()}
    assert observed_timeouts == [2.0]


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
