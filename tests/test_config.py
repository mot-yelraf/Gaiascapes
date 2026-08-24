import json

from gaia_rhythms_host.config import AppConfig, event_mappings_for_slots


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
        "background": "ocean_swell",
    }
    assert config.event_instruments["storm_potential"] == "none"


def test_none_is_available_for_every_instrument_role():
    mappings = event_mappings_for_slots(
        {"event_1": "none", "event_2": "none", "background": "none"}
    )

    assert set(mappings.values()) == {"none"}
