"""User-supplied wildlife recordings and pictures.

Assets use verified content-addressed filenames. The installation's separate
catalog is published only after every new asset in a batch is ready.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import threading
import time
from urllib.parse import quote, unquote, urljoin, urlsplit

from gaiascapes.events import GaiaEvent

from .commons_birdsong import COMMONS_CATALOG
from .mammals import CATALOG_PATH, MAMMAL_KINDS
from .sanctsound import ARCHIVE_URL, CATALOG as MARINE_CATALOG, MARINE_KINDS


ANIMAL_KINDS = ("birdsong", "frog_calls", *MARINE_KINDS, *MAMMAL_KINDS)
AUDIO_EXTENSIONS = {".mp3": "audio/mpeg", ".wav": "audio/wav"}
PICTURE_EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".png": "image/png", ".webp": "image/webp"}
ASSET_TYPES = AUDIO_EXTENSIONS | PICTURE_EXTENSIONS
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_PICTURE_BYTES = 10 * 1024 * 1024
MAX_CATALOG_BYTES = 1024 * 1024
MAX_BATCH_BYTES = 256 * 1024 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")
ASSET = re.compile(r"([0-9a-f]{64})(\.[a-z]+)\Z")
TLS = ssl.create_default_context()
TEXT_FIELDS = (
    "common_name", "title", "creator", "license", "place", "coordinate_basis",
    "context", "wikipedia_title", "scientific_name", "call_type", "recorded_date",
    "recorded_time", "recording_id", "recording_medium", "media_version", "review",
)
URL_FIELDS = ("source_url", "license_url", "coordinate_source")


def load_user_recordings(data_dir: Path) -> tuple[dict, ...]:
    """Read the active installation's user entries without touching media."""
    path = data_dir / "user-recordings" / "catalog.json"
    try:
        with path.open(encoding="utf-8") as source:
            document = json.load(source)
    except FileNotFoundError:
        return ()
    if (not isinstance(document, dict) or document.get("format_version") != 1
            or not isinstance(document.get("recordings"), list)):
        raise ValueError("Unsupported user recording catalog")
    return tuple(document["recordings"])


def _text(document, key, *, required=False):
    value = document.get(key, "")
    if not isinstance(value, str) or len(value) > 2000 or (required and not value.strip()):
        raise ValueError(f"{key} must be {'nonempty text' if required else 'text'} of at most 2000 characters")
    return value.strip()


def _url(value):
    # The same check is used for display links and for public downloads.
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.port not in (443, None)
                or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
            raise ValueError
    except ValueError:
        raise ValueError("Use an HTTPS URL without credentials or a custom port") from None
    return url


def _number(value, name, lower, upper, *, optional=False):
    if optional and value in ("", None):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return number


def _metadata(document, kind, *, imported):
    if not isinstance(document, dict):
        raise ValueError("Each recording must be a JSON object")
    if imported and document.get("kind") != kind:
        raise ValueError("The recording kind must match the selected Sound Sources tile")
    required = {"common_name", "place"} | ({"title", "creator", "license"} if imported else set())
    result = {key: value for key in TEXT_FIELDS
              if (value := _text(document, key, required=key in required))}
    result["title"] = result.get("title", result["common_name"])
    for key in URL_FIELDS:
        value = _text(document, key, required=imported and key in {"source_url", "license_url"})
        if value:
            _url(value)
            result[key] = value
    result.update(kind=kind,
                  latitude=_number(document.get("latitude"), "Latitude", -90, 90),
                  longitude=_number(document.get("longitude"), "Longitude", -180, 180))
    duration = _number(document.get("duration_seconds"), "Duration", 0.001, 86400, optional=not imported)
    if duration is not None:
        result["duration_seconds"] = duration
    return result


def _public_address(host):
    try:
        addresses = [ipaddress.ip_address(item[4][0]) for item in
                     socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except OSError as exc:
        raise ValueError(f"Could not resolve media host {host}") from exc
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        raise ValueError("Media URLs must resolve to public Internet addresses")
    return str(next((address for address in addresses if address.version == 4), addresses[0]))


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, context=TLS, timeout=timeout)
        self.address = address

    def connect(self):
        # Connect to the checked address and authenticate TLS for the original name.
        self.sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        except BaseException:
            self.sock.close()
            raise


