"""USGS GeoJSON retrieval and provider normalization.

The client bounds network responses and translates valid earthquake features
into stable Gaia events without coupling downstream code to USGS field names.
"""

from __future__ import annotations

import json
import urllib.request

from gaiascapes.events import GaiaEvent


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024


def normalized_strength(magnitude) -> tuple[float, float]:
    """Return a bounded musical strength alongside the raw magnitude."""
    try:
        raw = float(magnitude)
    except (TypeError, ValueError):
        raw = 0.0
    return max(0.0, min(1.0, (raw + 1.0) / 8.0)), raw


def parse_document(document) -> tuple[GaiaEvent, ...]:
    """Normalize a USGS GeoJSON feature collection."""
    if not isinstance(document, dict):
        raise ValueError("USGS document must be an object")
    features = document.get("features", ())
    if not isinstance(features, list):
        raise ValueError("USGS features must be a list")
    events = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        event_id = str(feature.get("id", "")).strip()
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            not event_id
            or not isinstance(properties, dict)
            or not isinstance(coordinates, list)
            or len(coordinates) < 2
        ):
            continue
        try:
            timestamp = float(properties.get("time")) / 1000.0
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
            depth_km = float(coordinates[2]) if len(coordinates) > 2 else 0.0
        except (TypeError, ValueError):
            continue
        if timestamp <= 0 or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            continue
        strength, magnitude = normalized_strength(properties.get("mag"))
        events.append(
            GaiaEvent(
                provider="usgs",
                event_id=event_id,
                kind="earthquake",
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
                strength=strength,
                traits={
                    "magnitude": magnitude,
                    "depth_km": depth_km,
                    "place": str(properties.get("place") or ""),
                    "url": str(properties.get("url") or ""),
                },
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    return tuple(events)


class UsgsClient:
    """Small standard-library client suitable for background polling."""

    def __init__(self, url: str, timeout: float = 20.0):
        self.url = str(url)
        self.timeout = float(timeout)

    def fetch(self) -> tuple[GaiaEvent, ...]:
        """Fetch and normalize the configured feed once."""
        request = urllib.request.Request(
            self.url,
            headers={"User-Agent": "Gaiascapes/0.1 (+local environmental music app)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_DOCUMENT_BYTES:
                raise ValueError("USGS response exceeds size limit")
            payload = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ValueError("USGS response exceeds size limit")
        return parse_document(json.loads(payload.decode("utf-8")))
