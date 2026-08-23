from gaia_rhythms.events import GaiaEvent
from gaia_rhythms_host.capture import EventStore


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


def test_store_prunes_only_events_before_cutoff(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    store.initialize()
    store.add_events((event("old", 100), event("keep", 200)))

    assert store.prune_before(150) == 1
    assert [item.event_id for item in store.events_since(0)] == ["keep"]


def test_store_migrates_legacy_table_without_losing_events(tmp_path):
    import sqlite3

    database = tmp_path / "gaia_rhythms.sqlite3"
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
