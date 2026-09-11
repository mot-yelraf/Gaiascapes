"""Xeno-canto bird and frog recordings with verified locations and local caching.

The authenticated API supplies catalog metadata; audio is downloaded without
credentials. Only identified birds and frogs with usable coordinates and reusable licenses
enter the rotation. Catalogs and recordings live beneath the runtime data folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from gaiascapes.events import GaiaEvent


API_URL = "https://xeno-canto.org/api/3/recordings"
COUNTRIES = (
    "Canada", "United States", "Mexico", "Costa Rica", "Ecuador", "Brazil",
    "Argentina", "Poland", "Germany", "United Kingdom", "France", "Spain",
    "Sweden", "Netherlands", "Morocco", "Kenya", "South Africa", "India",
    "Australia",
)
MAX_AUDIO_BYTES = 64 * 1024 * 1024
CATALOG_TTL = 24 * 60 * 60
CATALOG_POLICY_VERSION = 2
REGION_RADIUS_KM = 100.0
NEW_MEXICO_ROADRUNNER_ID = "254791"
EARTH_RADIUS_KM = 6371.0
USER_AGENT = "Gaiascapes (https://github.com/mot-yelraf/Gaiascapes)"


class NoRecordingsError(RuntimeError):
    """Signal that a region has no suitable recordings in the searched catalog."""


# Preserve the original exception import for Birdsong callers.
NoBirdsongRecordingsError = NoRecordingsError


class XenoCantoClient:
    """Rotate attributed recordings through countries or selected regions."""

    def __init__(self, data_dir: Path, api_key: str, opener=None, *, locations=None, group="birds"):
        """Create a bird or frog client with optional geographic region centers."""
        if group not in {"birds", "frogs"}:
            raise ValueError("Unsupported Xeno-canto animal group")
        self.group = group
        self.kind = "birdsong" if group == "birds" else "frog_calls"
        self.label = "Birdsong" if group == "birds" else "Frog Calls"
        self.media_url_prefix = "/birdsong-media" if group == "birds" else "/frog-calls-media"
        self.media_dir = Path(data_dir) / "media" / self.kind / "xeno-canto"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.locations = tuple(dict(location) for location in locations) if locations is not None else None
        if self.locations == ():
            raise ValueError(f"{self.label} requires at least one location")
        self._api_key = api_key
        self._opener = opener or urllib.request.urlopen
        self._lock = threading.Lock()
        self._retry_at = 0.0

    def event_at(self, index: int) -> GaiaEvent:
        """Return a playback event at the recording's documented coordinates."""
        with self._lock:
            if not self._api_key:
                raise RuntimeError("Enter a Xeno-canto API key in Sound settings")
            location = self.locations[index % len(self.locations)] if self.locations else None
            place = location["name"] if location else COUNTRIES[index % len(COUNTRIES)]
            records = self._catalog(place, location)
            count = len(self.locations) if self.locations else len(COUNTRIES)
            record = records[(index // count) % len(records)]
            filename = f"XC{record['id']}{record['extension']}"
            destination = self.media_dir / filename
            if not destination.is_file():
                self._download(record, destination)
            return GaiaEvent(
                provider="xeno_canto", event_id=f"XC{record['id']}-{time.time_ns()}",
                kind=self.kind, timestamp=time.time(),
                latitude=record["latitude"], longitude=record["longitude"], strength=0.6,
                traits={
                    "place": record["place"], "magnitude": 1.0,
                    "media_url": f"{self.media_url_prefix}/xeno-canto/{filename}",
                    "title": record["title"], "creator": record["creator"],
                    "license": record["license"], "license_url": record["license_url"],
                    "source_url": record["source_url"], "recording_id": record["id"],
                    "recorded_date": record["date"], "recorded_time": record["time"],
                    "location_kind": "recording", "quality": record["quality"],
                    "scientific_name": record["scientific_name"],
                    **({"region_name": place, "region_latitude": location["latitude"],
                        "region_longitude": location["longitude"],
                        **({"recording_selection": "New Mexico state bird"}
                           if self.group == "birds" and _new_mexico_region(location)
                           else {"region_radius_km": REGION_RADIUS_KM})}
                       if location else {}),
                },
            )

    def _open(self, url):
        if time.monotonic() < self._retry_at:
            raise RuntimeError("Xeno-canto is temporarily unavailable; retry in a minute")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            return self._opener(request, timeout=30)
        except (OSError, ValueError) as exc:
            self._retry_at = time.monotonic() + 60
            code = exc.code if isinstance(exc, urllib.error.HTTPError) else None
            message = {
                401: "Xeno-canto rejected the API key",
                403: "Xeno-canto denied access; check the API key and account",
                429: "Xeno-canto rate limit reached; retry in a minute",
            }.get(code, "Xeno-canto request failed; check network access")
            # Transport errors can contain the authenticated URL.
            raise RuntimeError(message) from None

    def _catalog(self, place, location=None):
        featured_id = (
            NEW_MEXICO_ROADRUNNER_ID
            if self.group == "birds" and _new_mexico_region(location) else None
        )
        if featured_id:
            query_regions = [f"nr:{featured_id}"]
            cache_name = f"recording-{featured_id}"
        elif location:
            boxes = _region_boxes(location)
            query_regions = [f"box:{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
                             for south, west, north, east in boxes]
            identity = json.dumps([location["latitude"], location["longitude"], REGION_RADIUS_KM])
            cache_name = "region-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        else:
            query_regions = [f'cnt:"{place}"']
            cache_name = place.lower().replace(" ", "-")
        path = self.media_dir / f"{cache_name}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("policy_version") == CATALOG_POLICY_VERSION
                and cached.get("records")
                and time.time() - float(cached.get("fetched_at", 0)) < CATALOG_TTL
            ):
                records = cached["records"]
                if featured_id:
                    records = [record for record in records if record["id"] == featured_id]
                elif location:
                    records = [record for record in records if _within_region(record, location)]
                if records:
                    return records
        except (OSError, ValueError, TypeError, KeyError):
            pass
        records = []
        try:
            for region in query_regions:
                # Bound catalog work while looking beyond unusable first-page entries.
                for page in range(1, 6):
                    # Frogs may be ungraded or have brief calls. Filter supported
                    # reuse licenses locally, including noncommercial ShareAlike.
                    filters = ' q:">C"' if self.group == "birds" else ""
                    parameters = urllib.parse.urlencode({
                        "query": f"grp:{self.group} {region}{filters}",
                        "key": self._api_key, "per_page": 50, "page": page,
                    })
                    with self._open(f"{API_URL}?{parameters}") as response:
                        document = json.load(response)
                    records.extend(record for item in document.get("recordings", [])
                                   if (record := _record(item, self.group)) is not None
                                   and (record["id"] == featured_id if featured_id else
                                        location is None or _within_region(record, location)))
                    if records or page >= int(document.get("numPages", 1)):
                        break
        except (OSError, ValueError, AttributeError, TypeError):
            raise RuntimeError("Xeno-canto returned an invalid catalog response") from None
        records = list({record["id"]: record for record in records}.values())
        if not records:
            if featured_id:
                raise NoRecordingsError(
                    f"New Mexico's Greater Roadrunner song (XC{featured_id}) is unavailable or unsuitable"
                )
            region_description = f"within {REGION_RADIUS_KM:g} km of {place}" if location else f"for {place}"
            licenses = "CC BY/CC BY-SA/CC BY-NC-SA"
            raise NoRecordingsError(f"Xeno-canto found no suitable {licenses} {self.group} recordings {region_description}")
        temporary = path.with_suffix(".json.part")
        temporary.write_text(json.dumps({
            "policy_version": CATALOG_POLICY_VERSION,
            "fetched_at": time.time(), "records": records,
        }), encoding="utf-8")
        temporary.replace(path)
        return records

    def _download(self, record, destination):
        pending_dir = os.environ.get("GAIASCAPES_WORKER_TEMP_DIR")
        temporary = (Path(pending_dir) / (destination.name + ".part") if pending_dir
                     else destination.with_suffix(destination.suffix + ".part"))
        try:
            with self._open(record["download_url"]) as response, temporary.open("wb") as output:
                content_type = response.headers.get("Content-Type", "").split(";")[0]
                if content_type not in {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
                                        "audio/ogg", "application/ogg", "application/octet-stream"}:
                    raise RuntimeError("Xeno-canto did not return an audio file")
                size = 0
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise RuntimeError("Xeno-canto recording exceeds the 64 MiB limit")
                    output.write(chunk)
            if not size:
                raise RuntimeError("Xeno-canto returned an empty recording")
            temporary.replace(destination)
        except OSError:
            raise RuntimeError("Unable to download or cache the Xeno-canto recording") from None
        finally:
            temporary.unlink(missing_ok=True)


def _new_mexico_region(location):
    """Recognize New Mexico in GeoIP or user-supplied sound location names."""
    return bool(location and re.search(r"\b(?:new mexico|nm)\b", location["name"], re.IGNORECASE))


def _region_boxes(location):
    """Bound a spherical search radius, splitting regions at the date line."""
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    angular_radius = REGION_RADIUS_KM / EARTH_RADIUS_KM
    latitude_span = math.degrees(angular_radius)
    south, north = max(-90.0, latitude - latitude_span), min(90.0, latitude + latitude_span)
    if south <= -90 or north >= 90:
        return [(south, -180.0, north, 180.0)]
    longitude_span = math.degrees(math.asin(math.sin(angular_radius) / math.cos(math.radians(latitude))))
    west, east = longitude - longitude_span, longitude + longitude_span
    if west < -180:
        return [(south, west + 360, north, 180.0), (south, -180.0, north, east)]
    if east > 180:
        return [(south, west, north, 180.0), (south, -180.0, north, east - 360)]
    return [(south, west, north, east)]


def _within_region(record, location):
    """Reject recordings outside the selected radius using their real coordinates."""
    latitude, longitude = math.radians(float(record["latitude"])), math.radians(float(record["longitude"]))
    center_latitude = math.radians(float(location["latitude"]))
    center_longitude = math.radians(float(location["longitude"]))
    haversine = (math.sin((latitude - center_latitude) / 2) ** 2
                 + math.cos(latitude) * math.cos(center_latitude)
                 * math.sin((longitude - center_longitude) / 2) ** 2)
    distance = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))
    return distance <= REGION_RADIUS_KM


