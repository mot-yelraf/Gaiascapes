"""Tests for configuration validation and migration.

The cases protect defaults, legacy instrument mappings, independent volume
controls, source migration, units, and lightning sampling bounds.
"""

import json

import pytest

from gaia_scape_host.config import (
    AppConfig,
    event_mappings_for_slots,
    validate_forecast_locations,
    volume_mappings_for_slots,
)


def test_legacy_instrument_mappings_migrate_to_three_roles(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "event_instruments": {
                    "earthquake": "tectonic_drone",
                    "ocean_swell": "ocean_swell",
                    "tide_turn": "ocean_swell",
                    "storm_potential": "storm_potential",
                }
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.instrument_slots() == {
        "event_1": "earthquake",
        "event_2": "tidal_bell",
        "event_3": "lightning_glass",
        "background": "ocean_swell",
    }
    assert config.event_instruments == {
        "event_1": "earthquake",
        "event_2": "tidal_bell",
        "event_3": "lightning_glass",
        "background": "ocean_swell",
    }


def test_event_slots_route_voices_by_their_environmental_source():
    config = AppConfig(
        event_instruments={
            "event_1": "tidal_bell",
            "event_2": "seismic_bells",
            "event_3": "earthquake",
            "background": "storm_potential",
        }
    )
    config.validate()

    assert config.instruments_for_event("earthquake") == (
        "seismic_bells", "earthquake"
    )
    assert config.instruments_for_event("tide_turn") == ("tidal_bell",)


def test_lightning_glass_routes_only_lightning_flashes():
    config = AppConfig(
        event_instruments={
            "event_1": "earthquake",
            "event_2": "tidal_bell",
            "event_3": "lightning_glass",
            "background": "storm_potential",
        }
    )
    config.validate()

    assert config.instruments_for_event("lightning_flash") == ("lightning_glass",)


def test_natural_thunder_routes_only_lightning_flashes():
    config = AppConfig(
        event_instruments={
            "event_1": "earthquake",
            "event_2": "tidal_bell",
            "event_3": "natural_thunder",
            "background": "storm_potential",
        }
    )
    config.validate()

    assert config.instruments_for_event("lightning_flash") == ("natural_thunder",)


def test_duplicate_event_slots_are_preserved():
    config = AppConfig(
        event_instruments={
            "event_1": "seismic_bells",
            "event_2": "seismic_bells",
            "event_3": "seismic_bells",
            "background": "none",
        }
    )
    config.validate()

    assert config.instruments_for_event("earthquake") == (
        "seismic_bells", "seismic_bells", "seismic_bells"
    )


def test_none_is_available_for_every_instrument_role():
    mappings = event_mappings_for_slots(
        {"event_1": "none", "event_2": "none", "background": "none"}
    )

    assert set(mappings.values()) == {"none"}


def test_units_are_validated_and_normalized():
    config = AppConfig(units=" Imperial ")
    config.validate()

    assert config.units == "imperial"

    config.units = "nautical"
    with pytest.raises(ValueError, match="Units must be metric or imperial"):
        config.validate()


def test_app_view_is_validated_and_normalized():
    config = AppConfig(app_view=" Map ")
    config.validate()

    assert config.app_view == "map"

    config.app_view = "globe"
    with pytest.raises(ValueError, match="App view must be dashboard or map"):
        config.validate()


def test_original_continuous_interval_migrates_to_23_seconds(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"continuous_interval_seconds": 12.0}), encoding="utf-8"
    )

    config = AppConfig.load(path)

    assert config.continuous_interval_seconds == 23.0


def test_existing_config_enables_glm_once_during_revision_migration(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"enabled_sources": ["usgs"]}), encoding="utf-8")

    config = AppConfig.load(path)
    config.save(path)
    reloaded = AppConfig.load(path)

    assert config.config_revision == 6
    assert config.enabled_sources == ["usgs", "noaa_glm"]
    assert reloaded.enabled_sources == ["usgs", "noaa_glm"]