def _download_media(url, destination, size):
    deadline = time.monotonic() + 60
    for _ in range(5):
        parsed = _url(url)
        connection = _PublicHTTPSConnection(parsed.hostname, _public_address(parsed.hostname), 10)
        try:
            path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parsed.query:
                path += "?" + quote(parsed.query, safe="=&?/%:+,$@!;*'()~-._")
            connection.request("GET", path, headers={
                "User-Agent": "Gaiascapes/1.0 (https://github.com/mot-yelraf/Gaiascapes)",
                "Accept-Encoding": "identity",
            })
            with connection.getresponse() as response:
                if response.status in (301, 302, 303, 307, 308) and response.getheader("Location"):
                    url = urljoin(url, response.getheader("Location"))
                    continue
                if response.status != 200:
                    raise ValueError(f"Media download returned HTTP {response.status} from {parsed.hostname}")
                return _copy_media(response, destination, size, deadline)
        except (OSError, http.client.HTTPException, UnicodeError) as exc:
            raise ValueError(f"Download failed from {parsed.hostname}") from exc
        finally:
            connection.close()
    raise ValueError("Media download returned too many redirects")


def _copy_media(source, destination, limit, deadline=None):
    digest = hashlib.sha256()
    size = 0
    with destination.open("wb") as output:
        while chunk := source.read(min(65536, limit + 1 - size)):
            size += len(chunk)
            if size > limit:
                raise ValueError("Media exceeds its declared size or the upload size limit")
            if deadline is not None and time.monotonic() > deadline:
                raise ValueError("Media download timed out")
            digest.update(chunk)
            output.write(chunk)
    return size, digest.hexdigest()


def _check_signature(path, suffix):
    with path.open("rb") as source:
        data = source.read(16)
    match suffix:
        case ".mp3":
            valid = data.startswith(b"ID3") or (len(data) >= 4 and data[0] == 255 and data[1] & 224 == 224)
        case ".wav":
            valid = data[:4] == b"RIFF" and data[8:12] == b"WAVE"
        case ".jpg" | ".jpeg":
            valid = data.startswith(b"\xff\xd8\xff")
        case ".png":
            valid = data.startswith(b"\x89PNG\r\n\x1a\n")
        case ".webp":
            valid = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        case _:
            valid = False
    if not valid:
        raise ValueError(f"Media content does not match the {suffix} file type")


def _remote_asset(document, extensions, limit):
    filename = _text(document, "file", required=True)
    suffix = Path(filename).suffix.lower()
    if filename != Path(filename).name or "\\" in filename or suffix not in extensions:
        raise ValueError("Media must have a plain filename with a supported extension")
    size = document.get("bytes")
    checksum = _text(document, "sha256", required=True)
    if type(size) is not int or not 1 <= size <= limit or not CHECKSUM.fullmatch(checksum):
        raise ValueError("Media requires a valid byte count and lowercase SHA-256 digest")
    url = _text(document, "download_url", required=True)
    _url(url)
    return url, suffix, size, checksum


def _stage_remote(asset, directory):
    url, suffix, size, checksum = asset
    destination = directory / f"{checksum}{suffix}"
    if destination.exists():
        if destination.stat().st_size != size:
            raise ValueError("Media size does not match the shared file's byte count")
        return destination
    actual = _download_media(url, destination, size)
    if actual != (size, checksum):
        raise ValueError("Downloaded media does not match its byte count and SHA-256")
    _check_signature(destination, suffix)
    return destination


def _stage_upload(upload, directory, extensions, limit):
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in extensions:
        raise ValueError(f"Choose a file with one of these extensions: {', '.join(extensions)}")
    pending = directory / f"upload{suffix}"
    size, checksum = _copy_media(upload.file, pending, limit)
    if not size:
        raise ValueError("The uploaded file is empty")
    _check_signature(pending, suffix)
    destination = directory / f"{checksum}{suffix}"
    pending.replace(destination)
    return destination, size, checksum


