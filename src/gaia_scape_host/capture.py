"""SQLite-backed event capture and replay history.

The event store owns schema migration, deduplication, retention, and ordered
queries while keeping normalized event semantics independent of providers.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from gaia_scape.events import GaiaEvent


class EventStore:
    """Persist normalized events with provider-level idempotency."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self) -> None:
        """Create the event schema when needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "earth_events" in tables and "gaia_events" not in tables:
                connection.execute("ALTER TABLE earth_events RENAME TO gaia_events")
                connection.execute("DROP INDEX IF EXISTS idx_earth_events_occurred")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gaia_events (
                    provider TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    ingested_at REAL NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    strength REAL NOT NULL,
                    traits_json TEXT NOT NULL,
                    PRIMARY KEY (provider, event_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_gaia_events_occurred "
                "ON gaia_events (occurred_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_gaia_events_kind_occurred "
                "ON gaia_events (kind, occurred_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS retained_status_events (
                    kind TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    strength REAL NOT NULL,
                    traits_json TEXT NOT NULL
                )
                """
            )
            latest_earthquake = connection.execute(
                """
                SELECT kind, provider, event_id, occurred_at, latitude,
                       longitude, strength, traits_json
                FROM gaia_events
                WHERE kind = 'earthquake'
                ORDER BY occurred_at DESC, provider DESC, event_id DESC
                LIMIT 1
                """
            ).fetchone()
            if latest_earthquake is not None:
                connection.execute(
                    """
                    INSERT INTO retained_status_events (
                        kind, provider, event_id, occurred_at, latitude,
                        longitude, strength, traits_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(kind) DO UPDATE SET
                        provider = excluded.provider,
                        event_id = excluded.event_id,
                        occurred_at = excluded.occurred_at,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        strength = excluded.strength,
                        traits_json = excluded.traits_json
                    WHERE excluded.occurred_at > retained_status_events.occurred_at
                    """,
                    latest_earthquake,
                )
            connection.commit()

    def add_events(self, events, ingested_at=None) -> int:
        """Insert unseen events and return the number newly stored."""
        return len(self.add_new_events(events, ingested_at=ingested_at))

    def add_new_events(self, events, ingested_at=None):
        """Insert unseen events and return the event objects actually stored."""
        events = tuple(events)
        if not events:
            return ()
        inserted_events = []
        captured_at = float(ingested_at if ingested_at is not None else time.time())
        with closing(sqlite3.connect(self.path)) as connection:
            for event in events:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO gaia_events (
                        provider, event_id, kind, occurred_at, ingested_at,
                        latitude, longitude, strength, traits_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.provider, event.event_id, event.kind, event.timestamp,
                        captured_at, event.latitude, event.longitude, event.strength,
                        json.dumps(event.traits, separators=(",", ":"), sort_keys=True),
                    ),
                )
                if cursor.rowcount == 1:
                    inserted_events.append(event)
                if event.kind == "earthquake":
                    connection.execute(
                        """
                        INSERT INTO retained_status_events (
                            kind, provider, event_id, occurred_at, latitude,
                            longitude, strength, traits_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(kind) DO UPDATE SET
                            provider = excluded.provider,
                            event_id = excluded.event_id,
                            occurred_at = excluded.occurred_at,
                            latitude = excluded.latitude,
                            longitude = excluded.longitude,
                            strength = excluded.strength,
                            traits_json = excluded.traits_json
                        WHERE excluded.occurred_at > retained_status_events.occurred_at
                        """,
                        (
                            event.kind, event.provider, event.event_id,
                            event.timestamp, event.latitude, event.longitude,
                            event.strength,
                            json.dumps(
                                event.traits, separators=(",", ":"), sort_keys=True
                            ),
                        ),
                    )
            connection.commit()
        return tuple(inserted_events)

    def retained_status_event(self, kind: str) -> GaiaEvent | None:
        """Return the event retained indefinitely for a status display."""
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                """
                SELECT provider, event_id, kind, occurred_at, latitude,
                       longitude, strength, traits_json
                FROM retained_status_events
                WHERE kind = ?
                """,
                (str(kind),),
            ).fetchone()
        return None if row is None else _event_from_row(row)

    def events_since(self, since_timestamp: float, limit: int = 5000):
        """Return events on or after a timestamp in occurrence order."""
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT provider, event_id, kind, occurred_at, latitude,
                       longitude, strength, traits_json
                FROM gaia_events
                WHERE occurred_at >= ?
                ORDER BY occurred_at ASC, provider ASC, event_id ASC
                LIMIT ?
                """,
                (float(since_timestamp), max(1, min(20000, int(limit)))),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def events_of_kinds_since(self, kinds, since_timestamp: float, limit: int = 5000):
        """Return only the requested event kinds on or after a timestamp."""
        kinds = tuple(dict.fromkeys(str(kind) for kind in kinds))
        if not kinds:
            return ()
        placeholders = ",".join("?" for _kind in kinds)
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                f"""
                SELECT provider, event_id, kind, occurred_at, latitude,
                       longitude, strength, traits_json
                FROM gaia_events
                WHERE kind IN ({placeholders}) AND occurred_at >= ?
                ORDER BY occurred_at ASC, provider ASC, event_id ASC
                LIMIT ?
                """,
                (
                    *kinds,
                    float(since_timestamp),
                    max(1, min(20000, int(limit))),
                ),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def latest_events_by_kind_and_place(self, kinds):
        """Return the newest requested event for each normalized place."""
        kinds = tuple(dict.fromkeys(str(kind) for kind in kinds))
        if not kinds:
            return ()
        placeholders = ",".join("?" for _kind in kinds)
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                f"""
                WITH ranked_events AS (
                    SELECT provider, event_id, kind, occurred_at, latitude,
                           longitude, strength, traits_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY kind, json_extract(traits_json, '$.place')
                               ORDER BY occurred_at DESC, provider DESC, event_id DESC
                           ) AS place_rank
                    FROM gaia_events
                    WHERE kind IN ({placeholders})
                )
                SELECT provider, event_id, kind, occurred_at, latitude,
                       longitude, strength, traits_json
                FROM ranked_events
                WHERE place_rank = 1
                ORDER BY kind ASC, json_extract(traits_json, '$.place') ASC
                """,
                kinds,
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def events_by_keys(self, keys):
        """Return stored events matching provider and event ID pairs."""
        keys = tuple(
            dict.fromkeys(
                (str(provider), str(event_id)) for provider, event_id in keys
            )
        )
        if not keys:
            return ()
        with closing(sqlite3.connect(self.path)) as connection:
            rows = []
            for provider, event_id in keys:
                row = connection.execute(
                    """
                    SELECT provider, event_id, kind, occurred_at, latitude,
                           longitude, strength, traits_json
                    FROM gaia_events
                    WHERE provider = ? AND event_id = ?
                    """,
                    (provider, event_id),
                ).fetchone()
                if row is not None:
                    rows.append(row)
        return tuple(_event_from_row(row) for row in rows)

    def count(self, excluded_kinds=()) -> int:
        """Return the total number of captured events."""
        excluded_kinds = tuple(str(kind) for kind in excluded_kinds)
        with closing(sqlite3.connect(self.path)) as connection:
            if excluded_kinds:
                placeholders = ",".join("?" for _kind in excluded_kinds)
                row = connection.execute(
                    f"SELECT COUNT(*) FROM gaia_events WHERE kind NOT IN ({placeholders})",
                    excluded_kinds,
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) FROM gaia_events").fetchone()
        return int(row[0])

    def latest_timestamp(self, excluded_kinds=()):
        """Return the newest occurrence timestamp, if any."""
        excluded_kinds = tuple(str(kind) for kind in excluded_kinds)
        with closing(sqlite3.connect(self.path)) as connection:
            if excluded_kinds:
                placeholders = ",".join("?" for _kind in excluded_kinds)
                row = connection.execute(
                    f"SELECT MAX(occurred_at) FROM gaia_events "
                    f"WHERE kind NOT IN ({placeholders})",
                    excluded_kinds,
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT MAX(occurred_at) FROM gaia_events"
                ).fetchone()
        return None if row[0] is None else float(row[0])

    def latest_ingested_at_for_provider(self, provider: str):
        """Return when a provider most recently supplied stored data."""
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT MAX(ingested_at) FROM gaia_events WHERE provider = ?",
                (str(provider),),
            ).fetchone()
        return None if row[0] is None else float(row[0])

    def prune_before(self, cutoff_timestamp: float) -> int:
        """Delete history older than the retention cutoff."""
        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute(
                "DELETE FROM gaia_events WHERE occurred_at < ?", (float(cutoff_timestamp),)
            )
            deleted = cursor.rowcount
            connection.commit()
        return max(0, int(deleted))

    def prune_provider_places(self, provider: str, active_places) -> int:
        """Delete forecast records for locations retired by a provider catalog."""
        active_places = tuple(dict.fromkeys(str(place) for place in active_places))
        if not active_places:
            return 0
        placeholders = ",".join("?" for _place in active_places)
        with closing(sqlite3.connect(self.path)) as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM gaia_events
                WHERE provider = ?
                  AND json_extract(traits_json, '$.place') NOT IN ({placeholders})
                """,
                (str(provider), *active_places),
            )
            deleted = cursor.rowcount
            connection.commit()
        return max(0, int(deleted))

    def prune_provider_locations(
        self, provider: str, active_locations, coordinate_tolerance: float = 0.5
    ) -> int:
        """Delete forecast records that no longer match an active named coordinate."""
        active_locations = tuple(active_locations)
        if not active_locations:
            return 0
        normalized = tuple(
            (str(location[1]), float(location[2]), float(location[3]))
            for location in active_locations
        )
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                """
                SELECT provider, event_id, latitude, longitude,
                       json_extract(traits_json, '$.place')
                FROM gaia_events
                WHERE provider = ?
                """,
                (str(provider),),
            ).fetchall()
            retired = [
                (row[0], row[1])
                for row in rows
                if not any(
                    row[4] == name
                    and abs(row[2] - latitude) <= coordinate_tolerance
                    and abs(row[3] - longitude) <= coordinate_tolerance
                    for name, latitude, longitude in normalized
                )
            ]
            connection.executemany(
                "DELETE FROM gaia_events WHERE provider = ? AND event_id = ?",
                retired,
            )
            connection.commit()
        return len(retired)


def _event_from_row(row) -> GaiaEvent:
    try:
        traits = json.loads(row[7])
    except (TypeError, ValueError, json.JSONDecodeError):
        traits = {}
    return GaiaEvent(
        provider=row[0],
        event_id=row[1],
        kind=row[2],
        timestamp=row[3],
        latitude=row[4],
        longitude=row[5],
        strength=row[6],
        traits=traits,
    )
