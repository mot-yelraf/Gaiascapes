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


class FakeGeoIpResolver:
    def resolve(self):
        return {
            "name": "Test City, Test Region",
            "latitude": 39.7392,
            "longitude": -104.9903,
            "timezone": "America/Denver",
            "provider": "test",
        }


class RecoveringMarine:
    def __init__(self):
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "Open-Meteo is temporarily limiting requests; Gaia Scape will retry automatically."
            )
        return (
            GaiaEvent(
                "open_meteo_marine", "recovered", "ocean_swell", time.time(),
                latitude=-27.68, longitude=-48.45, strength=0.5,
            ),
        )


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
            "earthquake", "tidal_bell", "seismic_bells", "lightning_glass",
            "natural_thunder", "none"
        ]
        assert re.findall(r'<option value="([^"]+)"', event_1_markup) == expected_event_choices
        assert re.findall(r'<option value="([^"]+)"', event_2_markup) == expected_event_choices
        assert re.findall(r'<option value="([^"]+)"', event_3_markup) == expected_event_choices
        assert home.text.count("Lightning R2D2") == 3
        assert home.text.count("Natural Thunder") == 3
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
        assert 'id="mapSystemLocationLayer"' in home.text
        assert "My location" in home.text
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
        assert 'id="lastEventType"' in home.text
        assert 'id="lastEventTime"' in home.text
        assert 'id="lastEarthquakeLocation"' in home.text
        assert 'id="lastEarthquakeDetail"' in home.text
        assert 'id="backgroundSoundsTitle" data-status-field="background-title">Ocean Swells</span>' in home.text
        assert home.text.count('data-status-field="background-location"') == 2
        assert home.text.count('data-status-field="background-characteristics"') == 2
        assert home.text.count('data-status-field="last-event-type"') == 2
        assert home.text.count('data-status-field="last-event-time"') == 2
        assert home.text.count('data-status-field="last-earthquake-location"') == 2
        assert home.text.count('data-status-field="last-earthquake-detail"') == 2
        assert home.text.count(">Last Event</span>") == 2
        assert home.text.count(">Last Earthquake Event</span>") == 2
        assert home.text.count('class="status-card status-card--background"') == 2
        assert home.text.count('class="status-card status-card--event"') == 2
        assert home.text.count('class="status-card status-card--earthquake"') == 2
        assert 'aria-label="Map application status"' in home.text
        assert "Open-Meteo Storm Outlook" in home.text
        assert '<option value="storm_potential" >Storm Outlook</option>' in home.text
        assert "Event Time" not in home.text
        assert "Event Sounds" not in home.text
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
        assert "pill.textContent = `${severity.label} · M${magnitude.toFixed(1)}`" in script
        assert (
            "observation.textContent = `${Number(event.latitude).toFixed(2)}, "
            "${Number(event.longitude).toFixed(2)} @ ${when(event.timestamp)}`"
        ) in script
        assert (
            "`${Number(event.latitude).toFixed(2)}, "
            "${Number(event.longitude).toFixed(2)} @ ${when(event.timestamp)}`"
        ) in script
        assert "status.sources?.recovery" in script
        assert "syncRecoveryToasts({" in script
        assert "Click to dismiss" in script
        assert 'id="recoveryToasts"' in home.text
        assert 'lightning_flash: ["#79500a"' in script
        assert '["lightning_glass", "natural_thunder"].includes(instrument)' in script
        assert "cue.volume ?? 1" in script
        assert "baseScale * visualVolume" in script
        assert 'return "Storm Outlook"' in script
        assert 'capeUnit: "ft²/s²"' in script
        assert 'showersUnit: "in"' in script
        assert 'gustUnit: "mph"' in script
        assert 'details.textContent = `Wind gusts ${measurements.gust.toFixed(0)} ${measurements.gustUnit}`' in script
        assert "details.textContent = `Showers" not in script
        assert 'label: "Weak"' in script
        assert 'label: "Modest"' in script
        assert 'label: "Substantial"' in script
        assert 'label: "Strong"' in script
        assert "storm-cape-pill" in script
        assert 'label: "Minimal"' in script
        assert 'label: "Small"' in script
        assert 'label: "Moderate"' in script
        assert 'label: "Large"' in script
        assert 'label: "Very Large"' in script
        assert 'label: "Extreme"' in script
        assert "swell-height-pill" in script
        assert "LIGHTNING_INTENSITY_HOLD_MS = 3000" in script
        assert 'label: "Faint"' in script
        assert 'label: "Intense"' in script
        assert "lightning-intensity-pill" in script
        assert "element.append(pill, observation)" in script
        assert "lightning-characteristics-details" not in script
        assert "flash_energy_j" in script
        assert "flash_duration_ms" in script
        assert 'areaUnit: "mi²"' in script
        assert 'durationUnit: "s"' in script
        assert 'return `${footPounds.toExponential(1)} ft·lbf`' in script
        assert 'return `${miles.toFixed(1)} mi`' in script
        assert "displayedLightningUnits !== selectedUnits" in script
        assert 'label: "Micro"' in script
        assert 'label: "Minor"' in script
        assert 'label: "Light"' in script
        assert 'label: "Major"' in script
        assert 'label: "Great"' in script
        assert "earthquake-magnitude-pill" in script
        assert 'return "Lightning R2D2"' in script
        assert 'return "Natural Thunder"' in script
        assert "updateBackgroundStatus(null)" in script
        stylesheet = client.get("/static/app.css").text
        assert ".storm-cape--weak" in stylesheet
        assert ".storm-cape--strong" in stylesheet
        assert ".swell-height--minimal" in stylesheet
        assert ".swell-height--extreme" in stylesheet
        assert ".lightning-intensity--faint" in stylesheet
        assert ".lightning-intensity--intense" in stylesheet
        assert ".earthquake-magnitude--micro" in stylesheet
        assert ".earthquake-magnitude--great" in stylesheet
        assert ".status-card--background { --status-accent: #6ab5bd; }" in stylesheet
        assert ".status-card--event { --status-accent: #e5aa2b; }" in stylesheet
        assert ".status-card--earthquake { --status-accent: #b98258; }" in stylesheet
        assert ".metrics small.forecast-characteristics," in stylesheet
        assert ".metrics small.lightning-characteristics," in stylesheet
        assert ".metrics small.earthquake-characteristics" in stylesheet
        assert "flex-direction: column; gap: 8px" in stylesheet
        assert "font-size: .76rem !important" in stylesheet
        assert ".recovery-toast-stack" in stylesheet
        assert ".recovery-toast--error" in stylesheet
        assert ".map-system-location-marker { fill: #53b86b;" in stylesheet
        assert "backgroundCharacteristics" in script
        assert "updateLastEventStatus" in script
        assert "updateLastEarthquakeStatus" in script
        assert 'return `${type} · M${magnitude} · ${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)}`' in script
        assert '!["lightning_glass", "natural_thunder"].includes(select.value)' in script
        assert "lightning_sample_rate: Number(lightningSampleSliders[0].value)" in script
        assert "activateWorkspacePane" in script
        assert "activateAppView" in script
        assert 'APP_VIEW_STORAGE_KEY = "gaia-scape-app-view"' in script
        assert 'request("/api/settings/view"' in script
        assert "activateAppView(savedAppView(), true)" in script
        assert "saveAppView(selectedName)" in script
        assert "projectCoordinates" in script
        assert "inverseProjectCoordinates" in script
        assert "mapProjectionBoundary" in script
        assert 'class: "map-system-location-marker"' in script
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
        assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in stylesheet
        assert "grid-template-columns: minmax(7.5rem, 1fr) 6rem" in stylesheet
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