def _built_in_recordings():
    index = {kind: [] for kind in ANIMAL_KINDS}
    for record in json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["recordings"]:
        index[record["kind"]].append(record)
    for record in MARINE_CATALOG:
        index[record["kind"]].append({
            **record, "download_url": record.get("download_url") or ARCHIVE_URL + record["object"],
        })
    for location in COMMONS_CATALOG:
        for record in location["recordings"]:
            index["birdsong"].append({**record, "id": f"xc-{record['recording_id']}"})
    return index


def _keys(record):
    keys = {(key, value) for key in ("id", "sha256", "source_sha256", "download_url", "md5")
            if (value := record.get(key))}
    if checksum := record.get("source_sha256"):
        keys.add(("sha256", checksum))
    if url := record.get("source_url"):
        parsed = urlsplit(url)
        path = unquote(parsed.path).rstrip("/")
        if parsed.hostname in {"xeno-canto.org", "www.xeno-canto.org"} and re.fullmatch(r"/\d+", path):
            keys.add(("id", f"xc-{path[1:]}"))
        if parsed.hostname == "commons.wikimedia.org" and path.startswith("/wiki/File:"):
            keys.add(("commons_file", path.replace(" ", "_")))
    return keys


def _legacy_digest(kind, path):
    if kind not in MARINE_KINDS:
        return {}
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return {"md5": base64.b64encode(digest.digest()).decode("ascii")}


