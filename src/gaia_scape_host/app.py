"""FastAPI application and local web control surface.

The application factory binds validated installation settings to the service
layer and exposes the dashboard, status, capture, playback, and settings APIs.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import (
    AppConfig,
    BACKGROUND_INSTRUMENT_OPTIONS,
    EVENT_VOICE_OPTIONS,
    default_forecast_locations,
    event_kind_for_voice,
    event_mappings_for_slots,
    resolve_data_dir,
)
from .geoip import GeoIpLocationResolver
from .open_meteo import STORM_LOCATIONS, SURF_LOCATIONS
from .service import GaiaScapeService


PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Environment(
    loader=FileSystemLoader(PACKAGE_DIR / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


def create_app(
    data_dir=None,
    auto_capture=True,
    usgs_client=None,
    marine_client=None,
    storm_client=None,
    glm_client=None,
    geoip_resolver=None,
) -> FastAPI:
    """Create an isolated application, optionally disabling network polling."""
    runtime_data = Path(data_dir) if data_dir is not None else resolve_data_dir()
    runtime_data.mkdir(parents=True, exist_ok=True)
    config_path = runtime_data / "config.json"
    config = AppConfig.load(config_path)
    if not config_path.exists():
        config.save(config_path)
    service = GaiaScapeService(
        config,
        runtime_data,
        usgs_client=usgs_client,
        marine_client=marine_client,
        storm_client=storm_client,
        glm_client=glm_client,
    )
    system_location = geoip_resolver or GeoIpLocationResolver()

    @asynccontextmanager
    async def lifespan(app):
        """Start and stop background service tasks with the web application."""
        if auto_capture:
            await service.start_polling()
        if config.live_mode == "continuous":
            await service.start_continuous()
        yield
        await service.stop()

    app = FastAPI(title="Gaia Scape", version=_version(), lifespan=lifespan)
    app.state.config = config
    app.state.config_path = config_path
    app.state.service = service
    app.state.system_location = system_location
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Render the dashboard with the installation's current settings."""
        template = TEMPLATES.get_template("index.html")
        return template.render(
            request=request,
            version=_version(),
            default_hours=config.replay_hours,
            default_duration=config.performance_seconds,
            live_mode=config.live_mode,
            app_view=config.app_view,
            enabled_sources=set(config.enabled_sources),
            units=config.units,
            instrument_slots=config.instrument_slots(),
            instrument_volumes=config.volume_slots(),
            lightning_sample_rate=config.lightning_sample_rate,
            event_voice_options=EVENT_VOICE_OPTIONS,
            background_options=BACKGROUND_INSTRUMENT_OPTIONS,
            forecast_location_catalogs={
                "ocean_swell": config.ocean_swell_locations,
                "storm_outlook": config.storm_outlook_locations,
            },
            default_forecast_location_catalogs={
                "ocean_swell": default_forecast_locations(SURF_LOCATIONS),
                "storm_outlook": default_forecast_locations(STORM_LOCATIONS),
            },
        )

    @app.get("/healthz")
    async def healthz():
        """Report process health and the running application version."""
        return {"status": "ok", "version": _version()}

    @app.get("/api/status")
    async def status():
        """Return the current capture, playback, source, and renderer status."""
        return await service.status()

    @app.get("/api/system-location")
    async def system_location_status():
        """Return the host's approximate, session-cached public-IP location."""
        location = await asyncio.to_thread(system_location.resolve)
        return {"location": location}

    @app.get("/api/events")
    async def events(hours: float | None = None, limit: int = 500):
        """Return recent visible environmental events for the dashboard."""
        return {"events": await service.recent_events(hours=hours, limit=limit)}

    @app.get("/api/cues")
    async def cues(after: int | None = None):
        """Long-poll for renderer cues emitted after an optional sequence."""
        return await service.emitted_cues(after=after)

    @app.post("/api/capture")
    async def capture():
        """Run one capture cycle for the configured non-GLM providers."""
        try:
            return await service.capture_once()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/performance/replay")
    async def replay(request: Request):
        """Start a time-scaled replay from the requested history window."""
        body = await _json_body(request)
        try:
            return await service.replay(
                hours=body.get("hours"),
                performance_seconds=body.get("performance_seconds"),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/performance/stop")
    async def stop_performance():
        """Stop the active history replay, if any."""
        await service.player.stop()
        return {"stopped": True}

    @app.put("/api/live/mode")
    async def update_live_mode(request: Request):
        """Validate, apply, and persist the selected live mode."""
        body = await _json_body(request)
        try:
            await service.set_live_mode(body.get("mode", ""))
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return (await service.status())["live"]

    @app.put("/api/settings/view")
    async def update_app_view(request: Request):
        """Validate and persist the user's selected application view."""
        body = await _json_body(request)
        previous_view = config.app_view
        try:
            config.app_view = body.get("view", "")
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            config.app_view = previous_view
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"view": config.app_view}

    @app.post("/api/live/start")
    async def start_live():
        """Start continuous environmental playback when that mode is selected."""
        if config.live_mode != "continuous":
            raise HTTPException(status_code=409, detail="Select Continuous mode first")
        await service.start_continuous()
        return (await service.status())["live"]

    @app.post("/api/live/stop")
    async def stop_live():
        """Stop continuous environmental playback without changing its mode."""
        await service.stop_continuous()
        return (await service.status())["live"]

    @app.get("/api/config")
    async def get_config():
        """Return the validated installation configuration."""
        from dataclasses import asdict

        return asdict(config)

    @app.put("/api/settings/audio")
    async def update_audio_settings(request: Request):
        """Validate, apply, and persist source and audio settings."""
        body = await _json_body(request)
        sources = body.get("enabled_sources", [])
        if not isinstance(sources, list):
            raise HTTPException(status_code=422, detail="Invalid audio settings")
        try:
            if "instrument_slots" in body:
                mappings = event_mappings_for_slots(body["instrument_slots"])
            else:
                legacy = body.get("event_instruments", {})
                if not isinstance(legacy, dict):
                    raise ValueError("Event instrument mappings must be an object")
                mappings = AppConfig(event_instruments=legacy)
                mappings._migrate_legacy_instruments()
                mappings = mappings.instrument_slots()
            service.apply_audio_settings(
                sources,
                mappings,
                body.get("units", config.units),
                body.get("instrument_volumes", config.instrument_volumes),
                body.get("lightning_sample_rate", config.lightning_sample_rate),
            )
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "enabled_sources": list(config.enabled_sources),
            "units": config.units,
            "instrument_slots": config.instrument_slots(),
            "event_instruments": dict(config.event_instruments),
            "instrument_volumes": config.volume_slots(),
            "lightning_sample_rate": config.lightning_sample_rate,
        }

    @app.put("/api/settings/locations")
    async def update_forecast_locations(request: Request):
        """Validate, apply, and persist editable forecast sampling locations."""
        body = await _json_body(request)
        try:
            pruned = service.apply_forecast_locations(
                body.get("ocean_swell_locations"),
                body.get("storm_outlook_locations"),
            )
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "ocean_swell_locations": config.ocean_swell_locations,
            "storm_outlook_locations": config.storm_outlook_locations,
            "pruned": pruned,
        }

    @app.post("/api/instruments/preview")
    async def preview_instrument(request: Request):
        """Render one representative cue for a selected instrument."""
        body = await _json_body(request)
        try:
            instrument = body.get("instrument", "")
            kind = body.get("kind")
            if instrument in EVENT_VOICE_OPTIONS and instrument != "none":
                kind = event_kind_for_voice(instrument)
            return await service.preview_instrument(
                instrument, kind or "earthquake", body.get("volume", 1.0)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Expected a JSON object") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    return body


def _version() -> str:
    try:
        value = metadata.version("gaia-scape")
    except metadata.PackageNotFoundError:
        return "development"
    return value if value.startswith("v") else f"v{value}"
