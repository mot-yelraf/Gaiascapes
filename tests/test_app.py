"""Integration tests for the Gaia Scape web application.

These tests exercise HTTP routes and service coordination with deterministic
provider doubles while verifying rendered controls and persisted settings.
"""

import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient

from gaia_scape.events import GaiaEvent
from gaia_scape.score import ScoreCue
from gaia_scape_host import service
from gaia_scape_host.app import create_app


class FakeUsgs:
    def __init__(self, events=()):
        self.events = events

    def fetch(self):
        return self.events


class FakeGlm:
    def __init__(self, events=(), raw_count=0):
        self.events = tuple(events)
        self.last_raw_flash_count = raw_count
        self.last_granule_count = 2 if events else 0
        self.last_error = ""

    def fetch(self):
        return self.events

    def status(self):
        return {
            "granule_count": self.last_granule_count,
            "raw_flash_count": self.last_raw_flash_count,
        }


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
        assert home.text.count('<option value="none"') == 4
        assert 'id="event1Instrument"' in home.text
        assert 'id="event2Instrument"' in home.text
        assert 'id="event3Instrument"' in home.text
        assert 'id="backgroundInstrument"' in home.text
        assert 'id="displayUnits"' in home.text
        for volume_id in (
            "event1Volume", "event2Volume", "event3Volume", "backgroundVolume"
        ):
            assert f'id="{volume_id}" type="range"' in home.text
        assert 'id="event3Volume" type="range" min="0" max="100" step="1" value="45"' in home.text
        assert home.text.count('data-lightning-sample-rate type="range" min="1" max="11"') == 3
        assert 'id="event3LightningSampleRate" data-lightning-sample-rate type="range" min="1" max="11" step="1" value="1"' in home.text
        assert "The background remains continuous while its forecast location" not in home.text
        event_1_markup = home.text.split('id="event1Instrument"', 1)[1].split(
            "</select>", 1
        )[0]
        event_2_markup = home.text.split('id="event2Instrument"', 1)[1].split(
            "</select>", 1
        )[0]
        event_3_markup = home.text.split('id="event3Instrument"', 1)[1].split(
            "</select>", 1
        )[0]
        expected_event_choices = [
            "earthquake", "tidal_bell", "seismic_bells", "lightning_glass", "none"
        ]
        assert re.findall(r'<option value="([^"]+)"', event_1_markup) == expected_event_choices
        assert re.findall(r'<option value="([^"]+)"', event_2_markup) == expected_event_choices
        assert re.findall(r'<option value="([^"]+)"', event_3_markup) == expected_event_choices
        assert home.text.count("Lightning R2D2") == 3
        assert "Open-Meteo surf & tides" in home.text
        assert 'id="sourceGlm"' in home.text
        assert "NOAA GOES GLM lightning" in home.text
        assert "<h2>Live Events</h2>" in home.text
        assert "spatial soundscapes" not in home.text
        assert 'id="systemPulse"' not in home.text
        assert 'id="dashboardViewButton"' in home.text
        assert 'id="mapViewButton"' in home.text
        assert 'id="worldMap"' in home.text
        assert 'id="mapPulseLayer"' in home.text
        assert 'href="/static/gaia-scape-icon.svg#realistic-land"' in home.text
        assert 'role="tablist"' in home.text
        assert 'data-workspace-tab="live"' in home.text
        assert 'data-workspace-tab="history"' in home.text
        assert 'role="tabpanel"' in home.text
        assert home.text.count('class="panel ') == 1
        assert "Waiting for application status" not in home.text
        assert home.text.index('class="actions"') < home.text.index(
            'class="mode-note continuous-only"'
        )
        assert '>Start</button>' in home.text
        assert 'id="startButton"' in home.text
        assert 'id="captureButton"' not in home.text
        assert 'id="refreshButton"' not in home.text
        assert 'id="backgroundSoundsStatus"' in home.text
        assert 'id="eventTimeStatus"' in home.text
        assert 'id="eventSoundsStatus"' in home.text
        assert 'id="backgroundSoundsTitle">Ocean Swells</span>' in home.text
        assert "Open-Meteo Storm Outlook" in home.text
        assert '<option value="storm_potential" >Storm Outlook</option>' in home.text
        assert "Event Time" in home.text
        assert "Event Sounds" in home.text
        assert 'id="scStatus"' not in home.text
        assert 'id="oscStatus"' not in home.text
        assert home.text.index('<section class="workspace">') < home.text.index(
            '<section class="metrics"'
        )
        assert 'id="liveMode"' in home.text
        assert '/static/gaia-scape-icon.svg' in home.text
        assert "Created by Peace Hill Studios" in home.text
        assert f'/static/app.js?v={app.version}' in home.text
        assert f'/static/app.css?v={app.version}' in home.text
        script = client.get("/static/app.js").text
        assert 'lightning_flash: ["#79500a"' in script
        assert 'instrument === "lightning_glass" ? "lightning_flash"' in script
        assert "cue.volume ?? 1" in script
        assert "baseScale * visualVolume" in script
        assert 'return "Storm Outlook"' in script
        assert 'return "Lightning R2D2"' in script
        assert 'updateBackgroundSoundsTitle(event.target.value)' in script
        assert 'control.hidden = select.value !== "lightning_glass"' in script
        assert "lightning_sample_rate: Number(lightningSampleSliders[0].value)" in script
        assert "activateWorkspacePane" in script
        assert "activateAppView" in script
        assert 'APP_VIEW_STORAGE_KEY = "gaia-scape-app-view"' in script
        assert "activateAppView(savedAppView())" in script
        assert "saveAppView(selectedName)" in script
        assert "projectCoordinates" in script
        assert "inverseProjectCoordinates" in script
        assert "mapProjectionBoundary" in script
        assert "mapContainsPoint" in script
        assert "mapMarkerTitle" in script
        assert 'event.kind === "earthquake"' in script
        assert "animateMapEvent" in script
        assert 'role === "background" ? "3.1" : "2.8"' in script
        assert "renderMapHistory(events)" in script
        assert 'byId("systemPulse")' not in script
        assert '"ArrowLeft", "ArrowRight", "Home", "End"' in script
        stylesheet = client.get("/static/app.css").text
        assert ".workspace { width: 57.5%; margin: 46px auto 0; }" in stylesheet
        assert "grid-template-columns: minmax(7.5rem, 1fr) 7rem" in stylesheet
        assert ".workspace { width: 100%; }" in stylesheet
        assert "50% { opacity: .62; transform: scale(var(--map-pulse-scale, 2.8)); }" in stylesheet
        capture = client.post("/api/capture", json={})
        events = client.get("/api/events")
        status = client.get("/api/status")

    assert capture.json()["inserted"] == 1
    assert events.json()["events"][0]["instrument"] == "earthquake"
    assert status.json()["history"]["event_count"] == 1
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "gaia_scape.sqlite3").exists()


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
    first_history = asyncio.run(app.state.service.recent_events(hours=1))
    assert {item["event_id"] for item in first_history} == {"swell", "tide"}

    played.clear()
    repeated_kinds = asyncio.run(app.state.service.play_next_ambient_layers())

    assert repeated_kinds == ("ocean_swell",)
    assert [cue.kind for _, cue in played] == ["ocean_swell"]
    repeated_history = asyncio.run(app.state.service.recent_events(hours=1))
    assert [item["event_id"] for item in repeated_history] == [
        item["event_id"] for item in first_history
    ]
    assert app.state.service._emitted_cues[-1]["history_updated"] is False



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
            "event_1": "earthquake",
            "event_2": "tidal_bell",
            "background": "storm_potential",
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

    played.clear()
    repeated_kinds = asyncio.run(app.state.service.play_next_ambient_layers())

    assert repeated_kinds == ("storm_potential",)
    assert [cue.kind for _, cue in played] == ["storm_potential"]