class UserRecordingLibrary:
    """Validate and append user entries while keeping built-in media separate."""

    def __init__(self, data_dir: Path):
        self.directory = data_dir / "user-recordings"
        self.assets = self.directory / "assets"
        self.entries = load_user_recordings(data_dir)
        self.built_in = _built_in_recordings()
        self.lock = threading.Lock()

    def for_kind(self, kind):
        """Return an immutable snapshot of additions for the selected tile."""
        return tuple(entry for entry in self.entries if entry["kind"] == kind)

    def _duplicates(self, kind):
        return set().union(*(_keys(entry) for entry in (*self.built_in[kind], *self.for_kind(kind))))

    def _append(self, kind, additions, skipped):
        with self.lock:
            seen = self._duplicates(kind)
            accepted = []
            for entry, files in additions:
                keys = _keys(entry)
                if keys & seen:
                    skipped += 1
                    continue
                accepted.append((entry, files))
                seen.update(keys)
            if not accepted:
                return {"added": 0, "skipped": skipped}
            self.assets.mkdir(exist_ok=True)
            for path in dict.fromkeys(path for _, files in accepted for path in files):
                path.replace(self.assets / path.name)
            entries = self.entries + tuple(entry for entry, _ in accepted)
            fd, name = tempfile.mkstemp(dir=self.directory, prefix=".catalog-")
            temporary = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump({"format_version": 1, "recordings": entries}, output, ensure_ascii=False, indent=2)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(self.directory / "catalog.json")
            finally:
                temporary.unlink(missing_ok=True)
            self.entries = entries
            return {"added": len(accepted), "skipped": skipped}

    def import_catalog(self, kind, document):
        """Download and atomically append verified public files from a manifest."""
        if kind not in ANIMAL_KINDS:
            raise ValueError("Unsupported animal recording tile")
        if not isinstance(document, dict) or type(document.get("format_version")) is not int or document["format_version"] != 1:
            raise ValueError("Expected a Gaiascapes catalog with format_version 1")
        records = document.get("recordings")
        if not isinstance(records, list) or not 1 <= len(records) <= 100:
            raise ValueError("Choose a catalog with 1–100 recordings")
        additions, skipped, budget = [], 0, MAX_BATCH_BYTES
        seen = self._duplicates(kind)
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.directory) as staging:
            directory = Path(staging)
            for index, record in enumerate(records, 1):
                try:
                    entry = _metadata(record, kind, imported=True)
                    identifier = _text(record, "id", required=True)
                    if not ID.fullmatch(identifier):
                        raise ValueError("id must use lowercase letters, digits, hyphens or underscores")
                    audio = _remote_asset(record, AUDIO_EXTENSIONS, MAX_AUDIO_BYTES)
                    url, suffix, size, checksum = audio
                    entry.update(id=identifier, provider=_text(record, "provider", required=True),
                                 download_url=url, file=f"{checksum}{suffix}", bytes=size, sha256=checksum)
                    keys = _keys(entry)
                    if keys & seen:
                        skipped += 1
                        continue
                    picture = record.get("picture")
                    assets = [audio]
                    if picture is not None:
                        if not isinstance(picture, dict):
                            raise ValueError("picture must be an object")
                        assets.append(_remote_asset(picture, PICTURE_EXTENSIONS, MAX_PICTURE_BYTES))
                        credit = {key: value for key in (
                            "title", "creator", "license", "license_url", "source_url", "alt", "context",
                        ) if (value := _text(picture, key, required=key in {"creator", "license", "license_url", "source_url"}))}
                        _url(credit["source_url"])
                        _url(credit["license_url"])
                        pic_url, pic_ext, pic_size, pic_hash = assets[1]
                        entry["picture"] = dict(credit, download_url=pic_url, file=pic_hash + pic_ext,
                                                bytes=pic_size, sha256=pic_hash)
                    budget -= sum(asset[2] for asset in assets)
                    if budget < 0:
                        raise ValueError("Catalog exceeds the 256 MiB media limit")
                    files = [_stage_remote(asset, directory) for asset in assets]
                    entry.update(_legacy_digest(kind, files[0]))
                    additions.append((entry, files))
                    seen.update(keys)
                except ValueError as exc:
                    raise ValueError(f"Recording {index}: {exc}") from exc
            return self._append(kind, additions, skipped)

    def add_upload(self, kind, fields, sound, picture):
        """Append one local sound and picture with their recording metadata."""
        if kind not in ANIMAL_KINDS:
            raise ValueError("Unsupported animal recording tile")
        entry = _metadata(fields, kind, imported=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.directory) as staging:
            directory = Path(staging)
            audio, size, checksum = _stage_upload(sound, directory, AUDIO_EXTENSIONS, MAX_AUDIO_BYTES)
            image, image_size, image_hash = _stage_upload(picture, directory, PICTURE_EXTENSIONS, MAX_PICTURE_BYTES)
            picture_metadata = {key: value for key in ("creator", "license", "source_url", "license_url", "context")
                                if (value := _text(fields, f"picture_{key}"))}
            for key in ("source_url", "license_url"):
                if key in picture_metadata:
                    _url(picture_metadata[key])
            entry.update(id=f"local-{checksum}", provider="local_recording", file=audio.name,
                         bytes=size, sha256=checksum, picture={
                             "file": image.name, "bytes": image_size, "sha256": image_hash,
                             "alt": entry["common_name"],
                             **picture_metadata,
                         })
            entry.update(_legacy_digest(kind, audio))
            return self._append(kind, [(entry, [audio, image])], 0)

    def asset_path(self, name):
        """Resolve a cataloged content-addressed asset for same-origin serving."""
        match = ASSET.fullmatch(name)
        if (match and match[2] in ASSET_TYPES and any(
            name == entry["file"] or name == entry.get("picture", {}).get("file")
            for entry in self.entries
        )):
            path = self.assets / name
            if path.is_file():
                return path
        return None

    def event(self, entry):
        """Build a normal recording playback event from a user catalog entry."""
        if not self.asset_path(entry["file"]):
            raise RuntimeError("User recording audio is missing")
        traits = {key: entry[key] for key in (*TEXT_FIELDS, *URL_FIELDS, "duration_seconds")
                  if key in entry}
        traits.update(title=entry["common_name"], recording_title=entry["title"],
                      recording_id=entry["id"], media_url=f"/user-recording-media/{entry['file']}",
                      location_kind="recording", region_id=entry["id"], region_name=entry["place"],
                      region_latitude=entry["latitude"], region_longitude=entry["longitude"], magnitude=1.0)
        if picture := entry.get("picture"):
            traits["picture"] = {key: picture[key] for key in ("alt", "creator", "license", "source_url", "license_url", "context")
                                 if key in picture}
            traits["picture"]["url"] = f"/user-recording-media/{picture['file']}"
        return GaiaEvent(provider=entry["provider"], event_id=f"{entry['id']}-{time.time_ns()}",
                         kind=entry["kind"], timestamp=time.time(), latitude=entry["latitude"],
                         longitude=entry["longitude"], strength=0.6, traits=traits)
