from datetime import datetime, timezone

from gaia_scape_host.open_meteo import parse_marine_document, parse_storm_document


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