def test_environment_port_overrides_are_not_persisted(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "http_host": "0.0.0.0",
                "http_port": 8768,
                "osc_host": "127.0.0.1",
                "osc_port": 57130,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GAIA_SCAPE_HTTP_HOST", "127.0.0.1")
    monkeypatch.setenv("GAIA_SCAPE_HTTP_PORT", "8878")
    monkeypatch.setenv("GAIA_SCAPE_OSC_HOST", "127.0.0.2")
    monkeypatch.setenv("GAIA_SCAPE_OSC_PORT", "57999")

    config = AppConfig.load(path)
    assert (config.http_host, config.http_port) == ("127.0.0.1", 8878)
    assert (config.osc_host, config.osc_port) == ("127.0.0.2", 57999)

    config.app_view = "map"
    config.save(path)
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert (persisted["http_host"], persisted["http_port"]) == ("0.0.0.0", 8768)
    assert (persisted["osc_host"], persisted["osc_port"]) == ("127.0.0.1", 57130)
    assert persisted["app_view"] == "map"


def test_forecast_location_catalogs_default_to_nineteen_and_persist(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig()
    config.ocean_swell_locations[0] = {
        "name": "Custom Atlantic",
        "latitude": 42.5,
        "longitude": -67.25,
    }
    config.save(path)

    reloaded = AppConfig.load(path)

    assert len(reloaded.ocean_swell_locations) == 19
    assert len(reloaded.storm_outlook_locations) == 19
    assert reloaded.ocean_swell_locations[0]["name"] == "Custom Atlantic"


def test_forecast_locations_require_nineteen_distinct_world_coordinates():
    locations = [
        {"name": f"Point {index}", "latitude": index - 9, "longitude": index * 5}
        for index in range(19)
    ]
    assert len(validate_forecast_locations(locations, "Test")) == 19

    with pytest.raises(ValueError, match="exactly 19"):
        validate_forecast_locations(locations[:-1], "Test")
    locations[1]["latitude"] = locations[0]["latitude"]
    locations[1]["longitude"] = locations[0]["longitude"]
    with pytest.raises(ValueError, match="distinct coordinates"):
        validate_forecast_locations(locations, "Test")


def test_glm_can_be_disabled_after_configuration_migration(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"config_revision": 2, "enabled_sources": ["usgs"]}),
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.enabled_sources == ["usgs"]


def test_eumetsat_source_requires_both_credentials():
    config = AppConfig(
        enabled_sources=["eumetsat_mtg_li"],
        eumetsat_consumer_key="consumer-key",
    )

    with pytest.raises(ValueError, match="Consumer Key and Consumer Secret"):
        config.validate()

    config.eumetsat_consumer_secret = "consumer-secret"
    config.validate()

    assert config.enabled_sources == ["eumetsat_mtg_li"]
    assert config.eumetsat_consumer_key == "consumer-key"
    assert config.eumetsat_consumer_secret == "consumer-secret"


def test_volume_slots_are_independent_and_zero_silences_only_that_slot():
    config = AppConfig(
        event_instruments={
            "event_1": "seismic_bells",
            "event_2": "seismic_bells",
            "event_3": "seismic_bells",
            "background": "ocean_swell",
        },
        instrument_volumes={
            "event_1": 0.8,
            "event_2": 0.0,
            "event_3": 0.3,
            "background": 0.6,
        },
    )
    config.validate()

    assert config.voices_for_event("earthquake") == (
        ("seismic_bells", 0.8), ("seismic_bells", 0.3)
    )
    assert config.volume_slots()["background"] == 0.6


def test_volume_slots_reject_out_of_range_values():
    with pytest.raises(ValueError, match="Event 1 volume must be 0..1"):
        volume_mappings_for_slots({"event_1": 1.2})


def test_lightning_sample_rate_defaults_to_one_and_is_bounded():
    config = AppConfig()
    config.validate()
    assert config.lightning_sample_rate == 1

    config.lightning_sample_rate = 99
    config.validate()
    assert config.lightning_sample_rate == 11
