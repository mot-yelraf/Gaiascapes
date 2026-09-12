"""Protect recording coverage, source geography, and the audit's failure reporting.

Default catalogs are checked against committed evidence without live requests.
Synthetic clients exercise the maintenance command's location-first traversal.
"""

import json
from pathlib import Path
import runpy

from gaiascapes.events import GaiaEvent
from gaiascapes_host.commons_birdsong import COMMONS_CATALOG
from gaiascapes_host.config import default_birdsong_locations, default_frog_locations
from gaiascapes_host.sanctsound import CATALOG, available_locations
from gaiascapes_host.xeno_canto import _within_region


ROOT = Path(__file__).parents[1]


def test_curated_birds_have_unique_recordings_within_their_documented_regions():
    for location in COMMONS_CATALOG:
        recordings = location["recordings"]
        assert len({recording["recording_id"] for recording in recordings}) == len(recordings)
        for recording in recordings:
            assert _within_region(recording, location)
            assert recording["source_url"].startswith("https://commons.wikimedia.org/")
            assert recording["location_evidence"]
            assert "Mystery mystery" not in recording["title"]


def test_all_default_catalogs_have_nineteen_verified_locations():
    report = json.loads((ROOT / "docs/recorded-catalogs-audit.json").read_text(encoding="utf-8"))
    assert len(report["catalogs"]) == 5
    for catalog in report["catalogs"]:
        rows = catalog["locations"]
        assert catalog["location_count"] == len(rows) == 19
        assert all(row["status"] in {"single", "multiple"} and not row["errors"] for row in rows)
        for row in rows:
            samples = row["samples"]
            assert len({sample["recording_id"] for sample in samples}) == min(2, row["eligible_recordings"])
        if catalog["provider"] == "xeno_canto":
            defaults = default_birdsong_locations() if catalog["kind"] == "birdsong" else default_frog_locations()
            for row, location in zip(rows, defaults):
                assert {key: row[key] for key in location} == location
                assert row["eligible_recordings"] >= 2
                assert all(_within_region(sample, location) for sample in row["samples"])
        elif catalog["provider"] == "wikimedia_commons":
            assert [row["id"] for row in rows] == [location["id"] for location in COMMONS_CATALOG]
            assert [row["eligible_recordings"] for row in rows] == [len(location["recordings"]) for location in COMMONS_CATALOG]
        else:
            sites = available_locations(catalog["kind"])
            assert [row["id"] for row in rows] == [site["id"] for site in sites]
            assert [row["eligible_recordings"] for row in rows] == [site["recording_count"] for site in sites]
    assert len({(clip["kind"], clip["object"]) for clip in CATALOG}) == len(CATALOG)


def test_audit_visits_locations_before_alternates_and_reports_failures():
    audit = runpy.run_path(str(ROOT / "scripts/audit_recorded_catalogs.py"))["audit_catalog"]
    calls = []

    class Client:
        def event_at(self, index):
            calls.append(index)
            if index == 2:
                raise RuntimeError("Archive unavailable")
            return GaiaEvent(provider="test", kind="birdsong", event_id=str(index), timestamp=0, traits={
                "recording_id": str(index), "title": "Bird", "source_url": "https://example.org/recording",
                "creator": "Recordist", "license": "CC0",
            })

    rows = audit(Client(), [{"name": "A"}, {"name": "B"}], [2, 1])
    assert calls == [0, 1, 2]
    assert rows[0]["status"] == "error"
    assert rows[0]["errors"] == ["Archive unavailable"]
    assert rows[1]["status"] == "single"