def test_system_location_api_returns_normalized_location(tmp_path):
    app = create_app(
        tmp_path,
        auto_capture=False,
        usgs_client=FakeUsgs(),
        geoip_resolver=FakeGeoIpResolver(),
    )

    with TestClient(app) as client:
        response = client.get("/api/system-location")

    assert response.status_code == 200
    assert response.json() == {
        "location": {
            "name": "Test City, Test Region",
            "latitude": 39.7392,
            "longitude": -104.9903,
            "timezone": "America/Denver",
            "provider": "test",
        }
    }


def test_selected_app_view_persists_across_restart(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    with TestClient(app) as client:
        response = client.put("/api/settings/view", json={"view": "map"})

    assert response.status_code == 200
    assert response.json() == {"view": "map"}
    assert '"app_view": "map"' in (tmp_path / "config.json").read_text(
        encoding="utf-8"
    )

    restarted_app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    with TestClient(restarted_app) as client:
        home = client.get("/")
        invalid = client.put("/api/settings/view", json={"view": "globe"})

    assert invalid.status_code == 422
    assert restarted_app.state.config.app_view == "map"
    assert '<body data-initial-app-view="map">' in home.text
    assert '<body data-app-view=' not in home.text
    assert 'class="view-option is-active" id="mapViewButton"' in home.text
    assert 'id="dashboardView" data-app-view="dashboard" hidden' in home.text
    assert 'id="mapView" data-app-view="map" aria-labelledby="mapViewTitle">' in home.text


def test_open_meteo_message_clears_after_provider_recovers(tmp_path):
    marine = RecoveringMarine()
    app = create_app(
        tmp_path,
        auto_capture=False,
        usgs_client=FakeUsgs(),
        marine_client=marine,
    )
    app.state.config.enabled_sources = ["open_meteo_marine"]

    with pytest.raises(RuntimeError, match="temporarily limiting requests"):
        asyncio.run(app.state.service.capture_once())
    failed_status = asyncio.run(app.state.service.status())
    recovered = asyncio.run(app.state.service.capture_once())
    recovered_status = asyncio.run(app.state.service.status())

    assert failed_status["capture"]["last_error"]
    assert recovered["received"] == 1
    assert recovered_status["capture"]["last_error"] == ""
    health = recovered_status["sources"]["health"]["open_meteo_marine"]
    assert health["state"] == "online"
    assert health["notify"] is True
    assert "recovered" in health["message"]


def test_provider_failure_backs_off_and_reports_offline_status(tmp_path, monkeypatch):
    class OfflineUsgs:
        def __init__(self):
            self.calls = 0

        def fetch(self):
            self.calls += 1
            raise OSError("network unavailable")

    source = OfflineUsgs()
    app = create_app(tmp_path, auto_capture=False, usgs_client=source)
    app.state.config.enabled_sources = ["usgs"]
    monkeypatch.setattr(service.random, "uniform", lambda _start, _end: 0.0)

    with pytest.raises(RuntimeError, match="network unavailable"):
        asyncio.run(app.state.service.capture_once(respect_backoff=True))
    skipped = asyncio.run(app.state.service.capture_once(respect_backoff=True))
    status = asyncio.run(app.state.service.status())

    health = status["sources"]["health"]["usgs"]
    assert source.calls == 1
    assert skipped["received"] == 0
    assert health["state"] == "offline"
    assert health["consecutive_failures"] == 1
    assert health["retry_seconds"] > 0
    assert health["using_fallback"] is False
    assert status["sources"]["recovery"]["state"] == "offline"
    assert "All enabled environmental data sources are offline" in (
        status["sources"]["recovery"]["message"]
    )


def test_provider_retry_delay_grows_exponentially_with_a_bound(tmp_path, monkeypatch):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    clock = [1000.0]
    monkeypatch.setattr(service.time, "time", lambda: clock[0])
    monkeypatch.setattr(service.random, "uniform", lambda _start, _end: 0.0)

    app.state.service._mark_source_failure("usgs", OSError("offline"))
    first_retry = app.state.service._source_recovery["usgs"].retry_at
    clock[0] += 1.0
    app.state.service._mark_source_failure("usgs", OSError("still offline"))
    second_retry = app.state.service._source_recovery["usgs"].retry_at

    assert first_retry == 1060.0
    assert second_retry == 1121.0


def test_recent_persisted_forecast_degrades_instead_of_going_offline(
    tmp_path, monkeypatch
):
    now = time.time()
    app = create_app(tmp_path, auto_capture=False, marine_client=RecoveringMarine())
    app.state.config.enabled_sources = ["open_meteo_marine"]
    app.state.service.store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "cached", "ocean_swell", now,
                latitude=1, longitude=2, strength=0.4,
                traits={"place": "Cached Coast"},
            ),
        ),
        ingested_at=now,
    )
    app.state.service._source_recovery["open_meteo_marine"].last_data_at = now
    monkeypatch.setattr(service.random, "uniform", lambda _start, _end: 0.0)

    with pytest.raises(RuntimeError):
        asyncio.run(app.state.service.capture_once(respect_backoff=True))
    health = asyncio.run(app.state.service.status())["sources"]["health"]

    assert health["open_meteo_marine"]["state"] == "degraded"
    assert health["open_meteo_marine"]["using_fallback"] is True


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


