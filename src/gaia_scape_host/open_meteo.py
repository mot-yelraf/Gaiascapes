"""Open-Meteo marine and forecast normalization.

Provider clients retrieve modeled ocean, tide, and convective conditions from
global sampling locations and normalize useful observations into Gaia events.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from gaia_scape.events import GaiaEvent


MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Offshore coordinates avoid accidental selection of inland model cells.
SURF_LOCATIONS = (
    ("mavericks", "Mavericks, California", 37.49, -122.53),
    ("north-shore", "North Shore, Hawaiʻi", 21.67, -158.08),
    ("puerto-escondido", "Puerto Escondido, Mexico", 15.84, -97.08),
    ("nazare", "Nazaré, Portugal", 39.60, -9.09),
    ("bundoran", "Bundoran, Ireland", 54.48, -8.30),
    ("jeffreys-bay", "Jeffreys Bay, South Africa", -34.05, 24.94),
    ("uluwatu", "Uluwatu, Indonesia", -8.83, 115.08),
    ("gold-coast", "Gold Coast, Australia", -28.03, 153.45),
    ("teahupoo", "Teahupoʻo, Tahiti", -17.86, -149.28),
    ("shonan", "Shōnan, Japan", 35.30, 139.45),
    ("punta-de-lobos", "Punta de Lobos, Chile", -34.42, -72.05),
    ("florianopolis", "Florianópolis, Brazil", -27.68, -48.45),
)

# Broad atmospheric sampling points. These describe forecast potential, not strikes.
STORM_LOCATIONS = (
    ("great-plains", "Great Plains, USA", 36.0, -98.0),
    ("caribbean", "Caribbean", 18.0, -75.0),
    ("amazon", "Amazon Basin", -3.0, -62.0),
    ("la-plata", "La Plata Basin", -28.0, -58.0),
    ("west-africa", "West Africa", 8.0, 5.0),
    ("congo", "Congo Basin", -2.0, 23.0),
    ("east-africa", "East Africa", 1.0, 35.0),
    ("south-africa", "South Africa", -27.0, 28.0),
    ("south-asia", "South Asia", 23.0, 80.0),
    ("maritime-continent", "Maritime Continent", 0.0, 115.0),
    ("northern-australia", "Northern Australia", -16.0, 133.0),
    ("east-asia", "East Asia", 28.0, 115.0),
)


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _documents(document):
    if isinstance(document, dict):
        return (document,)
    if isinstance(document, list) and all(isinstance(item, dict) for item in document):
        return tuple(document)
    raise ValueError("Open-Meteo document must be an object or list of objects")


def _series(hourly, name):
    values = hourly.get(name, ())
    return values if isinstance(values, list) else ()


def _nearest_index(timestamps, now):
    candidates = [(abs(timestamp - now), index) for index, timestamp in enumerate(timestamps) if timestamp is not None]
    return min(candidates)[1] if candidates else None


def parse_marine_document(document, locations=SURF_LOCATIONS, now=None):
    """Normalize current swell state and modeled tide turns."""
    events = []
    now = time.time() if now is None else float(now)
    for location, payload in zip(locations, _documents(document)):
        slug, place, fallback_latitude, fallback_longitude = location
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            continue
        timestamps = tuple(_timestamp(value) for value in _series(hourly, "time"))
        index = _nearest_index(timestamps, now)
        if index is None:
            continue
        wave_height = _at(hourly, "wave_height", index)
        swell_height = _at(hourly, "swell_wave_height", index)
        swell_period = _at(hourly, "swell_wave_period", index)
        swell_direction = _at(hourly, "swell_wave_direction", index)
        sea_level = _at(hourly, "sea_level_height_msl", index)
        if wave_height is not None or swell_height is not None:
            height = swell_height if swell_height is not None else wave_height
            strength = max(0.0, min(1.0, (height or 0.0) / 6.0))
            events.append(
                GaiaEvent(
                    provider="open_meteo_marine",
                    event_id=f"{slug}-swell-{int(timestamps[index])}",
                    kind="ocean_swell",
                    timestamp=timestamps[index],
                    latitude=_number(payload.get("latitude"), fallback_latitude),
                    longitude=_number(payload.get("longitude"), fallback_longitude),
                    strength=strength,
                    traits={
                        "place": place,
                        "magnitude": height or 0.0,
                        "wave_height_m": wave_height,
                        "swell_height_m": swell_height,
                        "swell_period_s": swell_period,
                        "swell_direction_deg": swell_direction,
                        "sea_level_msl_m": sea_level,
                        "modeled": True,
                    },
                )
            )
        if 0 < index < len(timestamps) - 1:
            previous = _at(hourly, "sea_level_height_msl", index - 1)
            following = _at(hourly, "sea_level_height_msl", index + 1)
            if None not in (previous, sea_level, following):
                turn = None
                if sea_level > previous and sea_level >= following:
                    turn = "high"
                elif sea_level < previous and sea_level <= following:
                    turn = "low"
                if turn:
                    events.append(
                        GaiaEvent(
                            provider="open_meteo_marine",
                            event_id=f"{slug}-tide-{turn}-{int(timestamps[index])}",
                            kind="tide_turn",
                            timestamp=timestamps[index],
                            latitude=_number(payload.get("latitude"), fallback_latitude),
                            longitude=_number(payload.get("longitude"), fallback_longitude),
                            strength=max(0.15, min(1.0, abs(sea_level) / 1.5)),
                            traits={
                                "place": place,
                                "magnitude": sea_level,
                                "tide_state": turn,
                                "sea_level_msl_m": sea_level,
                                "modeled": True,
                            },
                        )
                    )
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    return tuple(events)


def parse_storm_document(document, locations=STORM_LOCATIONS, now=None):
    """Normalize significant modeled convective potential without claiming strikes."""
    events = []
    now = time.time() if now is None else float(now)
    for location, payload in zip(locations, _documents(document)):
        slug, place, fallback_latitude, fallback_longitude = location
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            continue
        timestamps = tuple(_timestamp(value) for value in _series(hourly, "time"))
        index = _nearest_index(timestamps, now)
        if index is None:
            continue
        cape = _at(hourly, "cape", index) or 0.0
        weather_code = int(_at(hourly, "weather_code", index) or 0)
        showers = _at(hourly, "showers", index) or 0.0
        gust = _at(hourly, "wind_gusts_10m", index) or 0.0
        if cape < 600.0 and weather_code not in (95, 96, 99):
            continue
        strength = max(0.0, min(1.0, max(cape / 3000.0, showers / 20.0, gust / 140.0)))
        events.append(
            GaiaEvent(
                provider="open_meteo_storm",
                event_id=f"{slug}-storm-{int(timestamps[index])}",
                kind="storm_potential",
                timestamp=timestamps[index],
                latitude=_number(payload.get("latitude"), fallback_latitude),
                longitude=_number(payload.get("longitude"), fallback_longitude),
                strength=strength,
                traits={
                    "place": place,
                    "magnitude": cape / 1000.0,
                    "cape_jkg": cape,
                    "weather_code": weather_code,
                    "showers_mm": showers,
                    "wind_gust_kmh": gust,
                    "forecast": True,
                },
            )
        )
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    return tuple(events)


def _at(hourly, name, index):
    values = _series(hourly, name)
    return _number(values[index]) if index < len(values) else None


class _OpenMeteoClient:
    def __init__(self, url, locations, parser, variables, timeout=20.0):
        self.url = str(url)
        self.locations = tuple(locations)
        self.parser = parser
        self.variables = tuple(variables)
        self.timeout = float(timeout)

    def fetch(self):
        """Retrieve and normalize one forecast update for all locations."""
        parameters = urllib.parse.urlencode(
            {
                "latitude": ",".join(str(item[2]) for item in self.locations),
                "longitude": ",".join(str(item[3]) for item in self.locations),
                "hourly": ",".join(self.variables),
                "past_hours": 1,
                "forecast_hours": 2,
                "timezone": "GMT",
                "cell_selection": "sea" if self.parser is parse_marine_document else "nearest",
            }
        )
        request = urllib.request.Request(
            f"{self.url}?{parameters}",
            headers={"User-Agent": "Gaia-Scape/0.1 (+local environmental music app)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ValueError("Open-Meteo response exceeds size limit")
        return self.parser(json.loads(payload.decode("utf-8")), self.locations)


class OpenMeteoMarineClient(_OpenMeteoClient):
    """Retrieve modeled swell and tide conditions from Open-Meteo Marine."""

    def __init__(self, url=MARINE_URL, timeout=20.0):
        super().__init__(
            url,
            SURF_LOCATIONS,
            parse_marine_document,
            (
                "wave_height",
                "swell_wave_height",
                "swell_wave_period",
                "swell_wave_direction",
                "sea_level_height_msl",
            ),
            timeout,
        )


class OpenMeteoStormClient(_OpenMeteoClient):
    """Retrieve global convective forecasts from Open-Meteo Weather."""

    def __init__(self, url=WEATHER_URL, timeout=20.0):
        super().__init__(
            url,
            STORM_LOCATIONS,
            parse_storm_document,
            ("cape", "weather_code", "showers", "wind_gusts_10m"),
            timeout,
        )
