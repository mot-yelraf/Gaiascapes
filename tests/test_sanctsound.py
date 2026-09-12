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


def test_catalog_contains_verified_target_recordings_and_nineteen_sites():
    for kind in sanctsound.MARINE_KINDS:
        assert len(sanctsound.available_locations(kind)) == 19
        assert len(set(sanctsound.default_regions(kind))) == 19
    for clip in sanctsound.CATALOG:
        name = clip["object"].rsplit("/", 1)[-1]
        assert "Speed" not in name
        assert clip["title"] and clip["creator"] and clip["citation"]
        if clip.get("provider"):
            assert clip["source_url"].startswith("https://")
            assert clip["license_url"].startswith("https://creativecommons.org/")
        assert -90 <= clip["latitude"] <= 90 and -180 <= clip["longitude"] <= 180
        assert 0 < clip["size"] < sanctsound.MAX_AUDIO_BYTES


@pytest.mark.parametrize("kind", sanctsound.MARINE_KINDS)
def test_complete_marine_cycles_advance_each_sites_recordings(tmp_path, monkeypatch, kind):
    from pathlib import Path

    client = sanctsound.SanctSoundClient(tmp_path, kind)
    monkeypatch.setattr(client, "_download", lambda clip: tmp_path / Path(clip["object"]).name)
    sites = sanctsound.default_regions(kind)
    for cycle in range(3):
        for index, site in enumerate(sites):
            choices = [clip for clip in sanctsound.CATALOG if clip["kind"] == kind and clip["site"] == site]
            expected = choices[cycle % len(choices)]
            event = client.event_at(cycle * len(sites) + index)
            assert event.traits["region_id"] == site
            assert event.traits["recording_id"] == Path(expected["object"]).stem
            assert event.traits["title"] == expected["title"]
            assert event.provider == expected.get("provider", "noaa_sanctsound")


def test_bundled_recordings_keep_source_attribution_and_copy_to_runtime_data(tmp_path):
    client = sanctsound.SanctSoundClient(tmp_path, "dolphin_calls", ["xiamen"],
                                       lambda *_a, **_kw: pytest.fail("Bundled audio must not access the network"))
    events = [client.event_at(index) for index in range(4)]
    assert len({event.traits["recording_id"] for event in events}) == 4
    for event in events:
        path = client.media_dir / event.traits["media_url"].rsplit("/", 1)[-1]
        with wave.open(str(path)) as audio:
            assert audio.getframerate() == 48000
            assert audio.getnframes() > 0
        assert event.provider == "figshare"
        assert event.traits["license"] == "CC BY 4.0"
        assert "original speed" in event.traits["processing"]


def test_external_mp3_is_verified_and_cached(tmp_path):
    calls = []
    payload = b"ID3" + b"audio" * 10
    clip = dict(object="external.mp3", size=len(payload), md5=base64.b64encode(
        hashlib.md5(payload, usedforsecurity=False).digest()).decode(), download_url="https://example.org/dolphin.mp3")

    def opener(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(payload)

    client = sanctsound.SanctSoundClient(tmp_path, "dolphin_calls", opener=opener)
    assert client._download(clip).read_bytes() == payload
    client._download(clip)
    assert calls == [clip["download_url"]]


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
