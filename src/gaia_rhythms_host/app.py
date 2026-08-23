"""FastAPI application and local web control surface."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import metadata
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import AppConfig, EVENT_INSTRUMENT_OPTIONS, resolve_data_dir
from .service import GaiaRhythmsService


PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES = Environment(
    loader=FileSystemLoader(PACKAGE_DIR / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


def create_app(data_dir=None, auto_capture=True, usgs_client=None, marine_client=None, storm_client=None) -> FastAPI:
    """Create an isolated application, optionally disabling network polling."""
    runtime_data = Path(data_dir) if data_dir is not None else resolve_data_dir()
    runtime_data.mkdir(parents=True, exist_ok=True)
    config_path = runtime_data / "config.json"
    config = AppConfig.load(config_path)
    if not config_path.exists():
        config.save(config_path)
    service = GaiaRhythmsService(
        config,
        runtime_data,
        usgs_client=usgs_client,
        marine_client=marine_client,
        storm_client=storm_client,
    )

    @asynccontextmanager
    async def lifespan(app):
        if auto_capture:
            await service.start_polling()
        if config.live_mode == "continuous":
            await service.start_continuous()
        yield
        await service.stop()

    app = FastAPI(title="Gaia Rhythms", version=_version(), lifespan=lifespan)
    app.state.config = config
    app.state.config_path = config_path
    app.state.service = service
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        template = TEMPLATES.get_template("index.html")
        return template.render(
            request=request,
            version=_version(),
            default_hours=config.replay_hours,
            default_duration=config.performance_seconds,
            live_mode=config.live_mode,
            enabled_sources=set(config.enabled_sources),
            event_instruments=dict(config.event_instruments),
            instrument_options=EVENT_INSTRUMENT_OPTIONS,
        )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": _version()}

    @app.get("/api/status")
    async def status():
        return await service.status()

    @app.get("/api/events")
    async def events(hours: float | None = None, limit: int = 500):
        return {"events": await service.recent_events(hours=hours, limit=limit)}

    @app.get("/api/cues")
    async def cues(after: int | None = None):
        return await service.emitted_cues(after=after)

    @app.post("/api/capture")
    async def capture():
        try:
            return await service.capture_once()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/performance/replay")
    async def replay(request: Request):
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
        await service.player.stop()
        return {"stopped": True}

    @app.put("/api/live/mode")
    async def update_live_mode(request: Request):
        body = await _json_body(request)
        try:
            await service.set_live_mode(body.get("mode", ""))
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return (await service.status())["live"]

    @app.post("/api/live/start")
    async def start_live():
        if config.live_mode != "continuous":
            raise HTTPException(status_code=409, detail="Select Continuous mode first")
        await service.start_continuous()
        return (await service.status())["live"]

    @app.post("/api/live/stop")
    async def stop_live():
        await service.stop_continuous()
        return (await service.status())["live"]

    @app.get("/api/config")
    async def get_config():
        from dataclasses import asdict

        return asdict(config)

    @app.put("/api/settings/audio")
    async def update_audio_settings(request: Request):
        body = await _json_body(request)
        sources = body.get("enabled_sources", [])
        mappings = body.get("event_instruments", {})
        if not isinstance(sources, list) or not isinstance(mappings, dict):
            raise HTTPException(status_code=422, detail="Invalid audio settings")
        try:
            service.apply_audio_settings(sources, mappings)
            config.save(config_path)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "enabled_sources": list(config.enabled_sources),
            "event_instruments": dict(config.event_instruments),
        }

    @app.post("/api/instruments/preview")
    async def preview_instrument(request: Request):
        body = await _json_body(request)
        try:
            return await service.preview_instrument(body.get("instrument", ""), body.get("kind", "earthquake"))
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
        value = metadata.version("gaia-rhythms")
    except metadata.PackageNotFoundError:
        return "development"
    return value if value.startswith("v") else f"v{value}"
