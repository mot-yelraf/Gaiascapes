"""Tests for SQLite event capture and history behavior.

The cases cover chronological retrieval, deduplication, retention pruning,
and migration from the legacy event-table schema.
"""

from gaia_scape.events import GaiaEvent
from gaia_scape_host.capture import EventStore


def event(event_id, timestamp):
    return GaiaEvent(
        "usgs",
        event_id,
        "earthquake",
        timestamp,
        latitude=40,
        longitude=-110,
        strength=0.5,
        traits={"magnitude": 3.0, "depth_km": 8.0},
    )


def test_store_deduplicates_and_replays_in_time_order(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()

    assert store.add_events((event("b", 200), event("a", 100))) == 2
    assert store.add_events((event("a", 100),)) == 0
    assert [item.event_id for item in store.add_new_events((event("c", 300), event("a", 100)))] == ["c"]
    assert store.count() == 3
    assert [item.event_id for item in store.events_since(50)] == ["a", "b", "c"]
    assert store.events_since(150)[0].traits["depth_km"] == 8.0
    assert store.latest_ingested_at_for_provider("usgs") is not None
    assert store.latest_ingested_at_for_provider("noaa_glm") is None


def test_store_prunes_only_events_before_cutoff(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()
    store.add_events((event("old", 100), event("keep", 200)))

    assert store.prune_before(150) == 1
    assert [item.event_id for item in store.events_since(0)] == ["keep"]


def test_store_prunes_retired_provider_places(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()
    store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "dakar", "ocean_swell", 100,
                traits={"place": "Dakar, Senegal"},
            ),
            GaiaEvent(
                "open_meteo_marine", "jamaica", "ocean_swell", 100,
                traits={"place": "Jamaica"},
            ),
            event("unrelated", 100),
        )
    )

    assert store.prune_provider_places("open_meteo_marine", ("Jamaica",)) == 1
    assert {item.event_id for item in store.events_since(0)} == {
        "jamaica", "unrelated",
    }
    assert store.prune_provider_places("open_meteo_marine", ()) == 0


def test_store_prunes_provider_place_moved_to_new_coordinates(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()
    store.add_events(
        (
            GaiaEvent(
                "open_meteo_marine", "gold-coast", "ocean_swell", 100,
                latitude=-28.04, longitude=153.62,
                traits={"place": "Gold Coast, Australia"},
            ),
            GaiaEvent(
                "open_meteo_marine", "maine", "ocean_swell", 100,
                latitude=44.21, longitude=-68.12,
                traits={"place": "East Coast of Maine, USA"},
            ),
        )
    )
    active = (
        ("swell-8-new", "Gold Coast, Australia", -31.32, 115.29),
        ("swell-19", "East Coast of Maine, USA", 44.20, -68.10),
    )

    assert store.prune_provider_locations("open_meteo_marine", active) == 1
    assert [item.event_id for item in store.events_since(0)] == ["maine"]


def test_store_queries_required_kinds_and_latest_places(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()
    store.add_events(
        (
            event("unrelated", 400),
            GaiaEvent(
                "open_meteo_marine", "raglan-old", "ocean_swell", 100,
                traits={"place": "Raglan, New Zealand"},
            ),
            GaiaEvent(
                "open_meteo_marine", "raglan-new", "ocean_swell", 300,
                traits={"place": "Raglan, New Zealand"},
            ),
            GaiaEvent(
                "open_meteo_marine", "shonan", "ocean_swell", 200,
                traits={"place": "Shōnan, Japan"},
            ),
            GaiaEvent(
                "open_meteo_marine", "raglan-tide", "tide_turn", 250,
                traits={"place": "Raglan, New Zealand"},
            ),
        )
    )

    latest = store.latest_events_by_kind_and_place(("ocean_swell",))
    assert [item.event_id for item in latest] == ["raglan-new", "shonan"]
    assert [item.event_id for item in store.events_of_kinds_since(("tide_turn",), 200)] == [
        "raglan-tide"
    ]


def test_store_migrates_legacy_table_without_losing_events(tmp_path):
    import sqlite3

    database = tmp_path / "gaia_scape.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE earth_events (
            provider TEXT NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL,
            occurred_at REAL NOT NULL, ingested_at REAL NOT NULL,
            latitude REAL NOT NULL, longitude REAL NOT NULL, strength REAL NOT NULL,
            traits_json TEXT NOT NULL, PRIMARY KEY (provider, event_id)
        )"""
    )
    connection.execute(
        "INSERT INTO earth_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("usgs", "legacy", "earthquake", 100.0, 101.0, 1.0, 2.0, 0.5, "{}"),
    )
    connection.commit()
    connection.close()

    store = EventStore(database)
    store.initialize()

    assert store.count() == 1
    assert store.events_since(0)[0].event_id == "legacy"
