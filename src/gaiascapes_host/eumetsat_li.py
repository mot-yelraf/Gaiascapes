"""EUMETSAT MTG Lightning Imager retrieval and normalization.

The client authenticates through EUMETSAT's supported EUMDAC library, downloads
the latest LI Level 2 flash product, and converts bounded NetCDF observations
into provider-independent lightning events.
"""

from __future__ import annotations

import io
import math
import os
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from .netcdf_worker import netcdf_decoder

from gaiascapes.events import GaiaEvent


COLLECTION_ID = "EO:EUM:DAT:0691"
MAX_PRODUCT_BYTES = 96 * 1024 * 1024
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_FLASHES_PER_PRODUCT = 1000
GEOGRAPHIC_CELL_DEGREES = 10.0


@contextmanager
def _open_dataset(payload: bytes):
    """Open one bounded NetCDF chunk through a temporary file."""
    from netCDF4 import Dataset

    descriptor, path = tempfile.mkstemp(prefix="gaia-mtg-li-", suffix=".nc")
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


def _flash_group(dataset):
    required = {"flash_time", "latitude", "longitude", "flash_id"}
    pending = [dataset]
    while pending:
        group = pending.pop()
        if required.issubset(group.variables):
            return group
        pending.extend(group.groups.values())
    return None


