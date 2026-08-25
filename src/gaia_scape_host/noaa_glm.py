"""NOAA GOES GLM Level 2 flash retrieval and normalization.

The client discovers recent public satellite granules, validates bounded
netCDF payloads, and converts accepted flashes into normalized Gaia events.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from netCDF4 import Dataset, num2date

from gaia_scape.events import GaiaEvent


LOGGER = logging.getLogger(__name__)
GLM_POLL_SECONDS = 20.0
MAX_LIST_BYTES = 2 * 1024 * 1024
MAX_GRANULE_BYTES = 8 * 1024 * 1024
MAX_FLASHES_PER_GRANULE = 4
SONIFICATION_SAMPLE_STRIDE = 1
SATELLITES = (
    ("G19", "GOES-19", "noaa-goes19"),
    ("G18", "GOES-18", "noaa-goes18"),
)


@contextmanager
def _open_dataset(payload: bytes):
    """Open NetCDF bytes through a real temporary file without HDF5 diagnostics."""
    descriptor, path = tempfile.mkstemp(prefix="gaia-glm-", suffix=".nc")
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
        with Dataset(path, "r") as dataset:
            yield dataset
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _strength_for_energy(energy_j: float) -> float:
    """Map GLM optical energy across a useful logarithmic musical range."""
    if energy_j <= 0:
        return 0.05
    return max(0.05, min(1.0, (math.log10(energy_j) + 15.0) / 4.0))


def parse_glm_document(payload: bytes, object_key: str) -> tuple[GaiaEvent, ...]:
    """Normalize quality-accepted flashes from one GLM LCFA NetCDF granule."""
    if not payload or len(payload) > MAX_GRANULE_BYTES:
        raise ValueError("NOAA GLM granule is empty or exceeds the size limit")
    with _open_dataset(payload) as dataset:
        required = (
            "flash_id",
            "flash_lat",
            "flash_lon",
            "flash_energy",
            "flash_area",
            "flash_quality_flag",
            "flash_time_offset_of_first_event",
            "flash_time_offset_of_last_event",
        )
        missing = [name for name in required if name not in dataset.variables]
        if missing:
            raise ValueError(f"NOAA GLM granule lacks {', '.join(missing)}")
        platform = str(getattr(dataset, "platform_ID", "GOES")).strip() or "GOES"
        platform_name = next(
            (name for code, name, _bucket in SATELLITES if code == platform), platform
        )
        flash_ids = dataset["flash_id"][:]
        latitudes = dataset["flash_lat"][:]
        longitudes = dataset["flash_lon"][:]
        energies = dataset["flash_energy"][:]
        areas = dataset["flash_area"][:]
        qualities = dataset["flash_quality_flag"][:]
        first_variable = dataset["flash_time_offset_of_first_event"]
        last_variable = dataset["flash_time_offset_of_last_event"]
        first_times = num2date(
            first_variable[:],
            first_variable.units,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        last_times = num2date(
            last_variable[:],
            last_variable.units,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        start_token = next(
            (part[1:] for part in PurePosixPath(object_key).name.split("_") if part.startswith("s")),
            PurePosixPath(object_key).stem,
        )
        events = []
        for index in range(len(flash_ids)):
            latitude = _number(latitudes[index], 999.0)
            longitude = _number(longitudes[index], 999.0)
            quality = int(_number(qualities[index], -1))
            if quality != 0 or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                continue
            first = first_times[index]
            last = last_times[index]
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            energy_j = max(0.0, _number(energies[index]))
            area_km2 = max(0.0, _number(areas[index]) / 1_000_000.0)
            strength = _strength_for_energy(energy_j)
            flash_id = int(_number(flash_ids[index]))
            events.append(
                GaiaEvent(
                    provider="noaa_glm",
                    event_id=f"{platform}-{start_token}-{flash_id}",
                    kind="lightning_flash",
                    timestamp=first.timestamp(),
                    latitude=latitude,
                    longitude=longitude,
                    strength=strength,
                    traits={
                        "place": f"{platform_name} GLM flash",
                        "magnitude": 2.0 + (strength * 5.0),
                        "satellite": platform_name,
                        "flash_id": flash_id,
                        "flash_energy_j": energy_j,
                        "flash_area_km2": area_km2,
                        "flash_duration_ms": max(0.0, (last - first).total_seconds() * 1000.0),
                        "quality_flag": quality,
                        "granule": PurePosixPath(object_key).name,
                        "observed": True,
                    },
                )
            )
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    return tuple(events)


def count_glm_flashes(payload: bytes) -> int:
    """Return the unfiltered flash count declared by one LCFA granule."""
    with _open_dataset(payload) as dataset:
        dimension = dataset.dimensions.get("number_of_flashes")
        return len(dimension) if dimension is not None else 0


def select_sonification_events(events, stride: int = SONIFICATION_SAMPLE_STRIDE):
    """Select every nth accepted flash without disturbing its observed timing."""
    ordered = tuple(
        sorted(events, key=lambda event: (event.timestamp, event.event_id))
    )
    return ordered[::max(1, int(stride))]


class NoaaGlmClient:
    """Poll the public GOES-East and GOES-West LCFA object buckets."""

    def __init__(self, timeout: float = 15.0, now=None):
        self.timeout = float(timeout)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._seen_keys = set()
        self._initialized_buckets = set()
        self.last_granule_count = 0
        self.last_raw_flash_count = 0
        self.last_sampled_flash_count = 0
        self.last_sonified_flash_count = 0
        self.last_granules = []
        self.last_sonification_events = ()
        self.last_error = ""
        self.sonification_sample_stride = SONIFICATION_SAMPLE_STRIDE

    def fetch(self) -> tuple[GaiaEvent, ...]:
        """Retrieve unseen 20-second granules and return bounded flash samples."""
        now = self._now().astimezone(timezone.utc)
        sampled_events = []
        sonification_events = []
        raw_flash_count = 0
        granules = []
        errors = []
        for _code, satellite_name, bucket in SATELLITES:
            try:
                keys = self._available_keys(bucket, now)
                if bucket not in self._initialized_buckets:
                    self._seen_keys.update(keys[:-1])
                    unseen = keys[-1:] if keys else []
                    self._initialized_buckets.add(bucket)
                else:
                    unseen = [key for key in keys if key not in self._seen_keys]
                for key in unseen[-6:]:
                    payload = self._download(bucket, key)
                    raw_flash_count += count_glm_flashes(payload)
                    flashes = parse_glm_document(payload, key)
                    self._seen_keys.add(key)
                    granules.append(key)
                    sonification_events.extend(flashes)
                    strongest = sorted(
                        flashes, key=lambda event: event.strength, reverse=True
                    )[:MAX_FLASHES_PER_GRANULE]
                    sampled_events.extend(strongest)
            except Exception as exc:
                errors.append(f"{satellite_name}: {type(exc).__name__}: {exc}")
        self.last_granule_count = len(granules)
        self.last_raw_flash_count = raw_flash_count
        self.last_sampled_flash_count = len(sampled_events)
        sonification_events = select_sonification_events(
            sonification_events, self.sonification_sample_stride
        )
        self.last_sonification_events = tuple(sonification_events)
        self.last_sonified_flash_count = len(sonification_events)
        self.last_granules = [PurePosixPath(key).name for key in granules]
        self.last_error = "; ".join(errors)
        if errors and not granules:
            raise RuntimeError(self.last_error)
        if errors:
            LOGGER.warning("NOAA GLM partial retrieval: %s", self.last_error)
        sampled_events.sort(key=lambda event: (event.timestamp, event.event_id))
        return tuple(sampled_events)

    def status(self) -> dict:
        """Return counts, granules, and errors from the latest GLM update."""
        return {
            "granule_count": self.last_granule_count,
            "raw_flash_count": self.last_raw_flash_count,
            "sampled_flash_count": self.last_sampled_flash_count,
            "sonified_flash_count": self.last_sonified_flash_count,
            "granules": list(self.last_granules),
            "last_error": self.last_error,
        }

    def _available_keys(self, bucket: str, now: datetime) -> list[str]:
        hours = (now, now - timedelta(hours=1)) if now.minute < 2 else (now,)
        keys = []
        for hour in hours:
            prefix = f"GLM-L2-LCFA/{hour.year}/{hour.timetuple().tm_yday:03d}/{hour.hour:02d}/"
            query = urllib.parse.urlencode(
                {"list-type": "2", "prefix": prefix, "max-keys": 1000}
            )
            payload = self._request(f"https://{bucket}.s3.amazonaws.com/?{query}", MAX_LIST_BYTES)
            root = ET.fromstring(payload)
            keys.extend(
                element.text
                for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "Key" and element.text
            )
        return sorted(set(keys))

    def _download(self, bucket: str, key: str) -> bytes:
        quoted_key = urllib.parse.quote(key, safe="/")
        return self._request(
            f"https://{bucket}.s3.amazonaws.com/{quoted_key}", MAX_GRANULE_BYTES
        )

    def _request(self, url: str, maximum_bytes: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Gaia-Scape/0.1 (+local environmental music app)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > maximum_bytes:
                raise ValueError("NOAA GLM response exceeds size limit")
            payload = response.read(maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise ValueError("NOAA GLM response exceeds size limit")
        return payload
