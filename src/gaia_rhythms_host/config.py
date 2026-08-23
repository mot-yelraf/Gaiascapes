"""Runtime configuration and installed-data path handling."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


DEFAULT_USGS_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
SUPPORTED_SOURCES = ("usgs", "open_meteo_marine", "open_meteo_storm")
EVENT_INSTRUMENT_OPTIONS = {
    "earthquake": ("earthquake", "seismic_bells", "tectonic_drone"),
    "ocean_swell": ("ocean_swell", "tidal_bell"),
    "tide_turn": ("tidal_bell", "ocean_swell"),
    "storm_potential": ("storm_potential", "seismic_bells"),
}
DEFAULT_EVENT_INSTRUMENTS = {
    kind: instruments[0] for kind, instruments in EVENT_INSTRUMENT_OPTIONS.items()
}
SUPPORTED_INSTRUMENTS = tuple(
    dict.fromkeys(instrument for values in EVENT_INSTRUMENT_OPTIONS.values() for instrument in values)
)


@dataclass
class AppConfig:
    """Validated runtime settings stored alongside application data."""

    http_host: str = "0.0.0.0"
    http_port: int = 8768
    usgs_url: str = DEFAULT_USGS_URL
    poll_seconds: int = 60
    retention_days: int = 7
    replay_hours: float = 2.0
    performance_seconds: float = 120.0
    live_mode: str = "capture"
    continuous_interval_seconds: float = 12.0
    osc_host: str = "127.0.0.1"
    osc_port: int = 57130
    osc_enabled: bool = True
    enabled_sources: list[str] = field(default_factory=lambda: ["usgs"])
    event_instruments: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_EVENT_INSTRUMENTS)
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
        config.apply_environment()
        config.validate()
        return config

    def apply_environment(self) -> None:
        """Apply supported process-level overrides."""
        if value := os.environ.get("GAIA_RHYTHMS_HTTP_HOST"):
            self.http_host = value
        if value := os.environ.get("GAIA_RHYTHMS_HTTP_PORT"):
            self.http_port = int(value)
        if value := os.environ.get("GAIA_RHYTHMS_OSC_HOST"):
            self.osc_host = value
        if value := os.environ.get("GAIA_RHYTHMS_OSC_PORT"):
            self.osc_port = int(value)

    def validate(self) -> None:
        """Normalize values and reject unsafe ranges."""
        self.http_host = str(self.http_host).strip() or "0.0.0.0"
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
        self.continuous_interval_seconds = max(
            5.0, min(300.0, float(self.continuous_interval_seconds))
        )
        self.osc_enabled = bool(self.osc_enabled)
        if not isinstance(self.enabled_sources, list):
            raise ValueError("Enabled sources must be a list")
        self.enabled_sources = [
            source for source in SUPPORTED_SOURCES if source in self.enabled_sources
        ]
        if not isinstance(self.event_instruments, dict):
            raise ValueError("Event instrument mappings must be an object")
        normalized_instruments = {}
        for kind, default in DEFAULT_EVENT_INSTRUMENTS.items():
            instrument = str(self.event_instruments.get(kind, default))
            if instrument not in EVENT_INSTRUMENT_OPTIONS[kind]:
                raise ValueError(
                    f"Unsupported SuperCollider instrument for {kind}: {instrument}"
                )
            normalized_instruments[kind] = instrument
        self.event_instruments = normalized_instruments

    def save(self, path: Path) -> None:
        """Atomically save the current configuration."""
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def resolve_data_dir() -> Path:
    """Resolve writable state without depending on the source checkout."""
    override = os.environ.get("GAIA_RHYTHMS_DATA_DIR")
    return Path(override).expanduser().resolve() if override else Path.cwd() / "data"


def _port(value: object, label: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} port must be between 1 and 65535")
    return port