def _number(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _strength_for_radiance(radiance: float) -> float:
    """Map optical radiance onto a bounded musical intensity."""
    return max(0.05, min(1.0, math.log10(1.0 + max(0.0, radiance)) / 4.0))


@netcdf_decoder
def parse_li_chunk(
    payload: bytes, chunk_name: str, product_id: str
) -> tuple[GaiaEvent, ...]:
    """Normalize flashes from one LI Level 2 BODY NetCDF chunk."""
    if not payload or len(payload) > MAX_CHUNK_BYTES:
        raise ValueError("EUMETSAT LI chunk is empty or exceeds the size limit")
    from netCDF4 import num2date

    with _open_dataset(payload) as dataset:
        group = _flash_group(dataset)
        if group is None:
            raise ValueError("EUMETSAT LI chunk lacks required flash variables")
        times = group["flash_time"]
        observed_times = num2date(
            times[:],
            times.units,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        latitudes = group["latitude"][:]
        longitudes = group["longitude"][:]
        flash_ids = group["flash_id"][:]
        radiances = group["radiance"][:] if "radiance" in group.variables else ()
        durations = (
            group["flash_duration"][:]
            if "flash_duration" in group.variables
            else ()
        )
        event_counts = (
            group["number_of_events"][:]
            if "number_of_events" in group.variables
            else ()
        )
        group_counts = (
            group["number_of_groups"][:]
            if "number_of_groups" in group.variables
            else ()
        )
        footprints = (
            group["flash_footprint"][:]
            if "flash_footprint" in group.variables
            else ()
        )
        events = []
        for index, observed in enumerate(observed_times):
            latitude = _number(latitudes[index], 999.0)
            longitude = _number(longitudes[index], 999.0)
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            radiance = max(0.0, _number(radiances[index])) if len(radiances) else 0.0
            strength = _strength_for_radiance(radiance)
            flash_id = int(_number(flash_ids[index]))
            traits = {
                "place": "Meteosat MTG Lightning Imager flash",
                "magnitude": 2.0 + (strength * 5.0),
                "satellite": "Meteosat MTG-I",
                "flash_id": flash_id,
                "flash_radiance_mw_m2_sr": radiance,
                "granule": PurePosixPath(chunk_name).name,
                "product": product_id,
                "observed": True,
            }
            if len(durations):
                traits["flash_duration_ms"] = max(0.0, _number(durations[index]))
            if len(event_counts):
                traits["event_count"] = max(0, int(_number(event_counts[index])))
            if len(group_counts):
                traits["group_count"] = max(0, int(_number(group_counts[index])))
            if len(footprints):
                traits["flash_footprint_pixels"] = max(
                    0, int(_number(footprints[index]))
                )
            events.append(
                GaiaEvent(
                    provider="eumetsat_mtg_li",
                    event_id=f"{product_id}:{PurePosixPath(chunk_name).name}:{flash_id}",
                    kind="lightning_flash",
                    timestamp=observed.timestamp(),
                    latitude=latitude,
                    longitude=longitude,
                    strength=strength,
                    traits=traits,
                )
            )
    return tuple(events)


def _select_geographically_distributed(events, maximum: int):
    """Select strong flashes round-robin across occupied geographic cells."""
    if len(events) <= maximum:
        return tuple(events)
    cells = {}
    for event in sorted(
        events,
        key=lambda event: (-event.strength, event.timestamp, event.event_id),
    ):
        cell = (
            math.floor((event.latitude + 90.0) / GEOGRAPHIC_CELL_DEGREES),
            math.floor((event.longitude + 180.0) / GEOGRAPHIC_CELL_DEGREES),
        )
        cells.setdefault(cell, []).append(event)
    selected = []
    depth = 0
    ordered_cells = sorted(cells)
    while len(selected) < maximum:
        candidates = [
            cells[cell][depth]
            for cell in ordered_cells
            if depth < len(cells[cell])
        ]
        if not candidates:
            break
        remaining = maximum - len(selected)
        if len(candidates) <= remaining:
            selected.extend(candidates)
        else:
            step = len(candidates) / remaining
            selected.extend(
                candidates[math.floor(index * step)] for index in range(remaining)
            )
        depth += 1
    return tuple(selected)


def parse_li_product(payload: bytes, product_id: str) -> tuple[GaiaEvent, ...]:
    """Extract LI BODY chunks from one EUMETSAT Data Store ZIP product."""
    if not payload or len(payload) > MAX_PRODUCT_BYTES:
        raise ValueError("EUMETSAT LI product is empty or exceeds the size limit")
    events = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            item for item in archive.infolist()
            if item.filename.lower().endswith(".nc")
            and "CHK-BODY" in item.filename.upper()
            and item.file_size <= MAX_CHUNK_BYTES
        ]
        if not members:
            raise ValueError("EUMETSAT LI product contains no BODY NetCDF chunk")
        if sum(item.file_size for item in members) > MAX_PRODUCT_BYTES:
            raise ValueError("EUMETSAT LI product expands beyond the size limit")
        for member in members:
            events.extend(
                parse_li_chunk(archive.read(member), member.filename, product_id)
            )
    sampled = _select_geographically_distributed(events, MAX_FLASHES_PER_PRODUCT)
    return tuple(sorted(sampled, key=lambda event: (event.timestamp, event.event_id)))


class EumetsatLiClient:
    """Retrieve unseen MTG LI flash products with user-owned credentials."""

    def __init__(self, consumer_key: str = "", consumer_secret: str = "", now=None):
        self.consumer_key = str(consumer_key)
        self.consumer_secret = str(consumer_secret)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._seen_products = set()
        self.last_product_count = 0
        self.last_raw_flash_count = 0
        self.last_sampled_flash_count = 0
        self.last_products = []
        self.last_error = ""

    def set_credentials(self, consumer_key: str, consumer_secret: str) -> None:
        """Replace credentials without exposing them through client status."""
        changed = (consumer_key, consumer_secret) != (
            self.consumer_key, self.consumer_secret
        )
        self.consumer_key = str(consumer_key)
        self.consumer_secret = str(consumer_secret)
        if changed:
            self._seen_products.clear()

    def fetch(self) -> tuple[GaiaEvent, ...]:
        """Download and normalize the newest unseen LI flash product."""
        if not self.consumer_key or not self.consumer_secret:
            raise RuntimeError("EUMETSAT Consumer Key and Consumer Secret are required")
        try:
            import eumdac
        except ImportError as exc:
            raise RuntimeError("The EUMDAC runtime dependency is not installed") from exc
        try:
            token = eumdac.AccessToken((self.consumer_key, self.consumer_secret))
            collection = eumdac.DataStore(token).get_collection(COLLECTION_ID)
            now = self._now().astimezone(timezone.utc).replace(tzinfo=None)
            products = collection.search(dtstart=now - timedelta(minutes=30), dtend=now)
            product = products.first()
            if product is None or str(product) in self._seen_products:
                self.last_product_count = 0
                self.last_raw_flash_count = 0
                self.last_sampled_flash_count = 0
                self.last_products = []
                self.last_error = ""
                return ()
            product_id = str(product)
            with product.open() as source:
                payload = source.read(MAX_PRODUCT_BYTES + 1)
            if len(payload) > MAX_PRODUCT_BYTES:
                raise ValueError("EUMETSAT LI product exceeds the size limit")
            events = parse_li_product(payload, product_id)
            self._seen_products.add(product_id)
            self.last_product_count = 1
            self.last_raw_flash_count = len(events)
            self.last_sampled_flash_count = len(events)
            self.last_products = [product_id]
            self.last_error = ""
            return events
        except Exception as exc:
            # SDK exceptions may contain authenticated URLs or response bodies.
            self.last_error = (
                f"EUMETSAT request failed ({type(exc).__name__}); "
                "check credentials, network access, and Data Store availability."
            )
            raise RuntimeError(self.last_error) from None

    def status(self) -> dict:
        """Return non-secret details from the latest Data Store update."""
        return {
            "configured": bool(self.consumer_key and self.consumer_secret),
            "collection": COLLECTION_ID,
            "product_count": self.last_product_count,
            "raw_flash_count": self.last_raw_flash_count,
            "sampled_flash_count": self.last_sampled_flash_count,
            "products": list(self.last_products),
            "last_error": self.last_error,
        }