def test_event_history_returns_newest_records_with_small_limit(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    now = time.time()
    app.state.service.store.add_events(
        tuple(
            GaiaEvent("usgs", f"event-{index}", "earthquake", now + index)
            for index in range(5)
        )
    )

    history = asyncio.run(app.state.service.recent_events(hours=1, limit=2))

    assert [item["event_id"] for item in history] == ["event-4", "event-3"]


def test_event_history_publishes_background_only_when_visited_and_changed(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    now = time.time()
    amazon_old = GaiaEvent(
        "open_meteo_storm", "amazon-old", "storm_potential", now - 120,
        strength=0.2, traits={"place": "Amazon Basin", "cape_jkg": 700},
    )
    amazon_same = GaiaEvent(
        "open_meteo_storm", "amazon-same", "storm_potential", now - 60,
        strength=0.2, traits={"place": "Amazon Basin", "cape_jkg": 700},
    )
    amazon_new = GaiaEvent(
        "open_meteo_storm", "amazon-new", "storm_potential", now - 30,
        strength=0.6, traits={"place": "Amazon Basin", "cape_jkg": 1800},
    )
    caribbean = GaiaEvent(
        "open_meteo_storm", "caribbean", "storm_potential", now - 20,
        strength=0.4, traits={"place": "Caribbean", "cape_jkg": 1200},
    )
    swell = GaiaEvent(
        "open_meteo_marine", "bundoran-swell", "ocean_swell", now - 10,
        strength=0.5,
        traits={"place": "Bundoran", "swell_height_m": 3.0, "swell_period_s": 12.0},
    )
    swell_same = GaiaEvent(
        "open_meteo_marine", "bundoran-swell-same", "ocean_swell", now - 5,
        strength=0.5,
        traits={
            "place": "Bundoran", "swell_height_m": 3.0,
            "swell_period_s": 12.0, "sea_level_msl_m": 0.8,
        },
    )
    app.state.service.store.add_events(
        (
            amazon_old,
            amazon_same,
            amazon_new,
            caribbean,
            swell,
            swell_same,
            GaiaEvent(
                "open_meteo_marine", "nazare-high", "tide_turn", now - 100,
                traits={"place": "Nazaré", "tide_state": "high"},
            ),
            GaiaEvent(
                "open_meteo_marine", "nazare-low", "tide_turn", now - 20,
                traits={"place": "Nazaré", "tide_state": "low"},
            ),
            GaiaEvent("usgs", "quake-1", "earthquake", now - 90),
            GaiaEvent("usgs", "quake-2", "earthquake", now - 10),
        )
    )

    initial = asyncio.run(app.state.service.recent_events(hours=1, limit=100))
    assert {item["event_id"] for item in initial} == {
        "nazare-high", "nazare-low", "quake-1", "quake-2"
    }

    app.state.service._record_emitted_cue(
        ScoreCue(0, amazon_old, 60, 80), "storm_potential", publish_background=True
    )
    first_publish_time = next(
        iter(app.state.service._published_background_state.values())
    )["published_at"]
    app.state.service._record_emitted_cue(
        ScoreCue(0, amazon_same, 60, 80), "storm_potential", publish_background=True
    )

    unchanged = asyncio.run(app.state.service.recent_events(hours=1, limit=100))
    assert "amazon-old" in {item["event_id"] for item in unchanged}
    assert "amazon-same" not in {item["event_id"] for item in unchanged}
    assert next(iter(app.state.service._published_background_state.values()))[
        "published_at"
    ] == first_publish_time

    for event, instrument in (
        (amazon_new, "storm_potential"),
        (caribbean, "storm_potential"),
        (swell, "ocean_swell"),
    ):
        app.state.service._record_emitted_cue(
            ScoreCue(0, event, 60, 80), instrument, publish_background=True
        )
    app.state.service._record_emitted_cue(
        ScoreCue(0, swell_same, 60, 80), "ocean_swell", publish_background=True
    )
    app.state.service._record_emitted_cue(
        ScoreCue(
            0,
            GaiaEvent(
                "usgs", "later-quake", "earthquake", now,
                traits={"place": "Quake Ridge"},
            ),
            60,
            80,
        ),
        "earthquake",
    )

    history = asyncio.run(app.state.service.recent_events(hours=1, limit=100))

    assert {item["event_id"] for item in history} == {
        "amazon-new", "caribbean", "bundoran-swell",
        "nazare-high", "nazare-low", "quake-1", "quake-2",
    }
    amazon = next(item for item in history if item["event_id"] == "amazon-new")
    assert amazon["traits"]["cape_jkg"] == 1800
    assert "bundoran-swell-same" not in {item["event_id"] for item in history}
    status = asyncio.run(app.state.service.status())
    assert status["cues"]["latest_location"]["name"] == "Bundoran"
    assert status["cues"]["latest_background_location"]["name"] == "Bundoran"
    cues = asyncio.run(app.state.service.emitted_cues(after=0))["cues"]
    assert [cue["history_updated"] for cue in cues[:2]] == [True, False]


def test_event_history_includes_older_event_emitted_inside_window(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    event = GaiaEvent(
        "usgs",
        "older-but-just-heard",
        "earthquake",
        time.time() - 10800,
        strength=0.6,
        traits={"place": "Test Ridge"},
    )
    app.state.service.store.add_events((event,))
    app.state.service.renderer.play = lambda cue, instrument=None: True

    asyncio.run(app.state.service._play_live_event(event))
    history = asyncio.run(app.state.service.recent_events(hours=1))

    assert [item["event_id"] for item in history] == ["older-but-just-heard"]
    assert history[0]["emitted_at"] is not None


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
                    "event_3": "none",
                    "background": "storm_potential",
                },
                "units": "imperial",
                "instrument_volumes": {
                    "event_1": 0.8,
                    "event_2": 0.65,
                    "event_3": 0.35,
                    "background": 0.5,
                },
                "lightning_sample_rate": 7,
            },
        )
        capture = client.post("/api/capture", json={})
        home = client.get("/")

    assert response.status_code == 200
    assert response.json()["instrument_slots"] == {
        "event_1": "seismic_bells",
        "event_2": "earthquake",
        "event_3": "none",
        "background": "storm_potential",
    }
    assert 'id="backgroundSoundsTitle">Storm Outlook</span>' in home.text
    assert response.json()["units"] == "imperial"
    assert response.json()["instrument_volumes"] == {
        "event_1": 0.8,
        "event_2": 0.65,
        "event_3": 0.35,
        "background": 0.5,
    }
    assert response.json()["lightning_sample_rate"] == 7
    assert app.state.service.glm.sonification_sample_stride == 7
    assert app.state.config.units == "imperial"
    assert app.state.config.instruments_for_event("earthquake") == (
        "seismic_bells", "earthquake"
    )
    assert app.state.service.renderer.instrument_mappings == {
        "earthquake": "none",
        "ocean_swell": "none",
        "tide_turn": "none",
        "storm_potential": "storm_potential",
    }
    assert app.state.service._voices_for_kind("storm_potential") == (
        ("storm_potential", 0.5),
    )
    assert capture.json()["disabled"] is True
    assert '"background": "storm_potential"' in (
        tmp_path / "config.json"
    ).read_text(encoding="utf-8")
    assert '"lightning_sample_rate": 7' in (
        tmp_path / "config.json"
    ).read_text(encoding="utf-8")
    assert '"units": "imperial"' in (
        tmp_path / "config.json"
    ).read_text(encoding="utf-8")
    assert '"event_3": 0.35' in (
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
    assert app.state.config.event_instruments["event_1"] == "earthquake"
    assert app.state.service.renderer.instrument_mappings["earthquake"] == "none"


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


def test_instrument_preview_plays_and_adds_event_to_history(tmp_path):
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
        history = client.get("/api/events")
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
    assert emitted.json()["cues"][0]["instrument"] == "seismic_bells"
    assert emitted.json()["cues"][0]["volume"] == 1.0
    assert emitted.json()["cues"][0]["role"] == "event"
    assert emitted.json()["cues"][0]["event"]["kind"] == "earthquake"
    assert emitted.json()["cues"][0]["event"]["traits"]["magnitude"] == 6.0
    assert history.json()["events"][0]["instrument"] == "seismic_bells"
    assert history.json()["events"][0]["provider"] == "preview"
    assert status.json()["history"]["event_count"] == 1
    assert status.json()["cues"]["latest_location"] == {
        "name": "Earthquake preview",
        "latitude": 18.0,
        "longitude": -35.0,
    }
    assert status.json()["cues"]["latest_background_location"] is None
    assert status.json()["cues"]["latest_event_sounds"] == ["seismic_bells"]


def test_instrument_preview_uses_unsaved_slider_volume(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append(cue) or True
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/instruments/preview",
            json={
                "kind": "lightning_flash",
                "instrument": "lightning_glass",
                "volume": 0.25,
            },
        )
        emitted = client.get("/api/cues", params={"after": 0}).json()["cues"]

    assert response.status_code == 200
    assert played[0].velocity < 116
    assert emitted[0]["volume"] == 0.25


def test_event_history_identifies_seismic_bell_voice(tmp_path):
    event = GaiaEvent(
        "usgs", "bell-event", "earthquake", time.time(), strength=0.7
    )
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs((event,)))

    with TestClient(app) as client:
        client.post("/api/capture", json={})
        client.put(
            "/api/settings/audio",
            json={
                "enabled_sources": ["usgs"],
                "instrument_slots": {
                    "event_1": "seismic_bells",
                    "event_2": "tidal_bell",
                    "background": "ocean_swell",
                },
            },
        )
        history = client.get("/api/events").json()["events"]

    assert history[0]["instrument"] == "seismic_bells"


