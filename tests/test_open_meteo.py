"""Tests for Open-Meteo forecast normalization.

Representative marine and atmospheric documents verify that modeled swells,
tide turns, and meaningful storm outlooks become normalized Gaia events.
"""

import json
import urllib.error
from datetime import datetime, timezone

import pytest

from gaia_scape_host import open_meteo
from gaia_scape_host.open_meteo import (
    OpenMeteoMarineClient,
    parse_marine_document,
    parse_storm_document,
)


LOCATION = (("test-coast", "Test Coast", 10.0, 20.0),)
TIMES = ["2026-08-23T00:00", "2026-08-23T01:00", "2026-08-23T02:00"]
NOW = datetime(2026, 8, 23, 1, tzinfo=timezone.utc).timestamp()


def test_marine_document_emits_swell_and_modeled_high_tide_turn():
    document = {
        "latitude": 10.1,
        "longitude": 20.1,
        "hourly": {
            "time": TIMES,
            "wave_height": [2.0, 3.2, 2.8],
            "swell_wave_height": [1.8, 3.0, 2.6],
            "swell_wave_period": [10.0, 14.0, 12.0],
            "swell_wave_direction": [220.0, 225.0, 230.0],
            "sea_level_height_msl": [0.4, 0.9, 0.5],
        },
    }

    events = parse_marine_document(document, LOCATION, now=NOW)

    assert [event.kind for event in events] == ["ocean_swell", "tide_turn"]
    swell, tide = events
    assert swell.provider == "open_meteo_marine"
    assert swell.traits["swell_height_m"] == 3.0
    assert swell.traits["swell_period_s"] == 14.0
    assert swell.strength == 0.5
    assert tide.traits["tide_state"] == "high"
    assert tide.traits["modeled"] is True


def test_marine_document_does_not_invent_a_tide_turn_on_a_slope():
    document = {
        "hourly": {
            "time": TIMES,
            "wave_height": [1.0, 1.1, 1.2],
            "swell_wave_height": [0.8, 0.9, 1.0],
            "swell_wave_period": [8.0, 8.0, 8.0],
            "swell_wave_direction": [90.0, 90.0, 90.0],
            "sea_level_height_msl": [0.1, 0.2, 0.3],
        },
    }

    events = parse_marine_document(document, LOCATION, now=NOW)

    assert [event.kind for event in events] == ["ocean_swell"]


def test_storm_document_requires_meaningful_forecast_potential():
    active = {
        "hourly": {
            "time": TIMES,
            "cape": [400.0, 1200.0, 900.0],
            "weather_code": [3, 95, 80],
            "showers": [0.0, 4.0, 2.0],
            "wind_gusts_10m": [20.0, 70.0, 50.0],
        },
    }
    quiet = {
        "hourly": {
            "time": TIMES,
            "cape": [100.0, 250.0, 300.0],
            "weather_code": [3, 3, 3],
            "showers": [0.0, 0.0, 0.0],
            "wind_gusts_10m": [10.0, 15.0, 12.0],
        },
    }

    events = parse_storm_document(active, LOCATION, now=NOW)

    assert len(events) == 1
    assert events[0].kind == "storm_potential"
    assert events[0].traits["forecast"] is True
    assert events[0].traits["cape_jkg"] == 1200.0
    assert parse_storm_document(quiet, LOCATION, now=NOW) == ()


def test_open_meteo_client_caches_hourly_forecast_between_poll_cycles(monkeypatch):
    document = {
        "hourly": {
            "time": TIMES,
            "wave_height": [1.0, 1.1, 1.2],
            "swell_wave_height": [0.8, 0.9, 1.0],
            "swell_wave_period": [8.0, 8.0, 8.0],
            "swell_wave_direction": [90.0, 90.0, 90.0],
            "sea_level_height_msl": [0.1, 0.2, 0.3],
        }
    }
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(document).encode("utf-8")

    monkeypatch.setattr(
        open_meteo.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: calls.append(True) or Response(),
    )
    clock = [100.0]
    monkeypatch.setattr(open_meteo.time, "monotonic", lambda: clock[0])
    client = OpenMeteoMarineClient()
    client.locations = LOCATION

    first = client.fetch()
    clock[0] += 3599.0
    second = client.fetch()
    clock[0] += 1.0
    refreshed = client.fetch()

    assert first is second
    assert tuple(event.as_dict() for event in first) == tuple(
        event.as_dict() for event in refreshed
    )
    assert len(calls) == 2


def test_open_meteo_429_uses_stale_cache_and_starts_cooldown(monkeypatch):
    client = OpenMeteoMarineClient()
    client._cached_events = ("cached",)
    client._cache_updated_at = -3000.0
    client._has_cache = True
    clock = [1000.0]
    calls = []

    def rate_limited(*_args, **_kwargs):
        calls.append(True)
        raise urllib.error.HTTPError(
            client.url, 429, "Too Many Requests", {"Retry-After": "120"}, None
        )

    monkeypatch.setattr(open_meteo.urllib.request, "urlopen", rate_limited)
    monkeypatch.setattr(open_meteo.time, "monotonic", lambda: clock[0])

    assert client.fetch() == ("cached",)
    clock[0] = 1050.0
    assert client.fetch() == ("cached",)
    assert len(calls) == 1


def test_open_meteo_429_without_cache_has_a_readable_error(monkeypatch):
    client = OpenMeteoMarineClient()

    def rate_limited(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            client.url, 429, "Too Many Requests", {}, None
        )

    monkeypatch.setattr(open_meteo.urllib.request, "urlopen", rate_limited)

    with pytest.raises(RuntimeError, match="temporarily limiting requests"):
        client.fetch()