def test_ambient_rotation_ignores_unrelated_event_query_volume(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    now = time.time()
    unrelated = tuple(
        GaiaEvent(
            "noaa_glm", f"flash-{index}", "lightning_flash", now - 1000 + index / 10,
        )
        for index in range(5001)
    )
    backgrounds = tuple(
        GaiaEvent(
            "open_meteo_marine", f"{slug}-swell", "ocean_swell", now,
            traits={"place": place, "swell_period_s": 10.0},
        )
        for slug, place in (
            ("punta", "Punta de Lobos, Chile"),
            ("raglan", "Raglan, New Zealand"),
            ("shonan", "Shōnan, Japan"),
        )
    )
    app.state.service.store.add_events((*unrelated, *backgrounds))
    played = []
    app.state.service.renderer.update_layer = (
        lambda cue, instrument=None: played.append(cue.event.traits["place"])
    )

    for _cycle in backgrounds:
        asyncio.run(app.state.service.play_next_ambient_layers())

    assert played == [
        "Punta de Lobos, Chile",
        "Raglan, New Zealand",
        "Shōnan, Japan",
    ]


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
    app.state.service._record_emitted_cue(
        ScoreCue(
            0,
            GaiaEvent(
                "noaa_glm", "later-flash", "lightning_flash", now + 1,
                traits={"place": "Atlantic flash"},
            ),
            60,
            80,
        ),
        "lightning_glass",
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
    assert status["cues"]["latest_background_event"]["event_id"] == "bundoran-swell-same"
    assert status["cues"]["latest_event"]["event_id"] == "later-flash"
    assert status["cues"]["latest_earthquake_event"]["event_id"] == "later-quake"
    cues = asyncio.run(app.state.service.emitted_cues(after=0))["cues"]
    assert [cue["history_updated"] for cue in cues[:2]] == [True, False]


def test_status_restores_latest_earthquake_without_an_emitted_cue(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    assert app.state.service._emitted_cues.maxlen == 10000
    quake = GaiaEvent(
        "usgs", "retained-quake", "earthquake", 1234,
        latitude=12.3, longitude=45.6,
        traits={"place": "Retained Ridge", "magnitude": 4.2},
    )
    app.state.service.store.add_events((quake,))

    status = asyncio.run(app.state.service.status())

    assert status["cues"]["latest_earthquake_event"]["event_id"] == "retained-quake"


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
    assert 'id="backgroundSoundsTitle" data-status-field="background-title">Storm Outlook</span>' in home.text
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


def test_forecast_location_editor_renders_and_persists_catalogs(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    ocean = [dict(location) for location in app.state.config.ocean_swell_locations]
    storm = [dict(location) for location in app.state.config.storm_outlook_locations]
    ocean[0] = {
        "name": "Custom Gulf of Maine",
        "latitude": 43.5,
        "longitude": -68.5,
    }

    with TestClient(app) as client:
        home = client.get("/")
        response = client.put(
            "/api/settings/locations",
            json={
                "ocean_swell_locations": ocean,
                "storm_outlook_locations": storm,
            },
        )

    assert 'data-settings-pane="locations"' in home.text
    assert 'id="forecastLocationMap"' in home.text
    assert 'id="forecastLocationList"' in home.text
    assert response.status_code == 200
    assert response.json()["ocean_swell_locations"][0]["name"] == "Custom Gulf of Maine"
    assert app.state.service.marine.locations[0][0].startswith("swell-1-")
    assert app.state.service.marine.locations[0][1:] == (
        "Custom Gulf of Maine", 43.5, -68.5,
    )
    saved = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert '"name": "Custom Gulf of Maine"' in saved


def test_forecast_location_settings_reject_incomplete_catalog(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    original = [dict(location) for location in app.state.config.ocean_swell_locations]

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/locations",
            json={
                "ocean_swell_locations": original[:-1],
                "storm_outlook_locations": app.state.config.storm_outlook_locations,
            },
        )

    assert response.status_code == 422
    assert app.state.config.ocean_swell_locations == original


def test_forecast_location_move_immediately_prunes_old_map_record(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "gold-coast-old", "ocean_swell", time.time(),
                latitude=-28.04, longitude=153.62,
                traits={"place": "Gold Coast, Australia"},
            ),
        )
    )
    ocean = [dict(location) for location in app.state.config.ocean_swell_locations]
    ocean[7]["latitude"] = -31.32
    ocean[7]["longitude"] = 115.29

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/locations",
            json={
                "ocean_swell_locations": ocean,
                "storm_outlook_locations": app.state.config.storm_outlook_locations,
            },
        )
        events = client.get("/api/events")

    assert response.status_code == 200
    assert response.json()["pruned"] == 1
    assert events.json()["events"] == []


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


def test_natural_thunder_preview_routes_to_lightning(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue, instrument)) or True
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/instruments/preview",
            json={"instrument": "natural_thunder", "volume": 0.4},
        )
        history = client.get("/api/events").json()["events"]

    assert response.json() == {
        "played": True,
        "instrument": "natural_thunder",
        "kind": "lightning_flash",
    }
    assert played[0][0].kind == "lightning_flash"
    assert played[0][1] == "natural_thunder"
    assert history == []


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