def test_independent_event_slots_follow_the_selected_voice_source(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.apply_audio_settings(
        ["usgs", "open_meteo_marine"],
        {
            "event_1": "tidal_bell",
            "event_2": "seismic_bells",
            "event_3": "earthquake",
            "background": "none",
        },
    )
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue.kind, instrument))
    )
    now = time.time()

    asyncio.run(
        app.state.service._play_live_event(
            GaiaEvent("usgs", "quake", "earthquake", now, strength=0.6)
        )
    )
    asyncio.run(
        app.state.service._play_live_event(
            GaiaEvent("open_meteo_marine", "tide", "tide_turn", now, strength=0.5)
        )
    )

    assert played == [
        ("earthquake", "seismic_bells"),
        ("earthquake", "earthquake"),
        ("tide_turn", "tidal_bell"),
    ]


def test_matching_duplicate_slots_each_emit_a_cue(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.apply_audio_settings(
        ["usgs"],
        {
            "event_1": "seismic_bells",
            "event_2": "seismic_bells",
            "background": "none",
        },
    )
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append(instrument)
    )

    asyncio.run(
        app.state.service._play_live_event(
            GaiaEvent("usgs", "quake", "earthquake", time.time(), strength=0.6)
        )
    )

    assert played == ["seismic_bells", "seismic_bells"]
    assert app.state.service.continuous_played_count == 2
    status = asyncio.run(app.state.service.status())
    assert status["cues"]["latest_event_sounds"] == [
        "seismic_bells", "seismic_bells"
    ]


