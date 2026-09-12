"""Fixed-site mammal recordings with bundled audio and retained attribution.

Only explicitly curated files participate in rotation. Audio is copied into the
selected installation's media directory, so playback needs no external lookup,
account, or editable search region. Published site coordinates are approximate.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from gaiascapes.events import GaiaEvent


MAMMAL_LABELS = {
    "feline_calls": "Feline Calls",
    "canine_calls": "Canine Calls",
    "elephant_calls": "Elephants",
    "primate_calls": "Primates",
}
MAMMAL_KINDS = tuple(MAMMAL_LABELS)
CATALOG_PATH = Path(__file__).with_name("mammal_catalog.json")


class MammalRecordingClient:
    """Rotate a group's fixed recording sites without network searches."""

    def __init__(self, data_dir: Path, kind: str):
        if kind not in MAMMAL_LABELS:
            raise ValueError("Unsupported mammal recording group")
        self.kind = kind
        self.media_dir = Path(data_dir) / "media" / kind
        self.media_dir.mkdir(parents=True, exist_ok=True)
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.recordings = tuple(r for r in catalog["recordings"] if r["kind"] == kind)
        if not self.recordings:
            raise ValueError(f"No bundled recordings for {MAMMAL_LABELS[kind]}")

    @property
    def location_count(self) -> int:
        """Return the number of fixed sites in this group's rotation."""
        return len(self.recordings)

    def event_at(self, index: int) -> GaiaEvent:
        """Return a playable recording with its actual site and source credits."""
        recording = self.recordings[int(index) % self.location_count]
        name = recording["file"]
        source = Path(__file__).with_name("recordings") / name
        destination = self.media_dir / name
        expected = recording["sha256"]
        if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            audio = source.read_bytes()
            if hashlib.sha256(audio).hexdigest() != expected:
                raise RuntimeError(f"Bundled recording failed integrity check: {name}")
            temporary = destination.with_suffix(".mp3.part")
            temporary.write_bytes(audio)
            temporary.replace(destination)
        traits = {key: recording[key] for key in (
            "common_name", "wikipedia_title", "creator", "license", "license_url",
            "source_url", "place", "context", "coordinate_basis",
        )}
        traits.update({
            "title": recording["common_name"],
            "recording_title": recording["title"],
            "recording_id": recording["id"],
            "media_url": f"/{self.kind.replace('_', '-')}-media/{name}",
            "location_kind": "recording",
            "region_id": recording["id"],
            "region_name": recording["place"],
            "region_latitude": recording["latitude"],
            "region_longitude": recording["longitude"],
            "duration_seconds": recording["duration_seconds"],
            "magnitude": 1.0,
        })
        metadata = destination.with_suffix(".json")
        if not metadata.is_file():
            temporary = metadata.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(recording, indent=2) + "\n", encoding="utf-8")
            temporary.replace(metadata)
        return GaiaEvent(
            provider="freesound", event_id=f"{recording['id']}-{time.time_ns()}",
            kind=self.kind, timestamp=time.time(), strength=0.6,
            latitude=recording["latitude"], longitude=recording["longitude"], traits=traits,
        )
