"""Exercise supplemental catalogs through the app's normal recording routes.

Synthetic audio and a tiny picture keep imports deterministic and offline.
"""

import base64
import copy
import hashlib
import io
import struct
import wave

from fastapi.testclient import TestClient

from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig
from gaiascapes_host import user_recordings


PICTURE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTQ0AAAAASUVORK5CYII="
)
SITE = {"common_name": "Field recording", "place": "Wetland", "latitude": 0, "longitude": -180}


def wav(amplitude):
    output = io.BytesIO()
    with wave.open(output, "wb") as sound:
        sound.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        sound.writeframes(struct.pack("<hh", amplitude, -amplitude) * 4000)
    return output.getvalue()


def asset(name, content):
    return {"source_url": f"https://archive.example/{name}",
            "download_url": f"https://archive.example/media/{name}", "file": name,
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "creator": "Field recordist", "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/"}


def upload(client, kind, sound, fields=SITE):
    return client.post(f"/api/recordings/catalog/{kind}/local", data=fields, files={
        "sound": ("test.wav", sound, "audio/wav"),
        "picture": ("test.png", PICTURE, "image/png"),
    })


def test_local_upload_persists_and_plays_without_provider_key(tmp_path):
    app = create_app(tmp_path, auto_capture=False)
    sound = wav(101)
    client = TestClient(app)
    assert upload(client, "frog_calls", sound).json() == {"added": 1, "skipped": 0}
    assert upload(client, "frog_calls", sound).json() == {"added": 0, "skipped": 1}
    assert upload(client, "frog_calls", sound, {**SITE, "longitude": 181}).status_code == 422
    assert client.get("/api/settings/recording-counts").json()["user_recordings"]["frog_calls"] == 1
    settings = client.put("/api/settings/audio", json={
        "instrument_slots": {"event_1": "none", "event_2": "none", "event_3": "none", "background": "frog_calls"},
    })
    assert settings.status_code == 200, settings.text
    assert AppConfig.load(tmp_path / "config.json").instrument_slots()["background"] == "frog_calls"

    with TestClient(create_app(tmp_path, auto_capture=False)) as restarted:
        next_recording = restarted.post("/api/recordings/next-image?play=true")
        assert next_recording.status_code == 200, next_recording.text
        event = next_recording.json()["event"]
        assert event["provider"] == "local_recording"
        assert (event["latitude"], event["longitude"]) == (0, -180)
        event_traits = event["traits"]
        audio = restarted.get(event_traits["media_url"])
        assert audio.content == sound and audio.headers["content-type"] == "audio/wav"
        image = restarted.get(event_traits["picture"]["url"])
        assert image.content == PICTURE and image.headers["content-type"] == "image/png"
        cues = restarted.get("/api/cues", params={"after": 0}).json()["cues"]
        assert cues[0]["event"] == event


def test_import_is_atomic_skips_built_ins_and_appends_to_rotation(tmp_path, monkeypatch):
    app = create_app(tmp_path, auto_capture=False)
    kind = "canine_calls"
    files = {"first.wav": wav(100), "second.wav": wav(200), "portrait.png": PICTURE}
    downloads = []

    def download(url, destination, size):
        downloads.append(url)
        contents = files[url.rsplit("/", 1)[-1]]
        destination.write_bytes(contents)
        return len(contents), hashlib.sha256(contents).hexdigest()

    monkeypatch.setattr(user_recordings, "_download_media", download)
    native = app.state.service.canine_calls.recordings
    entries = [
        {**SITE, **asset(name, files[name]), "kind": kind, "id": name.split(".")[0],
         "title": name, "provider": "example", "duration_seconds": 1,
         "picture": asset("portrait.png", PICTURE)}
        for name in ("first.wav", "second.wav")
    ]
    catalog = {"format_version": 1, "recordings": [
        {**entries[0], "id": native[0]["id"]}, *entries,
    ]}
    malformed = copy.deepcopy(catalog)
    malformed["recordings"][-1]["sha256"] = "0" * 64
    url = f"/api/recordings/catalog/{kind}/import"
    client = TestClient(app)
    assert client.post(url, json=malformed).status_code == 422
    assert app.state.service.user_recordings.for_kind(kind) == ()
    assert client.post("/api/recordings/catalog/feline_calls/import", json=catalog).status_code == 422

    downloads.clear()
    assert client.post(url, json=catalog).json() == {"added": 2, "skipped": 1}
    assert len(downloads) == 3
    assert client.post(url, json=catalog).json() == {"added": 0, "skipped": 3}
    assert len(downloads) == 3
    assert len(app.state.service.canine_calls.recordings) == len(native)

    result = client.put("/api/settings/audio", json={
        "canine_calls_enabled": True,
        "instrument_slots": {"event_1": "none", "event_2": "none", "event_3": "none", "background": kind},
    })
    assert result.status_code == 200
    seen = []
    for _ in range(len(native) + len(entries)):
        response = client.post("/api/recordings/next-image")
        assert response.status_code == 200
        seen.append(response.json()["event"]["traits"]["recording_id"])
    assert seen == [record["id"] for record in native] + [entry["id"] for entry in entries]