def test_replay_cue_count_reflects_independent_matching_slots(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.apply_audio_settings(
        ["usgs"],
        {
            "event_1": "seismic_bells",
            "event_2": "seismic_bells",
            "background": "none",
        },
    )
    now = time.time()
    app.state.service.store.add_events(
        (
            GaiaEvent("usgs", "quake", "earthquake", now - 1),
            GaiaEvent("open_meteo_marine", "tide", "tide_turn", now - 1),
        )
    )

    result = asyncio.run(
        app.state.service.replay(hours=0.05, performance_seconds=1)
    )

    assert result["event_count"] == 2
    assert result["cue_count"] == 2


def test_event_2_preview_adds_selected_voice_to_history(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.renderer.play = lambda cue, instrument=None: True

    with TestClient(app) as client:
        response = client.post(
            "/api/instruments/preview",
            json={"kind": "tide_turn", "instrument": "tidal_bell"},
        )
        history = client.get("/api/events").json()["events"]
        count = client.get("/api/status").json()["history"]["event_count"]

    assert response.status_code == 200
    assert count == 1
    assert history[0]["kind"] == "tide_turn"
    assert history[0]["instrument"] == "tidal_bell"


def test_lightning_glass_preview_stays_out_of_history_and_event_sounds(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.renderer.play = lambda cue, instrument=None: True

    with TestClient(app) as client:
        response = client.post(
            "/api/instruments/preview",
            json={"kind": "lightning_flash", "instrument": "lightning_glass"},
        )
        history = client.get("/api/events").json()["events"]
        status = client.get("/api/status").json()

    assert response.status_code == 200
    assert history == []
    assert status["history"]["event_count"] == 0
    assert status["cues"]["latest_event_sounds"] == []


def test_glm_capture_reports_raw_counts_and_sounds_each_satellite(
    tmp_path, caplog, monkeypatch
):
    now = time.time()
    flashes = (
        GaiaEvent(
            "noaa_glm", "east", "lightning_flash", now,
            latitude=0, longitude=-75, strength=0.8,
            traits={"satellite": "GOES-19", "magnitude": 6.0},
        ),
        GaiaEvent(
            "noaa_glm", "west", "lightning_flash", now,
            latitude=0, longitude=-140, strength=0.7,
            traits={"satellite": "GOES-18", "magnitude": 5.5},
        ),
    )
    glm = FakeGlm(flashes, raw_count=389)
    app = create_app(
        tmp_path, auto_capture=False, usgs_client=FakeUsgs(), glm_client=glm
    )
    app.state.config.live_mode = "continuous"
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue, instrument)) or True
    )

    monkeypatch.setattr(service, "GLM_SONIFICATION_TIME_SCALE", 0.0)

    async def capture_and_finish_sonification():
        with caplog.at_level("INFO", logger="uvicorn.error"):
            result = await app.state.service.capture_glm_once()
        await app.state.service._glm_sonification_task
        return result, await app.state.service.status()

    result, status = asyncio.run(capture_and_finish_sonification())
    history = asyncio.run(app.state.service.recent_events(hours=1))

    assert result == {"received": 2, "raw_flashes": 389, "inserted": 2, "pruned": 0}
    assert [instrument for _cue, instrument in played] == [
        "lightning_glass", "lightning_glass"
    ]
    assert min(cue.pitch for cue, _instrument in played) >= 52
    assert max(cue.pitch for cue, _instrument in played) <= 61
    assert len({cue.pitch for cue, _instrument in played}) > 1
    assert status["glm"]["raw_flash_count"] == 389
    assert status["history"]["event_count"] == 0
    assert status["cues"]["latest_event_sounds"] == []
    assert history == ()
    assert (
        "NOAA GLM update: 2 granules, 389 raw flashes, 2 sampled, "
        "2 new, 2 sonified"
    ) in caplog.text


