"""Runtime configuration and installed-data path handling.

Configuration loading migrates older installations, validates user settings,
applies supported environment overrides, and saves state beside runtime data.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .sanctsound import MARINE_KINDS, default_regions, validate_regions
from .commons_birdsong import BIRDSONG_LOCATIONS
from .open_meteo import STORM_LOCATIONS, SURF_LOCATIONS


DEFAULT_USGS_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
SUPPORTED_SOURCES = (
    "usgs",
    "open_meteo_marine",
    "open_meteo_storm",
    "noaa_glm",
    "eumetsat_mtg_li",
)
EVENT_VOICE_OPTIONS = (
    "earthquake",
    "tidal_bell",
    "seismic_bells",
    "lightning_glass",
    "natural_thunder",
    "test_tone",
    "none",
)
BACKGROUND_INSTRUMENT_OPTIONS = (
    "ocean_swell", "storm_potential", "birdsong", "frog_calls", "whale_song", "dolphin_calls", "none"
)
EVENT_INSTRUMENT_OPTIONS = {
    "earthquake": ("earthquake", "seismic_bells", "test_tone", "none"),
    "ocean_swell": ("ocean_swell", "none"),
    "tide_turn": ("tidal_bell", "none"),
    "lightning_flash": ("lightning_glass", "natural_thunder", "none"),
    "storm_potential": ("storm_potential", "none"),
    "birdsong": ("birdsong", "none"),
    "frog_calls": ("frog_calls", "none"),
    "whale_song": ("whale_song", "none"),
    "dolphin_calls": ("dolphin_calls", "none"),
}
EVENT_KIND_BY_VOICE = {
    "earthquake": "earthquake",
    "seismic_bells": "earthquake",
    "tidal_bell": "tide_turn",
    "lightning_glass": "lightning_flash",
    "natural_thunder": "lightning_flash",
    "test_tone": "earthquake",
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


def default_birdsong_locations() -> list[dict]:
    """Return the nineteen editable Birdsong region centers."""
    return default_forecast_locations(location[:4] for location in BIRDSONG_LOCATIONS)


def default_frog_locations() -> list[dict]:
    """Return nineteen independent region centers for worldwide frog calls."""
    return [
        {"name": name, "latitude": latitude, "longitude": longitude}
        for name, latitude, longitude in (
            ("Algonquin, Canada", 45.8, -78.4),
            ("Everglades, United States", 25.3, -80.9),
            ("Veracruz, Mexico", 19.5, -96.9),
            ("Sarapiqui, Costa Rica", 10.4, -84.0),
            ("Mindo, Ecuador", -0.05, -78.77),
            ("Atlantic Forest, Brazil", -24.0, -47.5),
            ("Misiones, Argentina", -26.0, -54.5),
            ("Camargue, France", 43.5, 4.5),
            ("Norfolk Broads, United Kingdom", 52.7, 1.5),
            ("Biebrza, Poland", 53.5, 22.8),
            ("Doñana, Spain", 37.0, -6.4),
            ("Rif Mountains, Morocco", 35.0, -5.3),
            ("Kakamega, Kenya", 0.3, 34.9),
            ("KwaZulu-Natal, South Africa", -28.4, 32.3),
            ("Andasibe, Madagascar", -18.9, 48.4),
            ("Western Ghats, India", 11.7, 76.1),
            ("Sabah, Malaysia", 5.0, 117.7),
            ("Okinawa, Japan", 26.7, 128.2),
            ("Wet Tropics, Australia", -17.0, 145.6),
        )
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
    map_projection: str = "robinson"
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
    eumetsat_consumer_key: str = ""
    eumetsat_consumer_secret: str = ""
    whale_song_enabled: bool = False
    dolphin_calls_enabled: bool = False
    whale_song_regions: list[str] = field(default_factory=lambda: default_regions("whale_song"))
    dolphin_calls_regions: list[str] = field(default_factory=lambda: default_regions("dolphin_calls"))
    frog_calls_enabled: bool = False
    frog_calls_locations: list[dict] = field(default_factory=default_frog_locations)
    birdsong_enabled: bool = True
    birdsong_provider: str = "wikimedia_commons"
    xeno_canto_api_key: str = field(default="", repr=False)
    birdsong_locations: list[dict] = field(default_factory=default_birdsong_locations)
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
        self.map_projection = str(self.map_projection).strip().lower()
        if self.map_projection not in {"robinson", "eckert_iv"}:
            raise ValueError("Projection model must be Robinson or Eckert IV")
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
        self.eumetsat_consumer_key = _credential(
            self.eumetsat_consumer_key, "EUMETSAT Consumer Key"
        )
        self.eumetsat_consumer_secret = _credential(
            self.eumetsat_consumer_secret, "EUMETSAT Consumer Secret"
        )
        for kind in MARINE_KINDS:
            if not isinstance(getattr(self, f"{kind}_enabled"), bool):
                raise ValueError(f"{kind} enabled must be a boolean")
            setattr(self, f"{kind}_regions", validate_regions(getattr(self, f"{kind}_regions"), kind))
        if not isinstance(self.frog_calls_enabled, bool):
            raise ValueError("Frog Calls enabled must be a boolean")
        if not isinstance(self.birdsong_enabled, bool):
            raise ValueError("Birdsong enabled must be a boolean")
        self.xeno_canto_api_key = _credential(self.xeno_canto_api_key, "Xeno-canto API key")
        if self.birdsong_provider not in {"wikimedia_commons", "xeno_canto"}:
            raise ValueError("Unsupported birdsong provider")
        if (self.birdsong_provider == "xeno_canto" or self.frog_calls_enabled) and not self.xeno_canto_api_key:
            raise ValueError("Xeno-canto requires an API key")
        if "eumetsat_mtg_li" in self.enabled_sources and not (
            self.eumetsat_consumer_key and self.eumetsat_consumer_secret
        ):
            raise ValueError(
                "EUMETSAT MTG Lightning requires a Consumer Key and Consumer Secret"
            )
        self.frog_calls_locations = validate_forecast_locations(
            self.frog_calls_locations, "Frog Calls"
        )
        self.birdsong_locations = validate_forecast_locations(
            self.birdsong_locations, "Birdsong"
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
            "birdsong": "birdsong" if background == "birdsong" and self.birdsong_enabled else "none",
            "frog_calls": "frog_calls" if background == "frog_calls" and self.frog_calls_enabled else "none",
            **{kind: kind if background == kind and getattr(self, f"{kind}_enabled") else "none"
               for kind in MARINE_KINDS},
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
        document = asdict(self)
        document.update(getattr(self, "_persisted_environment_values", {}))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(document, output, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def resolve_data_dir() -> Path:
    """Resolve writable state without depending on the source checkout."""
    override = os.environ.get("GAIA_SCAPE_DATA_DIR")
    return Path(override).expanduser().resolve() if override else Path.cwd() / "data"


def _credential(value: object, label: str) -> str:
    """Normalize a locally stored provider credential without logging it."""
    credential = str(value or "").strip()
    if len(credential) > 512 or any(ord(character) < 32 for character in credential):
        raise ValueError(f"{label} is invalid")
    return credential


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
