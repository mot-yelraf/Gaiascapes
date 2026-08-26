"""Runtime configuration and installed-data path handling.

Configuration loading migrates older installations, validates user settings,
applies supported environment overrides, and saves state beside runtime data.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .open_meteo import STORM_LOCATIONS, SURF_LOCATIONS


DEFAULT_USGS_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
SUPPORTED_SOURCES = ("usgs", "open_meteo_marine", "open_meteo_storm", "noaa_glm")
EVENT_VOICE_OPTIONS = (
    "earthquake",
    "tidal_bell",
    "seismic_bells",
    "lightning_glass",
    "natural_thunder",
    "none",
)
BACKGROUND_INSTRUMENT_OPTIONS = ("ocean_swell", "storm_potential", "none")
EVENT_INSTRUMENT_OPTIONS = {
    "earthquake": ("earthquake", "seismic_bells", "none"),
    "ocean_swell": ("ocean_swell", "none"),
    "tide_turn": ("tidal_bell", "none"),
    "lightning_flash": ("lightning_glass", "natural_thunder", "none"),
    "storm_potential": ("storm_potential", "none"),
}
EVENT_KIND_BY_VOICE = {
    "earthquake": "earthquake",
    "seismic_bells": "earthquake",
    "tidal_bell": "tide_turn",
    "lightning_glass": "lightning_flash",
    "natural_thunder": "lightning_flash",
}
DEFAULT_INSTRUMENT_SLOTS = {
    "event_1": "earthquake",
    "event_2": "tidal_bell",
    "event_3": "lightning_glass",
    "background": "ocean_swell",
}
DEFAULT_INSTRUMENT_VOLUMES = {
    "event_1": 1.0,
    "event_2": 1.0,
    "event_3": 0.45,
    "background": 1.0,
}
SUPPORTED_INSTRUMENTS = tuple(
    dict.fromkeys(instrument for values in EVENT_INSTRUMENT_OPTIONS.values() for instrument in values)
)
FORECAST_LOCATION_COUNT = 19


def default_forecast_locations(locations) -> list[dict]:
    """Return a JSON-safe editable copy of a provider location catalog."""
    return [
        {"name": place, "latitude": latitude, "longitude": longitude}
        for _slug, place, latitude, longitude in locations
    ]


@dataclass
class AppConfig:
    """Validated runtime settings stored alongside application data."""

    config_revision: int = 6
    http_host: str = "0.0.0.0"
    http_port: int = 8768
    usgs_url: str = DEFAULT_USGS_URL
    poll_seconds: int = 60
    retention_days: int = 7
    replay_hours: float = 2.0
    performance_seconds: float = 120.0
    live_mode: str = "capture"
    app_view: str = "dashboard"
    continuous_interval_seconds: float = 23.0
    osc_host: str = "127.0.0.1"
    osc_port: int = 57130
    osc_enabled: bool = True
    units: str = "metric"
    enabled_sources: list[str] = field(default_factory=lambda: ["usgs", "noaa_glm"])
    event_instruments: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_INSTRUMENT_SLOTS)
    )
    instrument_volumes: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_INSTRUMENT_VOLUMES)
    )
    lightning_sample_rate: int = 1
    ocean_swell_locations: list[dict] = field(
        default_factory=lambda: default_forecast_locations(SURF_LOCATIONS)
    )
    storm_outlook_locations: list[dict] = field(
        default_factory=lambda: default_forecast_locations(STORM_LOCATIONS)
    )

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        """Load recognized settings, tolerating absent and future fields."""
        config = cls()
        if path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("Configuration must be a JSON object")
            recognized = {item.name for item in fields(cls)}
            for key, value in document.items():
                if key in recognized:
                    setattr(config, key, value)
            if int(document.get("config_revision", 0)) < 2:
                if "noaa_glm" not in config.enabled_sources:
                    config.enabled_sources.append("noaa_glm")
            if int(document.get("config_revision", 0)) < 6:
                config.config_revision = 6
            config._migrate_legacy_instruments()
            # v0.26.236.36 lengthened the original, non-user-facing default.
            if document.get("continuous_interval_seconds") in {12, 12.0}:
                config.continuous_interval_seconds = 23.0
        config.apply_environment()
        config.validate()
        return config

    def apply_environment(self) -> None:
        """Apply process-only overrides without making them persistent settings."""
        persisted_values = getattr(self, "_persisted_environment_values", {})
        if value := os.environ.get("GAIA_SCAPE_HTTP_HOST"):
            persisted_values.setdefault("http_host", self.http_host)
            self.http_host = value
        if value := os.environ.get("GAIA_SCAPE_HTTP_PORT"):
            persisted_values.setdefault("http_port", self.http_port)
            self.http_port = int(value)
        if value := os.environ.get("GAIA_SCAPE_OSC_HOST"):
            persisted_values.setdefault("osc_host", self.osc_host)
            self.osc_host = value
        if value := os.environ.get("GAIA_SCAPE_OSC_PORT"):
            persisted_values.setdefault("osc_port", self.osc_port)
            self.osc_port = int(value)
        self._persisted_environment_values = persisted_values

    def validate(self) -> None:
        """Normalize values and reject unsafe ranges."""
        self.http_host = str(self.http_host).strip() or "0.0.0.0"
        self.config_revision = max(6, int(self.config_revision))
        self.osc_host = str(self.osc_host).strip() or "127.0.0.1"
        self.usgs_url = str(self.usgs_url).strip()
        if not self.usgs_url.startswith("https://"):
            raise ValueError("USGS URL must use HTTPS")
        self.http_port = _port(self.http_port, "HTTP")
        self.osc_port = _port(self.osc_port, "OSC")
        self.poll_seconds = max(60, int(self.poll_seconds))
        self.retention_days = max(1, min(365, int(self.retention_days)))
        self.replay_hours = max(0.05, min(24.0, float(self.replay_hours)))
        self.performance_seconds = max(1.0, min(3600.0, float(self.performance_seconds)))
        self.live_mode = str(self.live_mode).strip().lower()
        if self.live_mode not in {"capture", "continuous"}:
            raise ValueError("Live mode must be capture or continuous")
        self.app_view = str(self.app_view).strip().lower()
        if self.app_view not in {"dashboard", "map"}:
            raise ValueError("App view must be dashboard or map")
        self.continuous_interval_seconds = max(
            5.0, min(300.0, float(self.continuous_interval_seconds))
        )
        self.osc_enabled = bool(self.osc_enabled)
        self.units = str(self.units).strip().lower()
        if self.units not in {"metric", "imperial"}:
            raise ValueError("Units must be metric or imperial")
        if not isinstance(self.enabled_sources, list):
            raise ValueError("Enabled sources must be a list")
        self.enabled_sources = [
            source for source in SUPPORTED_SOURCES if source in self.enabled_sources
        ]
        if not isinstance(self.event_instruments, dict):
            raise ValueError("Event instrument mappings must be an object")
        self.event_instruments = event_mappings_for_slots(self.event_instruments)
        self.instrument_volumes = volume_mappings_for_slots(self.instrument_volumes)
        self.lightning_sample_rate = max(
            1, min(11, int(self.lightning_sample_rate))
        )
        self.ocean_swell_locations = validate_forecast_locations(
            self.ocean_swell_locations, "Ocean Swells"
        )
        self.storm_outlook_locations = validate_forecast_locations(
            self.storm_outlook_locations, "Storm Outlook"
        )

    def instrument_slots(self) -> dict[str, str]:
        """Return the user-facing event and background musical roles."""
        return dict(self.event_instruments)

    def volume_slots(self) -> dict[str, float]:
        """Return independent gain settings for each musical role."""
        return dict(self.instrument_volumes)

    def voices_for_event(self, kind: str) -> tuple[tuple[str, float], ...]:
        """Return matching event-slot instruments with their independent gains."""
        return tuple(
            (instrument, self.instrument_volumes[slot])
            for slot in ("event_1", "event_2", "event_3")
            if (instrument := self.event_instruments[slot]) != "none"
            and EVENT_KIND_BY_VOICE[instrument] == kind
            and self.instrument_volumes[slot] > 0
        )

    def instruments_for_event(self, kind: str) -> tuple[str, ...]:
        """Return each independently selected voice triggered by an event kind."""
        return tuple(instrument for instrument, _gain in self.voices_for_event(kind))

    def background_mappings(self) -> dict[str, str]:
        """Return renderer mappings for the one selected persistent background."""
        background = self.event_instruments["background"]
        return {
            "earthquake": "none",
            "tide_turn": "none",
            "ocean_swell": "ocean_swell" if background == "ocean_swell" else "none",
            "storm_potential": (
                "storm_potential" if background == "storm_potential" else "none"
            ),
        }

    def _migrate_legacy_instruments(self) -> None:
        """Translate older configurations into the current musical roles."""
        if not isinstance(self.event_instruments, dict):
            return
        mappings = dict(self.event_instruments)
        if {"event_1", "event_2", "background"}.issubset(mappings):
            mappings.setdefault("event_3", "lightning_glass")
            self.event_instruments = mappings
            return
        event_1 = mappings.get("earthquake", "earthquake")
        event_2 = mappings.get("tide_turn", "tidal_bell")
        if event_1 not in EVENT_VOICE_OPTIONS:
            event_1 = "earthquake"
        if event_2 not in EVENT_VOICE_OPTIONS:
            event_2 = "tidal_bell"
        ocean_selected = mappings.get("ocean_swell") == "ocean_swell"
        storm_selected = mappings.get("storm_potential") == "storm_potential"
        if ocean_selected:
            background = "ocean_swell"
        elif storm_selected:
            background = "storm_potential"
        else:
            background = "none"
        self.event_instruments = {
            "event_1": event_1,
            "event_2": event_2,
            "event_3": "lightning_glass",
            "background": background,
        }

    def save(self, path: Path) -> None:
        """Atomically save the current configuration."""
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        document = asdict(self)
        document.update(getattr(self, "_persisted_environment_values", {}))
        temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def resolve_data_dir() -> Path:
    """Resolve writable state without depending on the source checkout."""
    override = os.environ.get("GAIA_SCAPE_DATA_DIR")
    return Path(override).expanduser().resolve() if override else Path.cwd() / "data"


def event_mappings_for_slots(slots: object) -> dict[str, str]:
    """Validate and preserve independent musical-role selections."""
    if not isinstance(slots, dict):
        raise ValueError("Instrument slots must be an object")
    event_1 = str(slots.get("event_1", ""))
    event_2 = str(slots.get("event_2", ""))
    event_3 = str(slots.get("event_3", "none"))
    background = str(slots.get("background", ""))
    if event_1 not in EVENT_VOICE_OPTIONS:
        raise ValueError(f"Unsupported Event 1 instrument: {event_1}")
    if event_2 not in EVENT_VOICE_OPTIONS:
        raise ValueError(f"Unsupported Event 2 instrument: {event_2}")
    if event_3 not in EVENT_VOICE_OPTIONS:
        raise ValueError(f"Unsupported Event 3 instrument: {event_3}")
    if background not in BACKGROUND_INSTRUMENT_OPTIONS:
        raise ValueError(f"Unsupported Background instrument: {background}")
    return {
        "event_1": event_1,
        "event_2": event_2,
        "event_3": event_3,
        "background": background,
    }


def event_kind_for_voice(instrument: str) -> str:
    """Resolve the environmental trigger represented by an event voice."""
    try:
        return EVENT_KIND_BY_VOICE[str(instrument)]
    except KeyError as exc:
        raise ValueError(f"Unsupported event instrument: {instrument}") from exc


def volume_mappings_for_slots(volumes: object) -> dict[str, float]:
    """Validate 0..1 gain controls for every independent musical role."""
    if not isinstance(volumes, dict):
        raise ValueError("Instrument volumes must be an object")
    normalized = {}
    for slot, default in DEFAULT_INSTRUMENT_VOLUMES.items():
        try:
            value = float(volumes.get(slot, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid {slot.replace('_', ' ')} volume") from exc
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{slot.replace('_', ' ').title()} volume must be 0..1")
        normalized[slot] = value
    return normalized


def validate_forecast_locations(locations: object, label: str) -> list[dict]:
    """Validate one complete editable forecast sampling catalog."""
    if not isinstance(locations, list) or len(locations) != FORECAST_LOCATION_COUNT:
        raise ValueError(f"{label} must contain exactly {FORECAST_LOCATION_COUNT} locations")
    normalized = []
    coordinates = set()
    for index, location in enumerate(locations, start=1):
        if not isinstance(location, dict):
            raise ValueError(f"{label} location {index} must be an object")
        name = str(location.get("name", "")).strip()
        if not name or len(name) > 80:
            raise ValueError(f"{label} location {index} must have a name up to 80 characters")
        try:
            latitude = float(location.get("latitude"))
            longitude = float(location.get("longitude"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} location {index} has invalid coordinates") from exc
        if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            raise ValueError(f"{label} location {index} is outside world coordinates")
        coordinate = (round(latitude, 4), round(longitude, 4))
        if coordinate in coordinates:
            raise ValueError(f"{label} locations must use distinct coordinates")
        coordinates.add(coordinate)
        normalized.append(
            {"name": name, "latitude": latitude, "longitude": longitude}
        )
    return normalized


def _port(value: object, label: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} port must be between 1 and 65535")
    return port