def test_glm_sonification_can_play_a_hundred_hidden_notes(tmp_path, monkeypatch):
    app = create_app(
        tmp_path, auto_capture=False, usgs_client=FakeUsgs(), glm_client=FakeGlm()
    )
    app.state.config.live_mode = "continuous"
    app.state.config.instrument_volumes["event_3"] = 0.2
    monkeypatch.setattr(service, "GLM_SONIFICATION_TIME_SCALE", 0.0)
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue, instrument)) or True
    )
    flashes = tuple(
        GaiaEvent(
            "noaa_glm", f"flash-{index}", "lightning_flash", time.time() + index / 10,
            latitude=(index % 80) - 40,
            longitude=(index * 17 % 360) - 180,
            strength=0.35 + ((index % 60) / 100),
            traits={"flash_id": index, "satellite": "GOES-19"},
        )
        for index in range(100)
    )

    asyncio.run(app.state.service._run_glm_sonification(flashes))
    status = asyncio.run(app.state.service.status())

    assert len(played) == 100
    assert len({cue.pitch for cue, _instrument in played}) >= 12
    assert {instrument for _cue, instrument in played} == {"lightning_glass"}
    assert {cue["volume"] for cue in app.state.service._emitted_cues} == {0.2}
    assert status["history"]["event_count"] == 0
    assert status["cues"]["latest_event_sounds"] == []


def test_background_preview_does_not_add_captured_event(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.renderer.play = lambda cue, instrument=None: True

    with TestClient(app) as client:
        response = client.post(
            "/api/instruments/preview",
            json={"kind": "ocean_swell", "instrument": "ocean_swell"},
        )
        emitted = client.get("/api/cues", params={"after": 0}).json()["cues"]
        count = client.get("/api/status").json()["history"]["event_count"]

    assert response.status_code == 200
    assert count == 0
    assert emitted[0]["role"] == "background"


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


@pytest.mark.parametrize("legacy_name", ["gaia_rhythms.sqlite3", "earth_rhythms.sqlite3"])
def test_app_migrates_legacy_database_filename(tmp_path, legacy_name):
    initial_app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    initial_app.state.service.store.add_events(
        (GaiaEvent("usgs", "saved", "earthquake", 100, strength=0.4),)
    )
    legacy_path = tmp_path / legacy_name
    initial_app.state.service.store.path.replace(legacy_path)

    migrated_app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    assert migrated_app.state.service.store.count() == 1
    assert (tmp_path / "gaia_scape.sqlite3").exists()
    assert not legacy_path.exists()
