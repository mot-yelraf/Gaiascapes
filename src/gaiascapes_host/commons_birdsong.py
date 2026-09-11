"""Keyless Wikimedia Commons birdsong discovery and local media caching.

The client searches one curated global listening point at a time, accepts only
freely reusable Commons audio, and retains both the original file and the
attribution metadata beneath the selected installation's data directory.
"""

from __future__ import annotations

import html
import json
import os
import mimetypes
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from gaiascapes.events import GaiaEvent


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_USER_AGENT = (
    "Gaiascapes/1.0 (https://github.com/mot-yelraf/Gaiascapes)"
)
MAX_AUDIO_BYTES = 64 * 1024 * 1024
SUPPORTED_LICENSES = frozenset(
    {
        "CC0",
        "CC BY 2.0",
        "CC BY 2.5",
        "CC BY 3.0",
        "CC BY 4.0",
        "CC BY-SA 2.0",
        "CC BY-SA 2.5",
        "CC BY-SA 3.0",
        "CC BY-SA 4.0",
        "Public domain",
    }
)

# Exact Commons titles keep the rotation deterministic and make each attribution
# auditable. The API still supplies the current file URL and license at runtime.
BIRDSONG_LOCATIONS = (
    ("canada", "Boreal Canada", 53.0, -106.0, "Gavia immer - Common Loon XC139388.mp3"),
    ("costa-rica", "Costa Rican Cloud Forest", 10.30, -84.80, "Resplendent Quetzal song (Pharomachrus mocinno).ogg"),
    ("ecuador", "Ecuadorian Andes", -0.70, -78.60, "Myadestes ralloides - Andean Solitaire XC251141.mp3"),
    ("brazil", "Brazilian Atlantic Forest", -24.0, -47.5, "Cyanocorax caeruleus - Azure Jay XC433994.mp3"),
    ("argentina", "Northwestern Argentina", -25.2, -65.8, "Nothoprocta pentlandii - Andean Tinamou XC112728.mp3"),
    ("poland", "Eastern Poland", 52.7, 23.8, "Sylvia atricapilla - Eurasian Blackcap XC316851.mp3"),
    ("romania", "Danube Delta, Romania", 45.1, 29.3, "Acrocephalus arundinaceus 1.ogg"),
    ("scotland", "Scottish Highlands", 57.0, -3.4, "Phylloscopus trochilus - Willow Warbler XC468919.mp3"),
    ("morocco", "Northern Morocco", 35.0, -5.4, "European robin (Erithacus rubecula) singing in northern Morocco.wav"),
    ("kenya", "Central Kenya", -0.9, 36.7, "Pogoniulus bilineatus - Yellow-rumped Tinkerbird XC371859.mp3"),
    ("botswana", "Okavango Delta, Botswana", -19.3, 22.9, "CapeTurtleDove.ogg"),
    ("madagascar", "Eastern Madagascar", -18.8, 48.4, "Roep Indri Indri.ogg"),
    ("india", "Western Ghats, India", 11.7, 76.1, "Malabar Whistling-thrush mawt Record-024.wav"),
    ("malaysia", "Borneo, Malaysia", 5.0, 117.7, "ShamaJavadi.ogg"),
    ("japan", "Central Japan", 36.2, 138.2, "Japanese nightingale note01.ogg"),
    ("bangladesh", "Sundarbans, Bangladesh", 22.0, 89.5, "Oriental magpie robin.wav"),
    ("south-africa", "South African Bushveld", -25.7, 28.2, "Ploceus velatus velatus, wintersang, Pta NBT, 2022-07-23 15h52, a.mp3"),
    ("australia", "Eastern Australia", -27.9, 153.2, "Eastern Whipbird (Psophodes olivaceus) (W PSOPHODES OLIVACEUS R1 C2).ogg"),
    ("new-zealand", "North Island, New Zealand", -38.5, 175.4, "Kiwi Male North Island brown kiwi song.ogg"),
)


