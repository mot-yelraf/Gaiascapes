"""Checks for verified SanctSound selection and bounded media caching.

All downloads use in-memory WAV fixtures; these tests never contact NOAA or
use installed runtime state.
"""

import base64
import hashlib
import io
import wave

import pytest

from gaiascapes_host import sanctsound
from gaiascapes_host.config import AppConfig


@pytest.fixture
def archive(monkeypatch):
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 8000, 80, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 80)
    payload = data.getvalue()
    clips = tuple(dict(clip, size=len(payload), md5=base64.b64encode(
        hashlib.md5(payload, usedforsecurity=False).digest()).decode()) for clip in sanctsound.CATALOG)
    monkeypatch.setattr(sanctsound, "CATALOG", clips)
    return payload


@pytest.mark.parametrize("kind", sanctsound.MARINE_KINDS)
def test_selected_site_rotation_cache_and_attribution(tmp_path, archive, kind):
    requests = []
    def opener(request, timeout):
        requests.append(request.full_url)
        assert request.full_url.startswith(sanctsound.ARCHIVE_URL)
        return io.BytesIO(archive)
    site = sanctsound.default_regions(kind)[0]
    client = sanctsound.SanctSoundClient(tmp_path, kind, [site], opener)
    first = client.event_at(0)
    second = client.event_at(0)
    assert len(requests) == 1
    assert first.provider == "noaa_sanctsound"
    assert first.kind == kind
    assert first.traits["region_id"] == site
    assert first.traits["location_kind"] == "hydrophone"
    assert first.traits["citation"] and first.traits["creator"]
    assert first.traits["source_url"].endswith("-metadata.json")
    assert first.event_id != second.event_id
    assert (client.media_dir / requests[0].rsplit("/", 1)[-1]).read_bytes() == archive
    for index in range(5):
        assert client.event_at(index).traits["region_id"] == site


def test_rotation_visits_sites_before_alternate_clips(tmp_path, archive):
    client = sanctsound.SanctSoundClient(tmp_path, "whale_song", ["ci02", "hi01"],
                                       lambda *_args, **_kwargs: io.BytesIO(archive))
    events = [client.event_at(index) for index in range(4)]
    assert [event.traits["region_id"] for event in events] == ["ci02", "hi01", "ci02", "hi01"]
    assert events[0].traits["recording_id"] != events[2].traits["recording_id"]
    assert events[1].traits["recording_id"] == events[3].traits["recording_id"]


@pytest.mark.parametrize("payload", [b"", b"<html>Unavailable</html>", b"RIFF0000WAVEbad", b"x" * 1000])
def test_bad_downloads_are_not_published(tmp_path, archive, payload):
    client = sanctsound.SanctSoundClient(tmp_path, "whale_song", opener=lambda *_a, **_kw: io.BytesIO(payload))
    with pytest.raises(RuntimeError, match="invalid WAV"):
        client.event_at(0)
    assert list(client.media_dir.iterdir()) == []


def test_corrupt_cache_is_replaced(tmp_path, archive):
    client = sanctsound.SanctSoundClient(tmp_path, "whale_song", opener=lambda *_a, **_kw: io.BytesIO(archive))
    event = client.event_at(0)
    path = client.media_dir / event.traits["media_url"].rsplit("/", 1)[-1]
    path.write_bytes(b"broken")
    client.event_at(0)
    assert path.read_bytes() == archive


@pytest.mark.parametrize("kind", sanctsound.MARINE_KINDS)
@pytest.mark.parametrize("selection", [[], ["bogus"], ["hi01", "hi01"], "hi01", [None], {}])
def test_invalid_regions_are_rejected(kind, selection):
    config = AppConfig(**{f"{kind}_regions": selection})
    with pytest.raises(ValueError, match="regions"):
        config.validate()


def test_catalog_contains_only_verified_unshifted_target_recordings():
    for clip in sanctsound.CATALOG:
        name = clip["object"].rsplit("/", 1)[-1]
        assert "Speed" not in name
        assert "humpbackwhalesong" in name if clip["kind"] == "whale_song" else "dolphin" in name
        assert -90 <= clip["latitude"] <= 90 and -180 <= clip["longitude"] <= 180
        assert 0 < clip["size"] < sanctsound.MAX_AUDIO_BYTES


def test_interrupted_download_cleans_temporary_file(tmp_path, archive):
    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("Connection lost")
            return super().read(12)
    client = sanctsound.SanctSoundClient(tmp_path, "whale_song", opener=lambda *_a, **_kw: Interrupted(archive))
    with pytest.raises(OSError, match="Connection lost"):
        client.event_at(0)
    assert list(client.media_dir.iterdir()) == []