def test_strong_live_earthquake_uses_seven_second_cue(tmp_path):
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.apply_audio_settings(
        ["usgs"],
        {
            "event_1": "earthquake",
            "event_2": "none",
            "event_3": "none",
            "background": "none",
        },
    )
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append((cue, instrument)) or True
    )

    asyncio.run(
        app.state.service._play_live_event(
            GaiaEvent("usgs", "strong-quake", "earthquake", time.time(), strength=1.0)
        )
    )

    assert len(played) == 1
    assert played[0][0].duration == 7.0
    assert played[0][1] == "earthquake"


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


def test_glm_replays_last_flash_field_when_no_new_granule_arrives(
    tmp_path, caplog, monkeypatch
):
    now = time.time()
    flashes = (
        GaiaEvent(
            "noaa_glm", "repeat-east", "lightning_flash", now,
            latitude=12, longitude=-72, strength=0.7,
        ),
        GaiaEvent(
            "noaa_glm", "repeat-west", "lightning_flash", now + 0.2,
            latitude=28, longitude=-140, strength=0.8,
        ),
    )
    glm = FakeGlm(flashes, raw_count=2)
    app = create_app(
        tmp_path, auto_capture=False, usgs_client=FakeUsgs(), glm_client=glm
    )
    app.state.config.live_mode = "continuous"
    monkeypatch.setattr(service, "GLM_SONIFICATION_TIME_SCALE", 0.0)
    played = []
    app.state.service.renderer.play = (
        lambda cue, instrument=None: played.append(cue.event.event_id) or True
    )

    async def capture_new_then_unchanged():
        await app.state.service.capture_glm_once()
        await app.state.service._glm_sonification_task
        glm.events = ()
        glm.last_raw_flash_count = 0
        glm.last_granule_count = 0
        with caplog.at_level("INFO", logger="uvicorn.error"):
            result = await app.state.service.capture_glm_once()
        await app.state.service._glm_sonification_task
        return result, await app.state.service.status()

    result, status = asyncio.run(capture_new_then_unchanged())

    assert result == {"received": 0, "raw_flashes": 0, "inserted": 0, "pruned": 0}
    assert played == ["repeat-east", "repeat-west", "repeat-east", "repeat-west"]
    assert status["glm"]["replaying_cached_field"] is True
    assert status["glm"]["cached_flash_count"] == 2
    assert (
        "NOAA GLM unchanged: replaying previous field with 2 sonified flashes"
        in caplog.text
    )