class CommonsBirdsongClient:
    """Resolve and cache freely licensed audio for 19 global locations."""

    def __init__(self, data_dir: Path, opener=None):
        self.media_dir = Path(data_dir) / "media" / "birdsong"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._opener = opener or urllib.request.urlopen

    def event_at(self, index: int) -> GaiaEvent:
        """Return a normalized birdsong event, downloading its audio once."""
        slug, place, latitude, longitude, file_title = BIRDSONG_LOCATIONS[
            int(index) % len(BIRDSONG_LOCATIONS)
        ]
        metadata_path = self.media_dir / f"{slug}.json"
        metadata = self._read_cached_metadata(metadata_path)
        if metadata is None:
            metadata = self._discover(file_title)
            media_path = self._download(slug, metadata)
            metadata["file"] = media_path.name
            self._write_metadata(metadata_path, metadata)
        media_path = self.media_dir / metadata["file"]
        if not media_path.is_file():
            media_path = self._download(slug, metadata)
            metadata["file"] = media_path.name
            self._write_metadata(metadata_path, metadata)
        now = time.time()
        return GaiaEvent(
            provider="wikimedia_commons",
            event_id=f"{slug}-{time.time_ns()}",
            kind="birdsong",
            timestamp=now,
            latitude=latitude,
            longitude=longitude,
            strength=0.6,
            traits={
                "place": place,
                "magnitude": 1.0,
                "media_url": f"/birdsong-media/{urllib.parse.quote(media_path.name)}",
                "title": metadata["title"],
                "creator": metadata["creator"],
                "license": metadata["license"],
                "license_url": metadata["license_url"],
                "source_url": metadata["source_url"],
                "commons_page_id": metadata["page_id"],
            },
        )

    def _discover(self, file_title: str) -> dict:
        parameters = {
            "action": "query",
            "titles": f"File:{file_title}",
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "format": "json",
            "formatversion": 2,
        }
        request = urllib.request.Request(
            f"{COMMONS_API_URL}?{urllib.parse.urlencode(parameters)}",
            headers={"User-Agent": COMMONS_USER_AGENT},
        )
        with self._opener(request, timeout=30) as response:
            document = json.load(response)
        candidates = []
        for page in document.get("query", {}).get("pages", []):
            image_info = next(iter(page.get("imageinfo", ())), None)
            if not image_info or not _is_audio_mime(image_info.get("mime", "")):
                continue
            metadata = image_info.get("extmetadata", {})
            license_name = _metadata_value(metadata, "LicenseShortName")
            size = int(image_info.get("size", 0))
            if license_name not in SUPPORTED_LICENSES or not 0 < size <= MAX_AUDIO_BYTES:
                continue
            title = str(page.get("title", "")).removeprefix("File:")
            candidates.append(
                {
                    "page_id": int(page["pageid"]),
                    "title": title,
                    "creator": _plain_text(_metadata_value(metadata, "Artist")),
                    "license": license_name,
                    "license_url": _metadata_value(metadata, "LicenseUrl"),
                    "source_url": image_info["descriptionurl"],
                    "download_url": image_info["url"],
                    "mime": image_info["mime"],
                    "size": size,
                }
            )
        if not candidates:
            raise RuntimeError(
                f"Wikimedia Commons has no compatible audio for {file_title}"
            )
        return candidates[0]

    def _download(self, slug: str, metadata: dict) -> Path:
        extension = Path(urllib.parse.urlparse(metadata["download_url"]).path).suffix
        if not extension:
            extension = mimetypes.guess_extension(metadata.get("mime", "")) or ".audio"
        destination = self.media_dir / f"{slug}{extension.lower()}"
        pending_dir = os.environ.get("GAIASCAPES_WORKER_TEMP_DIR")
        temporary = (Path(pending_dir) / (destination.name + ".part") if pending_dir
                     else destination.with_suffix(destination.suffix + ".part"))
        request = urllib.request.Request(
            metadata["download_url"],
            headers={"User-Agent": COMMONS_USER_AGENT},
        )
        with self._opener(request, timeout=60) as response, temporary.open("wb") as output:
            remaining = MAX_AUDIO_BYTES + 1
            while remaining > 0:
                chunk = response.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                output.write(chunk)
                remaining -= len(chunk)
        if not temporary.stat().st_size:
            temporary.unlink()
            raise RuntimeError("Wikimedia Commons returned an empty audio file")
        if temporary.stat().st_size > MAX_AUDIO_BYTES:
            temporary.unlink()
            raise RuntimeError("Wikimedia Commons audio exceeds the 64 MiB limit")
        temporary.replace(destination)
        return destination

    def _read_cached_metadata(self, path: Path) -> dict | None:
        if not path.is_file():
            return None
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        required = {"file", "title", "creator", "license", "license_url", "source_url", "page_id", "download_url"}
        return metadata if isinstance(metadata, dict) and required <= metadata.keys() else None

    @staticmethod
    def _write_metadata(path: Path, metadata: dict) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def _metadata_value(metadata: dict, key: str) -> str:
    value = metadata.get(key, {})
    return str(value.get("value", "")).strip() if isinstance(value, dict) else ""


def _is_audio_mime(value: str) -> bool:
    """Recognize Commons audio MIME types, including Ogg's generic type."""
    mime = str(value).lower()
    return mime.startswith("audio/") or mime == "application/ogg"


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", str(value))
    return html.unescape(without_tags).strip() or "Unknown contributor"
