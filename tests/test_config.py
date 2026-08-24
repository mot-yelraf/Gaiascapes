import json

import pytest

from gaia_rhythms_host.config import (
    AppConfig,
    event_mappings_for_slots,
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

    assert config.config_revision == 3
    assert config.enabled_sources == ["usgs", "noaa_glm"]
    assert reloaded.enabled_sources == ["usgs", "noaa_glm"]


def test_glm_can_be_disabled_after_configuration_migration(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"config_revision": 2, "enabled_sources": ["usgs"]}),
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.enabled_sources == ["usgs"]


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
