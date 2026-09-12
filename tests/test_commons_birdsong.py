"""Tests for keyless Wikimedia Commons birdsong caching.

Synthetic API and audio responses verify licensing, local persistence, and
normalized attribution without relying on the external Commons service.
"""

import io
import json

import pytest

from gaiascapes_host.commons_birdsong import (
    BIRDSONG_LOCATIONS,
    COMMONS_CATALOG,
    CommonsBirdsongClient,
)


class FakeOpener:
    def __init__(self, document, audio=b"OggS-test-audio"):
        self.responses = [io.BytesIO(json.dumps(document).encode()), io.BytesIO(audio)]
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def commons_document(license_name="CC BY 4.0"):
    return {
        "query": {
            "pages": [
                {
                    "pageid": 42,
                    "title": "File:Forest birds.ogg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/forest-birds.ogg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Forest_birds.ogg",
                            "mime": "application/ogg",
                            "size": 14,
                            "extmetadata": {
                                "Artist": {"value": '<a href="/user">A. Recordist</a>'},
                                "LicenseShortName": {"value": license_name},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                            },
                        }
                    ],
                }
            ]
        }
    }


def test_catalog_has_nineteen_global_locations():
    assert len(BIRDSONG_LOCATIONS) == 19
    assert len({location[0] for location in BIRDSONG_LOCATIONS}) == 19
    assert any(location[2] < 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[2] > 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[3] < 0 for location in BIRDSONG_LOCATIONS)
    assert any(location[3] > 0 for location in BIRDSONG_LOCATIONS)


def test_client_discovers_downloads_and_reuses_cached_commons_audio(tmp_path):
    opener = FakeOpener(commons_document())
    client = CommonsBirdsongClient(tmp_path, opener=opener)

    first = client.event_at(0)
    second = client.event_at(0)

    assert first.kind == "birdsong"
    assert first.provider == "wikimedia_commons"
    assert first.traits["creator"] == "A. Recordist"
    assert first.traits["license"] == "CC BY 4.0"
    filename = first.traits["media_url"].rsplit("/", 1)[-1]
    assert filename.startswith("canada-churchill-XC")
    assert second.traits["commons_page_id"] == 42
    assert len(opener.requests) == 2
    assert (tmp_path / "media" / "birdsong" / filename).read_bytes() == b"OggS-test-audio"
    assert "key=" not in opener.requests[0][0].full_url
    assert opener.requests[0][0].get_header("Authorization") is None


def test_client_rejects_incompatible_or_missing_audio(tmp_path):
    opener = FakeOpener(commons_document("Copyrighted"))
    client = CommonsBirdsongClient(tmp_path, opener=opener)

    with pytest.raises(RuntimeError, match="no compatible audio"):
        client.event_at(0)


def test_commons_visits_all_locations_before_advancing_and_wraps_independently(tmp_path, monkeypatch):
    client = CommonsBirdsongClient(tmp_path)
    titles = []

    def discover(title):
        titles.append(title)
        return dict(title=title, creator="Recordist", license="CC BY 4.0", license_url="https://example.org/license",
                    source_url="https://example.org/source", page_id=len(titles), download_url="https://example.org/audio.ogg")

    def download(slug, metadata):
        path = client.media_dir / (slug + ".ogg")
        path.write_bytes(b"OggS-recording")
        return path

    monkeypatch.setattr(client, "_discover", discover)
    monkeypatch.setattr(client, "_download", download)
    count = len(COMMONS_CATALOG)
    for cycle in range(5):
        for index, location in enumerate(COMMONS_CATALOG):
            event = client.event_at(cycle * count + index)
            expected = location["recordings"][cycle % len(location["recordings"])]
            assert event.traits["region_id"] == location["id"]
            assert event.traits["recording_id"] == expected["recording_id"]
            assert (event.latitude, event.longitude) == (expected["latitude"], expected["longitude"])
    assert len(titles) == sum(len(location["recordings"]) for location in COMMONS_CATALOG)
