"""Capture observed lightning from the Korea Meteorological Administration.

The KMA API Hub publishes five-minute batches in Korean Standard Time.
Normalize its quality-checked strokes for the existing lightning voice.
"""

import math
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from gaiascapes import GaiaEvent

from .http_transport import open_url


KMA_POLL_SECONDS = 300
KMA_ENDPOINT = "https://apihub.kma.go.kr/api/typ01/url/lgt_kma_nx1.php"
KST = timezone(timedelta(hours=9))
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def parse_strokes(payload: str) -> tuple[GaiaEvent, ...]:
    """Read rows in KMA's published post-2015 lightning observation format."""
    events = []
    for line in payload.splitlines():
        row = line.split()
        if not row or row[0].startswith("#"):
            continue
        try:
            if len(row) != 22:
                raise ValueError
            observed_at = datetime.fromisoformat(f"{row[1]}T{row[2]}")
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=KST)
            fraction = int(row[3])
            longitude, latitude = map(float, row[5:7])
            current = float(row[8])
            stroke_type, quality = int(row[10]), int(row[20])
        except (ValueError, OverflowError):
            raise ValueError("Unexpected KMA lightning response format") from None
        if (quality != 0 or stroke_type not in {1, 2} or not math.isfinite(current)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            continue
        events.append(GaiaEvent(
            provider="kma_lightning",
            event_id=f"{observed_at.astimezone(timezone.utc).isoformat()}-{fraction}-{row[0]}",
            kind="lightning_flash",
            timestamp=observed_at.timestamp() + fraction / 1_000_000_000,
            latitude=latitude,
            longitude=longitude,
            strength=min(1.0, abs(current) / 100.0),
            traits={
                "place": "KMA lightning observation",
                "observed": True,
                "current_ka": current,
                "stroke_type": "cloud_to_ground" if stroke_type == 1 else "cloud",
            },
        ))
    return tuple(events)


class KmaLightningClient:
    """Read recent observations using an installation's own KMA API key."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    def fetch(self) -> tuple[GaiaEvent, ...]:
        """Retrieve an overlapping window so late batches can still be captured."""
        end = datetime.now(KST)
        start = end - timedelta(minutes=15)
        query = urlencode({
            "tm1": start.strftime("%Y%m%d%H%M"),
            "tm2": end.strftime("%Y%m%d%H%M"),
            "authKey": self._api_key,
        })
        try:
            with open_url(f"{KMA_ENDPOINT}?{query}") as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise RuntimeError("KMA denied access. Check the API key and lightning access.") from None
            raise RuntimeError(f"KMA request failed (HTTP {exc.code})") from None
        except (OSError, URLError):
            raise RuntimeError("Could not connect to the KMA lightning API") from None
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("KMA lightning response exceeds size limit")
        return parse_strokes(payload.decode("utf-8-sig"))
