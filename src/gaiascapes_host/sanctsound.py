"""Keyless SanctSound recordings with verified listening sites and local caching.

The bundled catalog retains NOAA NCEI object checksums, deployment coordinates,
and attribution. Only selected archive sites participate in playback; coordinates
describe hydrophones, not the precise positions of vocalizing animals.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from gaiascapes.events import GaiaEvent


MARINE_KINDS = ("whale_song", "dolphin_calls")
ARCHIVE_URL = "https://storage.googleapis.com/noaa-passive-bioacoustic/"
DATASET_URL = "https://doi.org/10.25921/saca-sp25"
MAX_AUDIO_BYTES = 64 * 1024 * 1024
CATALOG = tuple(json.loads(Path(__file__).with_name("sanctsound_catalog.json").read_text(encoding="utf-8"))["clips"])


def available_locations(kind: str) -> list[dict]:
    """Return the verified hydrophone sites containing this recording kind."""
    if kind not in MARINE_KINDS:
        raise ValueError("Unsupported SanctSound recording kind")
    sites = {}
    for clip in CATALOG:
        if clip["kind"] == kind:
            sites.setdefault(clip["site"], {
                "id": clip["site"], "name": f'{clip["region"]} · {clip["site"].upper()}',
                "latitude": clip["latitude"], "longitude": clip["longitude"],
            })
    return list(sites.values())


def default_regions(kind: str) -> list[str]:
    """Select every verified site by default."""
    return [location["id"] for location in available_locations(kind)]


def validate_regions(value, kind: str) -> list[str]:
    """Reject empty, duplicate, or unsupported archive site selections."""
    allowed = set(default_regions(kind))
    if (not isinstance(value, list) or not value
            or any(not isinstance(site, str) or site not in allowed for site in value)
            or len(set(value)) != len(value)):
        raise ValueError(f"{kind.replace('_', ' ').title()} requires one or more distinct available regions")
    return list(value)


class SanctSoundClient:
    """Rotate verified NOAA clips across the user's selected recording sites."""

    def __init__(self, data_dir: Path, kind: str, regions=None, opener=None):
        self.kind = kind
        self.regions = validate_regions(default_regions(kind) if regions is None else regions, kind)
        self.media_dir = Path(data_dir) / "media" / kind
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._opener = opener or urllib.request.urlopen
        self._lock = threading.Lock()

    def event_at(self, index: int) -> GaiaEvent:
        """Return a recording cue, downloading and verifying its WAV once."""
        index = int(index)
        site = self.regions[index % len(self.regions)]
        choices = [clip for clip in CATALOG if clip["kind"] == self.kind and clip["site"] == site]
        clip = choices[(index // len(self.regions)) % len(choices)]
        with self._lock:
            path = self._download(clip)
        title = "Humpback whale song" if self.kind == "whale_song" else "Dolphin vocalizations"
        recorded = path.stem.rsplit("_", 1)[-1]
        return GaiaEvent(
            provider="noaa_sanctsound", event_id=f"{path.stem}-{time.time_ns()}",
            kind=self.kind, timestamp=time.time(), latitude=clip["latitude"],
            longitude=clip["longitude"], strength=0.6,
            traits={
                "place": f'{clip["region"]} · {site.upper()}', "magnitude": 1.0,
                "media_url": f'/{self.kind.replace("_", "-")}-media/{path.name}',
                "title": title, "creator": clip["creator"],
                "license": "NOAA open data", "license_url": DATASET_URL,
                "source_url": ARCHIVE_URL + clip["metadata"],
                "citation": clip["citation"], "dataset_url": DATASET_URL,
                "recording_id": path.stem, "recorded_date": recorded[:8],
                "recorded_time": recorded[9:], "location_kind": "hydrophone",
                "region_id": site,
            },
        )

    def _download(self, clip: dict) -> Path:
        destination = self.media_dir / Path(clip["object"]).name
        if destination.is_file() and self._valid_audio(destination, clip):
            return destination
        # Replacing settings can leave an older client downloading this clip.
        # Separate temporary files keep their atomic cache writes independent.
        with tempfile.NamedTemporaryFile(dir=os.environ.get("GAIASCAPES_WORKER_TEMP_DIR", self.media_dir), suffix=".part", delete=False) as pending:
            temporary = Path(pending.name)
        request = urllib.request.Request(ARCHIVE_URL + clip["object"], headers={
            "User-Agent": "Gaiascapes (https://github.com/mot-yelraf/Gaiascapes)"
        })
        try:
            with self._opener(request, timeout=60) as response, temporary.open("wb") as output:
                remaining = min(clip["size"], MAX_AUDIO_BYTES) + 1
                while remaining:
                    chunk = response.read(min(65536, remaining))
                    if not chunk:
                        break
                    output.write(chunk)
                    remaining -= len(chunk)
            if not self._valid_audio(temporary, clip):
                raise RuntimeError("NOAA SanctSound returned an incomplete or invalid WAV recording")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @staticmethod
    def _valid_audio(path: Path, clip: dict) -> bool:
        if path.stat().st_size != clip["size"] or not 0 < clip["size"] <= MAX_AUDIO_BYTES:
            return False
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as audio:
            header = audio.read(12)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return False
            digest.update(header)
            for chunk in iter(lambda: audio.read(65536), b""):
                digest.update(chunk)
        return base64.b64encode(digest.digest()).decode("ascii") == clip["md5"]