def test_recent_glm_field_is_restored_from_persistent_history(tmp_path):
    now = time.time()
    first = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    first.state.service.store.add_events(
        (
            GaiaEvent(
                "noaa_glm", "persisted-a", "lightning_flash", now - 5,
                latitude=10, longitude=-60, strength=0.5,
            ),
            GaiaEvent(
                "noaa_glm", "persisted-b", "lightning_flash", now,
                latitude=11, longitude=-61, strength=0.6,
            ),
        ),
        ingested_at=now,
    )

    restarted = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())

    assert [
        event.event_id
        for event in restarted.state.service._last_glm_sonification_events
    ] == ["persisted-a", "persisted-b"]


def test_continuous_mode_stops_forecast_layers_after_fallback_expires(tmp_path):
    old = time.time() - service.FORECAST_FALLBACK_MAX_AGE_SECONDS - 1
    app = create_app(tmp_path, auto_capture=False, usgs_client=FakeUsgs())
    app.state.service.store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "stale-swell", "ocean_swell", old,
                latitude=1, longitude=2, strength=0.5,
                traits={"place": "Stale Coast"},
            ),
        )
    )
    app.state.service.renderer.active_layers.add("ocean_swell")
    stopped = []
    app.state.service.renderer.stop_layer = (
        lambda kind: stopped.append(kind) or True
    )

    selected = asyncio.run(app.state.service.play_next_ambient_layers())

    assert selected == ()
    assert "ocean_swell" in stopped


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
