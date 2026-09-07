"""FastAPI application and local web control surface.

The application factory binds validated installation settings to the service
layer and exposes the dashboard, status, capture, playback, and settings APIs.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from gaiascapes import __version__

from .config import (
    AppConfig,
    BACKGROUND_INSTRUMENT_OPTIONS,
    EVENT_VOICE_OPTIONS,
    default_forecast_locations,
    default_birdsong_locations,
    default_frog_locations,
    event_kind_for_voice,
    event_mappings_for_slots,
    locations_with_system_location,
    resolve_data_dir,
)
from .sanctsound import MARINE_KINDS, available_locations
from .geoip import GeoIpLocationResolver
from .open_meteo import STORM_LOCATIONS, SURF_LOCATIONS
from .service import GaiascapesService


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
    mtg_li_client=None,
    birdsong_client=None,
    geoip_resolver=None,
    frog_calls_client=None,
    whale_song_client=None,
    dolphin_calls_client=None,
) -> FastAPI:
    """Create an isolated application, optionally disabling network polling."""
    runtime_data = Path(data_dir) if data_dir is not None else resolve_data_dir()
    runtime_data.mkdir(parents=True, exist_ok=True)
    for kind in ("birdsong", "frog_calls", *MARINE_KINDS):
        (runtime_data / "media" / kind).mkdir(parents=True, exist_ok=True)
    config_path = runtime_data / "config.json"
    config = AppConfig.load(config_path)
    if not config_path.exists():
        config.save(config_path)
    service = GaiascapesService(
        config,
        runtime_data,
        usgs_client=usgs_client,
        marine_client=marine_client,
        storm_client=storm_client,
        glm_client=glm_client,
        mtg_li_client=mtg_li_client,
        birdsong_client=birdsong_client,
        frog_calls_client=frog_calls_client,
        whale_song_client=whale_song_client,
        dolphin_calls_client=dolphin_calls_client,
    )
    system_location = geoip_resolver or GeoIpLocationResolver()
    resolved_location = None
    sound_locations_initialized = False
    location_lock = asyncio.Lock()

    def local_sound_defaults():
        """Return reset catalogs with the resolved host in the first slot."""
        location = resolved_location if config.system_location_enabled else None
        return {
            kind: locations_with_system_location(catalog, location)
            for kind, catalog in (
                ("birdsong", default_birdsong_locations()),
                ("frog_calls", default_frog_locations()),
                ("storm_outlook", default_forecast_locations(STORM_LOCATIONS)),
            )
        }

    async def initialize_sound_locations():
        """Resolve once per session and commit local sampling centers before polling."""
        nonlocal resolved_location, sound_locations_initialized
        async with location_lock:
            if not config.system_location_enabled:
                return None
            if resolved_location is None:
                location = await asyncio.to_thread(system_location.resolve)
                if not config.system_location_enabled or location is None:
                    return None
                resolved_location = location
            if not sound_locations_initialized:
                changes = {}
                for name in ("birdsong_locations", "frog_calls_locations", "storm_outlook_locations"):
                    catalog = locations_with_system_location(getattr(config, name), resolved_location)
                    if catalog != getattr(config, name):
                        changes[name] = catalog
                if changes:
                    await service.update_settings(changes, config_path)
                sound_locations_initialized = True
            return resolved_location

    @asynccontextmanager
    async def lifespan(app):
        """Start and stop background service tasks with the web application."""
        try:
            if auto_capture:
                await initialize_sound_locations()
                await service.start_polling()
            if config.live_mode == "continuous":
                await service.start_continuous()
            yield
        finally:
            await service.stop()

    app = FastAPI(title="Gaiascapes", version=_version(), lifespan=lifespan)
    app.state.config = config
    app.state.config_path = config_path
    app.state.service = service
    app.state.system_location = system_location
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.mount(
        "/birdsong-media",
        StaticFiles(directory=runtime_data / "media" / "birdsong"),
        name="birdsong-media",
    )

    app.mount(
        "/frog-calls-media",
        StaticFiles(directory=runtime_data / "media" / "frog_calls"),
        name="frog-calls-media",
    )

    for kind in MARINE_KINDS:
        name = f'{kind.replace("_", "-")}-media'
        app.mount(f"/{name}", StaticFiles(directory=runtime_data / "media" / kind), name=name)

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
            map_projection=config.map_projection,
            system_location_enabled=config.system_location_enabled,
            enabled_sources=set(config.enabled_sources),
            units=config.units,
            instrument_slots=config.instrument_slots(),
            instrument_volumes=config.volume_slots(),
            lightning_sample_rate=config.lightning_sample_rate,
            whale_song_enabled=config.whale_song_enabled,
            dolphin_calls_enabled=config.dolphin_calls_enabled,
            frog_calls_enabled=config.frog_calls_enabled,
            birdsong_enabled=config.birdsong_enabled,
            birdsong_provider=config.birdsong_provider,
            xeno_canto_credentials_configured=bool(config.xeno_canto_api_key),
            eumetsat_credentials_configured=bool(
                config.eumetsat_consumer_key and config.eumetsat_consumer_secret
            ),
            event_voice_options=EVENT_VOICE_OPTIONS,
            background_options=BACKGROUND_INSTRUMENT_OPTIONS,
            forecast_location_catalogs={
                **{kind: [dict(location, selected=location["id"] in getattr(config, f"{kind}_regions"))
                          for location in available_locations(kind)] for kind in MARINE_KINDS},
                "frog_calls": config.frog_calls_locations,
                "birdsong": config.birdsong_locations,
                "commons_birdsong": default_birdsong_locations(),
                "ocean_swell": config.ocean_swell_locations,
                "storm_outlook": config.storm_outlook_locations,
            },
            default_forecast_location_catalogs={
                **{kind: [dict(location, selected=True) for location in available_locations(kind)]
                   for kind in MARINE_KINDS},
                **local_sound_defaults(),
                "ocean_swell": default_forecast_locations(SURF_LOCATIONS),
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
        """Return the cached host location and initialized sound sampling catalogs."""
        if not config.system_location_enabled:
            return {"location": None}
        location = await initialize_sound_locations()
        if not config.system_location_enabled:
            return {"location": None}
        return {
            "location": location,
            "sound_locations": {
                kind: getattr(config, f"{kind}_locations")
                for kind in ("birdsong", "frog_calls", "storm_outlook")
            },
            "default_sound_locations": local_sound_defaults(),
        }

    @app.get("/api/events")
    async def events(hours: float | None = None, limit: int = 500):
        """Return recent visible environmental events for the dashboard."""
        return {"events": await service.recent_events(hours=hours, limit=limit)}

    @app.get("/api/cues")
    async def cues(after: int | None = None):
        """Long-poll for renderer cues emitted after an optional sequence."""
        return await service.emitted_cues(after=after)

    @app.post("/api/recordings/advance")
    async def advance_recording(request: Request):
        """Advance only the current continuous recording's location."""
        body = await _json_body(request)
        try:
            return {"advanced": service.advance_recording(body.get("sequence"))}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            await service.update_settings({"live_mode": body.get("mode", "")}, config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return (await service.status())["live"]

    @app.put("/api/settings/view")
    async def update_app_view(request: Request):
        """Validate and persist the user's selected application view."""
        body = await _json_body(request)
        try:
            await service.update_settings({"app_view": body.get("view", "")}, config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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
        """Return validated configuration without provider credentials."""
        from dataclasses import asdict

        document = asdict(config)
        document.pop("eumetsat_consumer_key", None)
        document.pop("eumetsat_consumer_secret", None)
        document.pop("xeno_canto_api_key", None)
        document["xeno_canto_credentials_configured"] = bool(config.xeno_canto_api_key)
        document["eumetsat_credentials_configured"] = bool(
            config.eumetsat_consumer_key and config.eumetsat_consumer_secret
        )
        return document

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
            changes = {
                "enabled_sources": sources, "event_instruments": mappings,
                "units": body.get("units", config.units),
                "system_location_enabled": body.get("system_location_enabled", config.system_location_enabled),
                "instrument_volumes": body.get("instrument_volumes", config.instrument_volumes),
                "lightning_sample_rate": body.get("lightning_sample_rate", config.lightning_sample_rate),
                **{f"{kind}_enabled": body.get(f"{kind}_enabled", getattr(config, f"{kind}_enabled"))
                   for kind in MARINE_KINDS},
                "frog_calls_enabled": body.get("frog_calls_enabled", config.frog_calls_enabled),
                "birdsong_enabled": body.get("birdsong_enabled", config.birdsong_enabled),
                "birdsong_provider": body.get("birdsong_provider", config.birdsong_provider),
            }
            for name in ("eumetsat_consumer_key", "eumetsat_consumer_secret", "xeno_canto_api_key"):
                if body.get(name):
                    changes[name] = body[name]
            await service.update_settings(changes, config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "enabled_sources": list(config.enabled_sources),
            **{f"{kind}_enabled": getattr(config, f"{kind}_enabled") for kind in MARINE_KINDS},
            "frog_calls_enabled": config.frog_calls_enabled,
            "birdsong_enabled": config.birdsong_enabled,
            "birdsong_provider": config.birdsong_provider,
            "xeno_canto_credentials_configured": bool(config.xeno_canto_api_key),
            "units": config.units,
            "instrument_slots": config.instrument_slots(),
            "event_instruments": dict(config.event_instruments),
            "instrument_volumes": config.volume_slots(),
            "lightning_sample_rate": config.lightning_sample_rate,
            "eumetsat_credentials_configured": bool(
                config.eumetsat_consumer_key and config.eumetsat_consumer_secret
            ),
        }

    @app.put("/api/settings/locations")
    async def update_forecast_locations(request: Request):
        """Persist sound locations and the shared map projection."""
        body = await _json_body(request)
        try:
            pruned = await service.update_settings({
                **{f"{kind}_regions": body.get(f"{kind}_regions", getattr(config, f"{kind}_regions"))
                   for kind in MARINE_KINDS},
                "frog_calls_locations": body.get("frog_calls_locations", config.frog_calls_locations),
                "birdsong_locations": body.get("birdsong_locations", config.birdsong_locations),
                "map_projection": body.get("map_projection", config.map_projection),
                "ocean_swell_locations": body.get("ocean_swell_locations"),
                "storm_outlook_locations": body.get("storm_outlook_locations"),
            }, config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "map_projection": config.map_projection,
            **{f"{kind}_regions": getattr(config, f"{kind}_regions") for kind in MARINE_KINDS},
            "frog_calls_locations": config.frog_calls_locations,
            "birdsong_locations": config.birdsong_locations,
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
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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
    return __version__