def _record(item, group="birds"):
    """Normalize only playable, attributed records with public coordinates."""
    try:
        if item.get("grp") != group or item.get("status", "identified") != "identified":
            return None
        if group == "birds" and item.get("q") not in {"A", "B"}:
            return None
        latitude, longitude = float(item["lat"]), float(item["lon"])
        if not (math.isfinite(latitude) and math.isfinite(longitude)
                and -90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        license_url = item["lic"]
        license_match = re.fullmatch(
            r"https?://creativecommons\.org/licenses/(by|by-sa|by-nc-sa)/(2\.0|2\.5|3\.0|4\.0)/?", license_url
        )
        recording_id = str(item["id"])
        extension = Path(item["file-name"]).suffix.lower()
        if (not license_match or not recording_id.isdigit()
                or extension not in {".mp3", ".wav", ".ogg"} or not item.get("rec")):
            return None
        minutes, seconds = map(int, item["length"].split(":"))
        minimum_seconds = 1 if group == "frogs" else 10
        if not minimum_seconds <= minutes * 60 + seconds <= 180:
            return None
        # Build public URLs from the numeric ID, never from credential-bearing data.
        source_url = f"https://xeno-canto.org/{recording_id}"
        return {
            "id": recording_id, "extension": extension,
            "latitude": latitude, "longitude": longitude,
            "place": ", ".join(filter(None, [item.get("loc"), item.get("cnt")])),
            "title": f"{item['en']} · {item.get('type', 'animal recording')}",
            "scientific_name": f"{item['gen']} {item['sp']}",
            "creator": item["rec"], "license_url": license_url,
            "license": f"CC {license_match[1].upper()} {license_match[2]}",
            "source_url": source_url, "download_url": source_url + "/download",
            "date": item.get("date", ""), "time": item.get("time", ""),
            "quality": item.get("q", ""),
        }
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
