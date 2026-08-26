"""Resolve an approximate system location from the host's public IP.

The resolver normalizes small provider-specific payload differences into one
stable application shape and caches the first successful result in memory.
"""

from __future__ import annotations

import json
import math
from threading import Lock
from typing import Any, Callable
from urllib.request import Request, urlopen


GEOIP_PROVIDERS = (
    ("ipapi.co", "https://ipapi.co/json/"),
    ("ipwho.is", "https://ipwho.is/"),
)


class GeoIpLocationResolver:
    """Resolve and cache a provider-independent approximate system location."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.5,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener
        self._cached_location: dict[str, Any] | None = None
        self._lock = Lock()

    def resolve(self) -> dict[str, Any] | None:
        """Return an approximate public-IP location, trying HTTPS fallbacks."""
        with self._lock:
            if self._cached_location is not None:
                return dict(self._cached_location)
            for provider, url in GEOIP_PROVIDERS:
                try:
                    request = Request(url, headers={"User-Agent": "Gaia-Scape"})
                    with self.opener(request, timeout=self.timeout_seconds) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    location = _normalize_location(payload, provider)
                except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                if location is not None:
                    self._cached_location = location
                    return dict(location)
        return None


def _normalize_location(payload: Any, provider: str) -> dict[str, Any] | None:
    """Normalize a supported provider response and reject invalid coordinates."""
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False or str(payload.get("status", "")).lower() == "fail":
        return None
    try:
        latitude = float(payload.get("latitude", payload.get("lat")))
        longitude = float(payload.get("longitude", payload.get("lon")))
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90.0 <= latitude <= 90.0
        or not -180.0 <= longitude <= 180.0
    ):
        return None

    timezone_value = payload.get("timezone")
    if isinstance(timezone_value, dict):
        timezone_name = str(timezone_value.get("id") or timezone_value.get("name") or "")
    else:
        timezone_name = str(timezone_value or "")
    city = str(payload.get("city") or "").strip()
    region = str(payload.get("region") or payload.get("regionName") or "").strip()
    country = str(payload.get("country_name") or payload.get("country") or "").strip()
    name = ", ".join(dict.fromkeys(part for part in (city, region, country) if part))
    if not name:
        name = f"{latitude:.2f}, {longitude:.2f}"
    return {
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone_name,
        "provider": provider,
    }
