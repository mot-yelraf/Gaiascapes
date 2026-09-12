"""Check mammal source controls and their fixed-site curation boundary."""

import xml.etree.ElementTree as ET
import pytest
from fastapi.testclient import TestClient

from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig
from gaiascapes_host.mammals import MAMMAL_KINDS, MAMMAL_LABELS


@pytest.mark.parametrize("kind", MAMMAL_KINDS)
def test_mammal_selection_persists_and_previews_bundled_audio(tmp_path, kind):
    config = AppConfig(system_location_enabled=False, enabled_sources=[], osc_enabled=False)
    config.save(tmp_path / "config.json")
    app = create_app(tmp_path, auto_capture=False)
    with TestClient(app) as client:
        assert not getattr(app.state.config, f"{kind}_enabled")
        payload = {f"{kind}_enabled": True, "instrument_slots": {
            "background": kind, "event_1": "none", "event_2": "none", "event_3": "none",
        }}
        response = client.put("/api/settings/audio", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()[f"{kind}_enabled"] is True
        saved = AppConfig.load(tmp_path / "config.json")
        assert saved.instrument_slots()["background"] == kind
        assert getattr(saved, f"{kind}_enabled") is True
        preview = client.post("/api/instruments/preview", json={"kind": kind, "instrument": kind})
        assert preview.status_code == 200, preview.text
        event = getattr(app.state.service, kind).event_at(0)
        media = client.get(event.traits["media_url"])
        assert media.status_code == 200
        assert media.headers["content-type"].startswith("audio/")
        assert len(media.content) > 1000
        for suffix in ("locations", "regions"):
            response = client.put("/api/settings/locations", json={f"{kind}_{suffix}": []})
            assert response.status_code == 422
            assert "fixed curated recording sites" in response.json()["detail"]
        response = client.put("/api/settings/audio", json={f"{kind}_enabled": False})
        assert response.status_code == 200
        preview = client.post("/api/instruments/preview", json={"kind": kind, "instrument": kind})
        assert preview.status_code == 422
        assert "Enable" in preview.json()["detail"]


def test_mammal_tiles_have_art_and_no_location_picker(tmp_path):
    AppConfig(system_location_enabled=False, enabled_sources=[], osc_enabled=False).save(tmp_path / "config.json")
    app = create_app(tmp_path, auto_capture=False)
    with TestClient(app) as client:
        home = client.get("/").text
        for kind, label in MAMMAL_LABELS.items():
            assert f'id="source_{kind}"' in home
            assert f'data-location-catalog="{kind}"' not in home
            assert home.index(f'id="source_{kind}"') < home.index('aria-label="Announce Recording"')
            image = client.get(f"/static/sound-{kind}.svg")
            assert image.status_code == 200
            root = ET.fromstring(image.content)
            assert root.find('{http://www.w3.org/2000/svg}title').text == label


def test_bundled_catalog_rotation_integrity_and_cache_repair(tmp_path):
    import hashlib
    import json
    from gaiascapes_host.mammals import CATALOG_PATH, MammalRecordingClient

    catalog = json.loads(CATALOG_PATH.read_text())["recordings"]
    assert {r["kind"] for r in catalog} == set(MAMMAL_KINDS)
    for kind in MAMMAL_KINDS:
        recording_client = MammalRecordingClient(tmp_path, kind)
        expected = [r for r in catalog if r["kind"] == kind]
        visited = []
        for index, recording in enumerate(expected):
            event = recording_client.event_at(index)
            visited.append(event.traits["recording_id"])
            assert (event.latitude, event.longitude) == (recording["latitude"], recording["longitude"])
            assert event.traits["common_name"] == recording["common_name"]
            assert event.traits["license"] in {"CC0", "CC BY 4.0"}
            assert event.traits["source_url"].startswith("https://freesound.org/")
            assert event.traits["wikipedia_title"]
            cached = recording_client.media_dir / recording["file"]
            assert hashlib.sha256(cached.read_bytes()).hexdigest() == recording["sha256"]
            cached.write_bytes(b"corrupted")
            recording_client.event_at(index)
            assert hashlib.sha256(cached.read_bytes()).hexdigest() == recording["sha256"]
        assert len(set(visited)) == recording_client.location_count
        assert recording_client.event_at(len(expected)).traits["recording_id"] == visited[0]


@pytest.mark.parametrize("kind", MAMMAL_KINDS)
def test_next_stages_mammal_without_audio_and_play_consumes_it(tmp_path, kind):
    import asyncio

    config = AppConfig(system_location_enabled=False, enabled_sources=[], osc_enabled=False,
                       live_mode="continuous", **{f"{kind}_enabled": True})
    config.event_instruments = {"background": kind, "event_1": "none", "event_2": "none", "event_3": "none"}
    config.save(tmp_path / "config.json")
    app = create_app(tmp_path, auto_capture=False)
    service = app.state.service

    async def exercise():
        event = await service.next_recording_image()
        assert event["kind"] == kind
        assert service._staged_recording[1].traits["media_url"] == event["traits"]["media_url"]
        assert not service._recording_sequences
        # Playback is dispatched as a browser recording, with no SC dependency.
        service.playback.start()
        await service.play_next_ambient_layers()
        assert service._staged_recording is None
        assert kind in service._recording_sequences

    asyncio.run(exercise())
