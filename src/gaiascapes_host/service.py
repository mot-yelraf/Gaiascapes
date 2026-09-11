"""Application orchestration for capture, history, and performance.

The service coordinates independent providers, persistent event history,
continuous sound layers, live cues, replay scheduling, and status reporting.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import shutil
import time
from collections import deque
from dataclasses import dataclass, fields
from pathlib import Path

from gaiascapes.events import GaiaEvent
from gaiascapes.score import ScoreCue, build_score, event_duration

from .capture import EventStore
from .contracts import EventProvider
from .sanctsound import MARINE_KINDS, SanctSoundClient
from .commons_birdsong import CommonsBirdsongClient
from .xeno_canto import NoRecordingsError, XenoCantoClient
from .config import AppConfig, EVENT_INSTRUMENT_OPTIONS, SUPPORTED_SOURCES, EVENT_KIND_BY_VOICE
from .eumetsat_li import EumetsatLiClient
from .open_meteo import (
    OpenMeteoMarineClient,
    OpenMeteoStormClient,
    provider_locations,
)
from .noaa_glm import GLM_POLL_SECONDS, NoaaGlmClient
from .osc import OscRenderer
from .history import HistoryView, BACKGROUND_HISTORY_KINDS, HIDDEN_HISTORY_KINDS
from .settings import settings_candidate, persist_settings
from .polling import PollingCoordinator
from .playback import PlaybackController, render_call
from .performance import PerformancePlayer, cue_with_gain
from .usgs import UsgsClient


CUE_LONG_POLL_SECONDS = 2.0
EMITTED_CUE_LIMIT = 10000
LOGGER = logging.getLogger("uvicorn.error")
GLM_SONIFICATION_TIME_SCALE = 1.0
MTG_PRESENTATION_DELAY_SECONDS = 12 * 60.0
MTG_LATE_EVENT_TOLERANCE_SECONDS = 5.0
RECOVERY_MAX_RETRY_SECONDS = 15 * 60.0
GLM_FALLBACK_MAX_AGE_SECONDS = 5 * 60.0
FORECAST_FALLBACK_MAX_AGE_SECONDS = 3 * 60 * 60.0
SOURCE_FETCH_TIMEOUT_SECONDS = 45.0
SOURCE_LABELS = {
    "usgs": "USGS earthquakes",
    "open_meteo_marine": "Open-Meteo marine",
    "open_meteo_storm": "Open-Meteo storm outlook",
    "noaa_glm": "NOAA GLM lightning",
    "eumetsat_mtg_li": "EUMETSAT MTG lightning",
}
SOURCE_FALLBACK_MAX_AGE = {
    "open_meteo_marine": FORECAST_FALLBACK_MAX_AGE_SECONDS,
    "open_meteo_storm": FORECAST_FALLBACK_MAX_AGE_SECONDS,
    "noaa_glm": GLM_FALLBACK_MAX_AGE_SECONDS,
    "eumetsat_mtg_li": 30 * 60.0,
}


@dataclass
class _SourceRecovery:
    """Track one provider's observable recovery state without persisting config."""

    state: str = "waiting"
    consecutive_failures: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_data_at: float | None = None
    retry_at: float | None = None
    last_error: str = ""
    using_fallback: bool = False
    transition: int = 0
    transition_at: float | None = None
    notify: bool = False


class GaiascapesService:
    """Coordinate provider polling without coupling it to HTTP routes."""

    def __init__(
        self,
        config: AppConfig,
        data_dir: Path,
        usgs_client: EventProvider | None = None,
        marine_client: EventProvider | None = None,
        storm_client: EventProvider | None = None,
        glm_client: EventProvider | None = None,
        mtg_li_client: EventProvider | None = None,
        birdsong_client=None,
        frog_calls_client=None,
        whale_song_client=None,
        dolphin_calls_client=None,
    ):
        self.config = config
        self.data_dir = Path(data_dir)
        self.store = EventStore(_resolve_event_database(self.data_dir))
        self.store.initialize()
        self.history = HistoryView(self.store)
        self.polling = PollingCoordinator(SUPPORTED_SOURCES)
        self.playback = PlaybackController()
        self._settings_lock = asyncio.Lock()
        self._playback_lifecycle_lock = asyncio.Lock()
        self._source_recovery = {
            source: _SourceRecovery(
                last_data_at=self.store.latest_ingested_at_for_provider(source)
            )
            for source in SUPPORTED_SOURCES
        }
        self._overall_recovery = _SourceRecovery()
        self.usgs = usgs_client or UsgsClient(config.usgs_url)
        self.marine = marine_client or OpenMeteoMarineClient(
            locations=provider_locations(config.ocean_swell_locations, "swell")
        )
        self.storm = storm_client or OpenMeteoStormClient(
            locations=provider_locations(config.storm_outlook_locations, "storm")
        )
        self.glm = glm_client or NoaaGlmClient()
        self.glm.sonification_sample_stride = config.lightning_sample_rate
        self.mtg_li = mtg_li_client or EumetsatLiClient(
            config.eumetsat_consumer_key, config.eumetsat_consumer_secret
        )
        self.birdsong = birdsong_client or (
            XenoCantoClient(self.data_dir, config.xeno_canto_api_key, locations=config.birdsong_locations)
            if config.birdsong_provider == "xeno_canto"
            else CommonsBirdsongClient(self.data_dir)
        )
        self.frog_calls = frog_calls_client or XenoCantoClient(
            self.data_dir, config.xeno_canto_api_key, locations=config.frog_calls_locations, group="frogs"
        )
        self.whale_song = whale_song_client or SanctSoundClient(
            self.data_dir, "whale_song", config.whale_song_regions
        )
        self.dolphin_calls = dolphin_calls_client or SanctSoundClient(
            self.data_dir, "dolphin_calls", config.dolphin_calls_regions
        )
        self.renderer = OscRenderer(
            config.osc_host,
            config.osc_port,
            config.osc_enabled,
            config.background_mappings(),
        )
        self._replay_lightning_counts = {}
        self._cue_sequence = 0
        self._emitted_cues = deque(maxlen=EMITTED_CUE_LIMIT)
        self._cue_event = asyncio.Event()
        self._latest_sound_location = None
        self._latest_background_location = None
        self._published_background_state = {}
        self.player = PerformancePlayer(
            self.renderer,
            self._record_replay_cue,
            lambda cue: self._voices_with_channels(cue.kind),
        )
        self._glm_sonification_task = None
        self._last_glm_sonification_events = ()
        self._glm_replaying_cached_field = False
        self._mtg_sonification_tasks = set()
        self._mtg_scheduled_products = deque(maxlen=2048)
        self.last_mtg_scheduled_count = 0
        self.mtg_played_count = 0
        self.mtg_skipped_late_count = 0
        self._continuous_task = None
        self._glm_capture_lock = asyncio.Lock()
        self._live_play_lock = asyncio.Lock()
        self._ambient_cursors = {
            kind: 0 for kind in ("ocean_swell", "storm_potential", "birdsong", "frog_calls", *MARINE_KINDS)
        }
        self._recording_status = {
            kind: {"state": "idle", "error": ""}
            for kind in ("birdsong", "frog_calls", *MARINE_KINDS)
        }
        self._recording_sequences = {}
        self._recording_advance = asyncio.Event()
        self._last_continuous_cycle_at = time.time()
        self.continuous_played_count = 0
        self.continuous_last_error = ""
        self.last_capture_at = None
        self.last_capture_count = 0
        self.last_capture_inserted = 0
        self.last_capture_error = ""
        self.last_glm_capture_at = None
        self.last_glm_received = 0
        self.last_glm_inserted = 0
        self.last_glm_error = ""
        self._restore_glm_fallback()

    def _restore_glm_fallback(self) -> None:
        """Restore one recent persisted lightning field after an app restart."""
        recent = self.store.events_of_kinds_since(
            ("lightning_flash",),
            time.time() - GLM_FALLBACK_MAX_AGE_SECONDS,
            500, provider="noaa_glm", newest_first=True,
        )
        if not recent:
            return
        newest = max(event.timestamp for event in recent)
        self._last_glm_sonification_events = tuple(
            event for event in reversed(recent) if event.timestamp >= newest - GLM_POLL_SECONDS
        )[-120:]

    async def _fetch_source(self, source: str, client):
        """Bound a provider fetch and prevent overlapping worker calls."""
        return await self.polling.fetch(source, client, SOURCE_FETCH_TIMEOUT_SECONDS)

    def _source_can_retry(self, source: str) -> bool:
        retry_at = self._source_recovery[source].retry_at
        return retry_at is None or time.time() >= retry_at

    def _source_has_fresh_fallback(self, source: str, now: float | None = None) -> bool:
        maximum_age = SOURCE_FALLBACK_MAX_AGE.get(source)
        data_at = self._source_recovery[source].last_data_at
        if maximum_age is None or data_at is None:
            return False
        current = time.time() if now is None else float(now)
        return current - data_at <= maximum_age

    def _set_source_state(self, source: str, state: str, notify: bool) -> None:
        recovery = self._source_recovery[source]
        if recovery.state != state:
            recovery.state = state
            recovery.transition += 1
            recovery.transition_at = time.time()
        recovery.notify = notify

    def _mark_source_recovering(self, source: str) -> None:
        recovery = self._source_recovery[source]
        if recovery.consecutive_failures:
            self._set_source_state(source, "recovering", True)

    def _mark_source_success(self, source: str, events, client=None) -> None:
        now = time.time()
        recovery = self._source_recovery[source]
        had_failures = bool(recovery.consecutive_failures or recovery.using_fallback)
        used_fallback = bool(
            client is not None and getattr(client, "last_fetch_used_fallback", False)
        )
        client_error = str(getattr(client, "last_error", "")) if client else ""
        if used_fallback or client_error:
            if events:
                recovery.last_data_at = now
            self._mark_source_failure(
                source,
                RuntimeError(
                    client_error or "Cached provider data is in use."
                ),
            )
            if events:
                recovery.using_fallback = True
                self._set_source_state(source, "degraded", True)
            return
        recovery.last_success_at = now
        recovery.last_data_at = now
        recovery.retry_at = None
        recovery.consecutive_failures = 0
        recovery.last_error = ""
        recovery.using_fallback = False
        self._set_source_state(source, "online", had_failures)

    def _mark_source_failure(self, source: str, error: Exception) -> None:
        now = time.time()
        recovery = self._source_recovery[source]
        recovery.consecutive_failures += 1
        recovery.last_failure_at = now
        base_delay = (
            GLM_POLL_SECONDS if source == "noaa_glm" else self.config.poll_seconds
        )
        delay = min(
            RECOVERY_MAX_RETRY_SECONDS,
            float(base_delay) * (2 ** min(recovery.consecutive_failures - 1, 8)),
        )
        delay += random.uniform(0.0, min(float(base_delay) * 0.2, 30.0))
        recovery.retry_at = now + delay
        recovery.last_error = _capture_error_message(source, error)
        recovery.using_fallback = self._source_has_fresh_fallback(source, now)
        self._set_source_state(
            source, "degraded" if recovery.using_fallback else "offline", True
        )

    def _source_recovery_status(self, source: str) -> dict:
        now = time.time()
        recovery = self._source_recovery[source]
        enabled = source in self.config.enabled_sources
        if not enabled:
            return {
                "source": source,
                "label": SOURCE_LABELS[source],
                "enabled": False,
                "state": "disabled",
                "notify": False,
                "transition": recovery.transition,
            }
        fallback_age = (
            None
            if recovery.last_data_at is None
            else max(0.0, now - recovery.last_data_at)
        )
        retry_seconds = (
            None
            if recovery.retry_at is None
            else max(0, round(recovery.retry_at - now))
        )
        label = SOURCE_LABELS[source]
        if recovery.state == "online":
            message = f"{label} recovered. Live data has resumed."
            severity = "success"
        elif recovery.state == "recovering":
            message = f"{label} is attempting automatic recovery."
            severity = "info"
        elif recovery.state == "degraded":
            age_text = (
                ""
                if fallback_age is None
                else f" Cached data age: {round(fallback_age / 60)} minutes."
            )
            retry_text = (
                "" if retry_seconds is None else f" Retrying in {retry_seconds} seconds."
            )
            error_text = (
                "" if not recovery.last_error else f" Last error: {recovery.last_error}"
            )
            message = (
                f"{label} is degraded; cached data remains active."
                f"{age_text}{retry_text}{error_text}"
            )
            severity = "warning"
        elif recovery.state == "offline":
            retry_text = (
                "" if retry_seconds is None else f" Retrying in {retry_seconds} seconds."
            )
            error_text = (
                "" if not recovery.last_error else f" Last error: {recovery.last_error}"
            )
            message = f"{label} is offline.{retry_text}{error_text}"
            severity = "error"
        else:
            message = f"{label} is waiting for its first update."
            severity = "info"
        return {
            "source": source,
            "label": label,
            "enabled": True,
            "state": recovery.state,
            "severity": severity,
            "message": message,
            "notify": bool(
                recovery.notify
                and recovery.transition_at is not None
                and now - recovery.transition_at <= 5 * 60
            ),
            "transition": recovery.transition,
            "consecutive_failures": recovery.consecutive_failures,
            "last_success_at": recovery.last_success_at,
            "last_failure_at": recovery.last_failure_at,
            "last_data_at": recovery.last_data_at,
            "last_error": recovery.last_error,
            "using_fallback": recovery.using_fallback,
            "fallback_age_seconds": fallback_age,
            "freshness_limit_seconds": SOURCE_FALLBACK_MAX_AGE.get(source),
            "retry_at": recovery.retry_at,
            "retry_seconds": retry_seconds,
        }

    def _overall_recovery_status(self, health: dict[str, dict]) -> dict:
        """Summarize whether the enabled provider set can supply live data."""
        enabled = [item for item in health.values() if item["enabled"]]
        states = {item["state"] for item in enabled}
        if not enabled:
            state = "disabled"
        elif states == {"online"}:
            state = "online"
        elif states <= {"waiting"}:
            state = "waiting"
        elif "waiting" in states and not states.intersection({"offline", "degraded"}):
            state = "waiting"
        elif states <= {"offline"}:
            state = "offline"
        elif "recovering" in states and not states.intersection({"online", "degraded"}):
            state = "recovering"
        else:
            state = "degraded"
        previous = self._overall_recovery.state
        overall = self._overall_recovery
        if overall.state != state:
            overall.state = state
            overall.transition += 1
            overall.transition_at = time.time()
        overall.notify = state not in {"disabled", "waiting"} and not (
            previous == "waiting" and state == "online"
        )
        messages = {
            "online": "All enabled environmental data sources are online.",
            "degraded": "Gaiascapes is degraded. At least one enabled data source is using fallback data or recovering.",
            "offline": "All enabled environmental data sources are offline. Automatic recovery will continue.",
            "recovering": "Gaiascapes is attempting to recover its environmental data sources.",
            "waiting": "Gaiascapes is waiting for its first environmental data update.",
            "disabled": "No environmental data sources are enabled.",
        }
        severities = {
            "online": "success",
            "degraded": "warning",
            "offline": "error",
            "recovering": "info",
            "waiting": "info",
            "disabled": "info",
        }
        return {
            "source": "all_sources",
            "label": "Environmental data",
            "enabled": bool(enabled),
            "state": state,
            "severity": severities[state],
            "message": messages[state],
            "notify": bool(
                overall.notify
                and overall.transition_at is not None
                and time.time() - overall.transition_at <= 5 * 60
            ),
            "transition": overall.transition,
        }

    async def start_polling(self) -> None:
        """Start one independently scheduled loop per provider."""
        for source in SUPPORTED_SOURCES:
            if source == "noaa_glm":
                self.polling.start(
                    source, lambda: self.capture_glm_once(respect_backoff=True),
                    lambda: GLM_POLL_SECONDS,
                )
            else:
                self.polling.start(
                    source,
                    lambda source=source: self.capture_once(True, source),
                    lambda: self.config.poll_seconds,
                )

    async def start_continuous(self) -> None:
        """Start the ambient live-event stream without duplicating it."""
        async with self._playback_lifecycle_lock:
            self.playback.start()
            if self._continuous_task is None or self._continuous_task.done():
                self._recording_sequences.clear()
                self._last_continuous_cycle_at = time.time()
                self._continuous_task = self.playback.schedule(
                    self._continuous_loop(), name="gaiascapes-continuous"
                )
                await self._restore_mtg_schedule()

    async def stop_continuous(self) -> None:
        """Pause all continuous playback while leaving capture enabled."""
        async with self._playback_lifecycle_lock:
            await self.playback.stop()
            self._recording_sequences.clear()
            self._continuous_task = None
            self._glm_sonification_task = None
            self._glm_replaying_cached_field = False
            self._mtg_sonification_tasks.clear()
            # Cancelled products can resume their remaining timeline on Start.
            self._mtg_scheduled_products.clear()
            async with self._live_play_lock:
                await asyncio.to_thread(self.renderer.stop_layer, "ocean_swell")
                await asyncio.to_thread(self.renderer.stop_layer, "storm_potential")

    async def set_live_mode(self, mode: str) -> None:
        """Select capture or continuous behavior and apply it immediately."""
        previous = self.config.live_mode
        self.config.live_mode = str(mode).strip().lower()
        try:
            self.config.validate()
        except ValueError:
            self.config.live_mode = previous
            raise
        if self.config.live_mode == "continuous":
            await self.player.stop()
            await self.start_continuous()
        else:
            await self.stop_continuous()

    async def stop(self) -> None:
        """Stop provider polling and drain playback tasks."""
        await self.polling.stop()
        await self.stop_continuous()
        await self.player.stop()

    def _capture_clients(self) -> dict[str, EventProvider]:
        return {
            "usgs": self.usgs,
            "open_meteo_marine": self.marine,
            "open_meteo_storm": self.storm,
            "eumetsat_mtg_li": self.mtg_li,
        }

    async def _capture_source(self, source, respect_backoff):
        async with self.polling.capture_locks[source]:
            if source not in self.config.enabled_sources:
                return {"received": 0, "inserted": 0, "pruned": 0, "disabled": True}
            if respect_backoff and not self._source_can_retry(source):
                return {"received": 0, "inserted": 0, "pruned": 0, "backing_off": True}
            client = self._capture_clients()[source]
            locations = getattr(client, "locations", None)
            self._mark_source_recovering(source)
            try:
                events = tuple(await self._fetch_source(source, client))
                async with self._settings_lock:
                    if (source not in self.config.enabled_sources
                            or client is not self._capture_clients()[source]
                            or locations != getattr(client, "locations", None)):
                        return {"received": 0, "inserted": 0, "pruned": 0, "discarded": True}
                    inserted_events = await asyncio.to_thread(self.store.add_new_events, events)
                    pruned = await asyncio.to_thread(
                        self.store.prune_before,
                        time.time() - self.config.retention_days * 86400,
                    )
                    if source.startswith("open_meteo_") and locations:
                        pruned += await asyncio.to_thread(
                            self.store.prune_provider_locations, source, locations
                        )
                    self._mark_source_success(source, events, client)
                    try:
                        if self.playback.enabled and self.config.live_mode == "continuous":
                            earthquakes = [event for event in inserted_events if event.kind == "earthquake"]
                            if earthquakes:
                                await self._play_live_event(max(earthquakes, key=lambda event: event.strength))
                            if source == "eumetsat_mtg_li" and events:
                                self._start_mtg_sonification(events)
                    except Exception as exc:
                        # Audio transport failure must not mark capture offline.
                        self.continuous_last_error = f"Playback failed: {exc}"
                        LOGGER.warning("Live event playback failed: %s", exc)
                    return {"received": len(events), "inserted": len(inserted_events), "pruned": pruned}
            except Exception as exc:
                if client is not self._capture_clients()[source]:
                    return {"received": 0, "inserted": 0, "pruned": 0, "discarded": True}
                self._mark_source_failure(source, exc)
                return {"received": 0, "inserted": 0, "pruned": 0, "error": _capture_error_message(source, exc)}

    async def capture_once(self, respect_backoff: bool = False, source=None) -> dict:
        """Capture enabled feeds concurrently and publish each batch promptly."""
        self.last_capture_at = time.time()
        sources = (source,) if source is not None else tuple(self._capture_clients())
        results = await asyncio.gather(*(
            self._capture_source(item, respect_backoff) for item in sources
        ))
        summary = {key: sum(result[key] for result in results) for key in ("received", "inserted", "pruned")}
        self.last_capture_count = summary["received"]
        self.last_capture_inserted = summary["inserted"]
        errors = [result["error"] for result in results if "error" in result]
        errors.extend(
            self._source_recovery[item].last_error for item, result in zip(sources, results)
            if result.get("backing_off") and self._source_recovery[item].last_error
        )
        self.last_capture_error = "; ".join(dict.fromkeys(errors))
        if results and all(result.get("disabled") for result in results):
            summary["disabled"] = True
        attempted = [result for result in results if not result.get("disabled")]
        if attempted and all("error" in result for result in attempted):
            raise RuntimeError(self.last_capture_error)
        return summary

    async def capture_glm_once(self, respect_backoff: bool = False) -> dict:
        """Retrieve, persist, and sound one independent NOAA GLM update."""
        async with self._glm_capture_lock:
            self.last_glm_capture_at = time.time()
            if "noaa_glm" not in self.config.enabled_sources:
                self.last_glm_received = 0
                self.last_glm_inserted = 0
                self.last_glm_error = ""
                self._glm_replaying_cached_field = False
                return {"received": 0, "inserted": 0, "disabled": True}
            if respect_backoff and not self._source_can_retry("noaa_glm"):
                return {
                    "received": 0,
                    "inserted": 0,
                    "backing_off": True,
                    "retry_at": self._source_recovery["noaa_glm"].retry_at,
                }
            try:
                self._mark_source_recovering("noaa_glm")
                events = tuple(await self._fetch_source("noaa_glm", self.glm))
                self._mark_source_success("noaa_glm", events, self.glm)
                inserted_events = await asyncio.to_thread(
                    self.store.add_new_events, events
                )
                cutoff = time.time() - (self.config.retention_days * 86400)
                pruned = await asyncio.to_thread(self.store.prune_before, cutoff)
                self.last_glm_received = len(events)
                self.last_glm_inserted = len(inserted_events)
                self.last_glm_error = str(getattr(self.glm, "last_error", ""))
                raw_count = int(
                    getattr(self.glm, "last_raw_flash_count", len(events))
                )
                granule_count = int(getattr(self.glm, "last_granule_count", 0))
                sonification_events = tuple(
                    getattr(self.glm, "last_sonification_events", inserted_events)
                )
                selected_count = getattr(
                    self.glm, "last_selected_flash_count", len(sonification_events)
                )
                limit_detail = (
                    f" (safety limit: {selected_count} selected reduced to {len(sonification_events)})"
                    if selected_count > len(sonification_events) else ""
                )
                report = (
                    f"NOAA GLM update: {granule_count} granules, {raw_count} raw flashes, "
                    f"{len(events)} sampled, {len(inserted_events)} new{limit_detail}"
                )
                if sonification_events:
                    self._last_glm_sonification_events = sonification_events
                    self._glm_replaying_cached_field = False
                    if self.playback.enabled and self.config.live_mode == "continuous":
                        self._start_glm_sonification(sonification_events, report=report)
                else:
                    self._replay_last_glm_sonification()
                return {
                    "received": len(events),
                    "raw_flashes": raw_count,
                    "inserted": len(inserted_events),
                    "pruned": pruned,
                }
            except Exception as exc:
                self._mark_source_failure("noaa_glm", exc)
                self.last_glm_error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("NOAA GLM update failed: %s", self.last_glm_error)
                self._replay_last_glm_sonification()
                raise

    async def replay(self, hours=None, performance_seconds=None) -> dict:
        """Build and start a replay from captured history."""
        hours = self.config.replay_hours if hours is None else float(hours)
        duration = (
            self.config.performance_seconds
            if performance_seconds is None
            else float(performance_seconds)
        )
        hours = max(0.05, min(24.0, hours))
        duration = max(1.0, min(3600.0, duration))
        now = time.time()
        window_seconds = hours * 3600.0
        window_start = now - window_seconds
        events = await asyncio.to_thread(self.store.events_since, window_start)
        score = build_score(events, window_start, window_seconds, duration)
        self._replay_lightning_counts = {}
        for cue in score:
            if cue.kind == "lightning_flash" and self._voices_with_channels(cue.kind):
                provider = cue.event.provider
                self._replay_lightning_counts[provider] = self._replay_lightning_counts.get(provider, 0) + 1
        await self.player.start(score)
        return {
            "event_count": len(events),
            "cue_count": self.player.cue_count,
            "hours": hours,
            "performance_seconds": duration,
        }

    async def recent_events(self, hours=None, limit=500):
        """Return a filtered, newest-first snapshot of visible history."""
        return await self.history.recent_events(
            self.config.replay_hours if hours is None else hours, limit,
            tuple(self._emitted_cues), tuple(self._published_background_state.values()),
            self._instruments_for_kind,
        )

    async def status(self) -> dict:
        """Build the observable application status contract."""
        count, latest, retained_earthquake = await asyncio.gather(
            asyncio.to_thread(self.store.count, HIDDEN_HISTORY_KINDS),
            asyncio.to_thread(self.store.latest_timestamp, HIDDEN_HISTORY_KINDS),
            asyncio.to_thread(self.store.retained_status_event, "earthquake"),
        )
        emitted_earthquake = self._latest_emitted_event("event", kind="earthquake")
        retained_earthquake = (
            None if retained_earthquake is None else retained_earthquake.as_dict()
        )
        latest_earthquake = max(
            (event for event in (retained_earthquake, emitted_earthquake) if event),
            key=lambda event: event["timestamp"],
            default=None,
        )
        glm_status = self.glm.status() if hasattr(self.glm, "status") else {}
        mtg_li_status = (
            self.mtg_li.status() if hasattr(self.mtg_li, "status") else {}
        )
        source_health = {
            source: self._source_recovery_status(source)
            for source in SUPPORTED_SOURCES
        }
        return {
            "capture": {
                "polling": any(self.polling.running(source) for source in SUPPORTED_SOURCES if source != "noaa_glm"),
                "last_at": self.last_capture_at,
                "last_received": self.last_capture_count,
                "last_inserted": self.last_capture_inserted,
                "last_error": self.last_capture_error,
            },
            "history": {"event_count": count, "latest_timestamp": latest},
            "cues": {
                "latest_sequence": self._cue_sequence,
                "latest_location": self._latest_sound_location,
                "latest_background_location": self._latest_background_location,
                "latest_background_event": self._latest_emitted_event("background"),
                "latest_event": self._latest_emitted_event("event"),
                "latest_earthquake_event": latest_earthquake,
                "latest_event_sounds": self._latest_event_sounds(),
            },
            "performance": self.player.status(),
            "live": {
                "mode": self.config.live_mode,
                "running": self._continuous_task is not None and not self._continuous_task.done(),
                "played_count": self.continuous_played_count,
                "last_error": self.continuous_last_error,
                "interval_seconds": self.config.continuous_interval_seconds,
                "location_strategy": "background_rotation_with_due_events",
            },
            "osc": self.renderer.status(),
            "supercollider": detect_supercollider(),
            "sources": {
                "enabled": list(self.config.enabled_sources),
                "birdsong_enabled": self.config.birdsong_enabled,
                "frog_calls_enabled": self.config.frog_calls_enabled,
                "recordings": {kind: dict(value) for kind, value in self._recording_status.items()},
                **{f"{kind}_enabled": getattr(self.config, f"{kind}_enabled") for kind in MARINE_KINDS},
                "health": source_health,
                "recovery": self._overall_recovery_status(source_health),
            },
            "glm": {
                **glm_status,
                "enabled": "noaa_glm" in self.config.enabled_sources,
                "polling": self.polling.running("noaa_glm"),
                "interval_seconds": GLM_POLL_SECONDS,
                "last_at": self.last_glm_capture_at,
                "last_received": self.last_glm_received,
                "last_inserted": self.last_glm_inserted,
                "replaying_cached_field": self._glm_replaying_cached_field,
                "cached_flash_count": len(self._last_glm_sonification_events),
                "last_error": self.last_glm_error
                or str(glm_status.get("last_error", "")),
            },
            "mtg_li": {
                **mtg_li_status,
                "enabled": "eumetsat_mtg_li" in self.config.enabled_sources,
                "configured": bool(
                    self.config.eumetsat_consumer_key
                    and self.config.eumetsat_consumer_secret
                ),
                "interval_seconds": self.config.poll_seconds,
                "presentation_mode": "delayed_once",
                "presentation_delay_seconds": MTG_PRESENTATION_DELAY_SECONDS,
                "active_timeline_count": len(self._mtg_sonification_tasks),
                "last_scheduled_count": self.last_mtg_scheduled_count,
                "played_count": self.mtg_played_count,
                "skipped_late_count": self.mtg_skipped_late_count,
            },
        }

    def _latest_emitted_event(self, role: str, kind: str | None = None) -> dict | None:
        """Return the normalized event from the latest emitted cue for a role."""
        for cue in reversed(self._emitted_cues):
            if cue["role"] == role and (kind is None or cue["event"]["kind"] == kind):
                return cue["event"]
        return None

    def _latest_event_sounds(self) -> list[str]:
        """Return Event 1–3 voices emitted for the most recent source event."""
        latest_key = None
        instruments = []
        for cue in reversed(self._emitted_cues):
            if cue["role"] != "event":
                continue
            event = cue["event"]
            if event["kind"] in HIDDEN_HISTORY_KINDS:
                continue
            key = (event["provider"], event["event_id"])
            if latest_key is None:
                latest_key = key
            elif key != latest_key:
                break
            instruments.append(cue["instrument"])
        instruments.reverse()
        return instruments

    def apply_audio_settings(
        self, enabled_sources, event_instruments, units=None,
        instrument_volumes=None, lightning_sample_rate=None,
        eumetsat_consumer_key=None, eumetsat_consumer_secret=None,
    ) -> None:
        """Configure audio before polling starts; HTTP uses update_settings."""
        changes = {"enabled_sources": list(enabled_sources), "event_instruments": dict(event_instruments)}
        optional = {
            "units": units, "instrument_volumes": instrument_volumes,
            "lightning_sample_rate": lightning_sample_rate,
            "eumetsat_consumer_key": eumetsat_consumer_key,
            "eumetsat_consumer_secret": eumetsat_consumer_secret,
        }
        changes.update({key: value for key, value in optional.items() if value is not None})
        self._apply_config(settings_candidate(self.config, changes))

    def _apply_config(self, candidate):
        previous_sources = set(self.config.enabled_sources)
        changed_kinds = set()
        for kind in MARINE_KINDS:
            if getattr(candidate, f"{kind}_enabled") != getattr(self.config, f"{kind}_enabled"):
                changed_kinds.add(kind)
            if getattr(candidate, f"{kind}_regions") != getattr(self.config, f"{kind}_regions"):
                changed_kinds.add(kind)
                setattr(self, kind, SanctSoundClient(self.data_dir, kind, getattr(candidate, f"{kind}_regions")))
        if candidate.frog_calls_enabled != self.config.frog_calls_enabled:
            changed_kinds.add("frog_calls")
        if (candidate.xeno_canto_api_key, candidate.frog_calls_locations) != (
            self.config.xeno_canto_api_key, self.config.frog_calls_locations
        ):
            changed_kinds.add("frog_calls")
            self.frog_calls = XenoCantoClient(
                self.data_dir, candidate.xeno_canto_api_key,
                locations=candidate.frog_calls_locations, group="frogs",
            )
        if candidate.birdsong_enabled != self.config.birdsong_enabled:
            changed_kinds.add("birdsong")
        if (candidate.birdsong_provider, candidate.xeno_canto_api_key, candidate.birdsong_locations) != (
            self.config.birdsong_provider, self.config.xeno_canto_api_key, self.config.birdsong_locations
        ):
            changed_kinds.add("birdsong")
            self.birdsong = (
                XenoCantoClient(self.data_dir, candidate.xeno_canto_api_key, locations=candidate.birdsong_locations)
                if candidate.birdsong_provider == "xeno_canto"
                else CommonsBirdsongClient(self.data_dir)
            )
        for field_name, client_name, kind, prefix, client_type in (
            ("ocean_swell_locations", "marine", "ocean_swell", "swell", OpenMeteoMarineClient),
            ("storm_outlook_locations", "storm", "storm_potential", "storm", OpenMeteoStormClient),
        ):
            if getattr(self.config, field_name) != getattr(candidate, field_name):
                changed_kinds.add(kind)
                # Replace rather than mutate a client with an in-flight worker.
                if isinstance(getattr(self, client_name), client_type):
                    setattr(self, client_name, client_type(
                        locations=provider_locations(getattr(candidate, field_name), prefix)
                    ))
        credentials = (candidate.eumetsat_consumer_key, candidate.eumetsat_consumer_secret)
        if credentials != (self.config.eumetsat_consumer_key, self.config.eumetsat_consumer_secret):
            if isinstance(self.mtg_li, EumetsatLiClient):
                self.mtg_li = EumetsatLiClient(*credentials)
            elif hasattr(self.mtg_li, "set_credentials"):
                self.mtg_li.set_credentials(*credentials)
        for item in fields(AppConfig):
            setattr(self.config, item.name, getattr(candidate, item.name))
        # Reconnecting players must receive the saved gain for a held recording.
        for cue in self._emitted_cues:
            if cue["sequence"] in self._recording_sequences.values():
                cue["volume"] = self.config.instrument_volumes["background"]
        self.glm.sonification_sample_stride = self.config.lightning_sample_rate
        self.renderer.instrument_mappings = self.config.background_mappings()
        for source in set(self.config.enabled_sources) - previous_sources:
            self._source_recovery[source] = _SourceRecovery(
                last_data_at=self._source_recovery[source].last_data_at
            )
        if changed_kinds:
            self._emitted_cues = deque(
                (cue for cue in self._emitted_cues if cue["event"]["kind"] not in changed_kinds),
                maxlen=EMITTED_CUE_LIMIT,
            )
            for key in tuple(self._published_background_state):
                if key[1] in changed_kinds:
                    del self._published_background_state[key]
            self._latest_background_location = None
            self._latest_sound_location = None
            for kind in changed_kinds:
                self._recording_sequences.pop(kind, None)
                self._ambient_cursors[kind] = 0
                if kind in self._recording_status:
                    self._recording_status[kind] = {"state": "idle", "error": ""}
        return changed_kinds

    async def update_settings(self, changes: dict, path: Path) -> int:
        """Persist a candidate before applying coordinated runtime changes."""
        async with self._settings_lock:
            previous_volumes = dict(self.config.instrument_volumes)
            candidate = settings_candidate(self.config, changes)
            await persist_settings(candidate, path)
            pruned = 0
            try:
                changed_kinds = self._apply_config(candidate)
                if previous_volumes != self.config.instrument_volumes:
                    async with self._live_play_lock:
                        await asyncio.to_thread(
                            self.renderer.set_volumes, self.config.volume_slots()
                        )
                for kind, source, catalog, prefix in (
                    ("ocean_swell", "open_meteo_marine", self.config.ocean_swell_locations, "swell"),
                    ("storm_potential", "open_meteo_storm", self.config.storm_outlook_locations, "storm"),
                ):
                    if kind in changed_kinds:
                        pruned += await asyncio.to_thread(
                            self.store.prune_provider_locations, source, provider_locations(catalog, prefix)
                        )
                    if kind in changed_kinds or self.renderer.instrument_mappings[kind] != kind:
                        async with self._live_play_lock:
                            await asyncio.to_thread(self.renderer.stop_layer, kind)
                if "live_mode" in changes:
                    if self.config.live_mode == "continuous":
                        await self.player.stop()
                        await self.start_continuous()
                    else:
                        await self.stop_continuous()
            except Exception as exc:
                self.continuous_last_error = f"Settings saved, but runtime update failed: {exc}"
                raise RuntimeError(self.continuous_last_error) from exc
            return pruned

    async def preview_instrument(
        self, instrument: str, kind: str = "earthquake", volume: float = 1.0,
        output_channel: str = "preview",
    ) -> dict:
        """Play a representative cue through the selected host instrument."""
        if not isinstance(output_channel, str) or output_channel not in {
            "preview", "background", "event_1", "event_2", "event_3"
        }:
            raise ValueError("Unsupported audio output channel")
        instrument = str(instrument)
        kind = str(kind)
        if kind not in EVENT_INSTRUMENT_OPTIONS:
            raise ValueError(f"Unsupported event kind: {kind}")
        if instrument not in EVENT_INSTRUMENT_OPTIONS[kind]:
            raise ValueError(f"Unsupported SuperCollider instrument for {kind}: {instrument}")
        if kind in {"birdsong", "frog_calls", *MARINE_KINDS}:
            label = {"birdsong": "Birdsong", "frog_calls": "Frog Calls",
                     "whale_song": "Whale Song", "dolphin_calls": "Dolphin Calls"}[kind]
            if not getattr(self.config, f"{kind}_enabled"):
                raise ValueError(f"Enable {label} in Sound Sources before previewing")
            volume = _preview_volume(volume)
            recording_client = getattr(self, kind)
            event = await asyncio.to_thread(recording_client.event_at, 0)
            if getattr(self, kind) is not recording_client or not getattr(self.config, f"{kind}_enabled"):
                raise ValueError(f"{label} settings changed; preview again")
            cue = cue_with_gain(
                ScoreCue(0, event, pitch=60, velocity=116, duration=8.0, pan=0.0),
                volume,
            )
            self._record_emitted_cue(cue, instrument, volume=volume)
            return {"played": True, "instrument": instrument, "kind": kind}
        examples = {
            "earthquake": (18.0, -35.0, 0.875, 6.0, 12.0, "Earthquake preview"),
            "ocean_swell": (-17.86, -149.28, 0.7, 4.2, 14.0, "Ocean swell preview"),
            "tide_turn": (39.60, -9.09, 0.55, 0.9, 0.0, "High tide preview"),
            "lightning_flash": (-31.95, 115.86, 0.82, 5.4, 18.0, "Lightning R2D2 preview"),
            "storm_potential": (1.0, 35.0, 0.8, 2.4, 75.0, "Storm Outlook preview"),
        }
        latitude, longitude, strength, magnitude, depth, place = examples[kind]
        event = GaiaEvent(
            provider="preview",
            event_id=f"preview-{time.time_ns()}",
            kind=kind,
            timestamp=time.time(),
            latitude=latitude,
            longitude=longitude,
            strength=strength,
            traits={"magnitude": magnitude, "depth_km": depth, "place": place},
        )
        preview_pitch = 42 if kind == "lightning_flash" else 50
        preview_duration = event_duration(event) if instrument == "earthquake" else 2.4
        cue = ScoreCue(
            0, event, pitch=preview_pitch, velocity=116,
            duration=preview_duration, pan=0.0,
        )
        volume = _preview_volume(volume)
        cue = cue_with_gain(cue, volume, output_channel)
        rendered = await asyncio.to_thread(self.renderer.play, cue, instrument)
        if rendered is not False:
            if kind in {"earthquake", "tide_turn", "lightning_flash"}:
                await asyncio.to_thread(self.store.add_events, (event,))
            self._record_emitted_cue(cue, instrument, volume=volume)
        return {"played": rendered is not False, "instrument": instrument, "kind": kind}

    async def emitted_cues(self, after=None) -> dict:
        """Return cue events emitted after a browser.s sequence cursor."""
        if after is None:
            cues = tuple(cue for cue in self._emitted_cues
                         if cue["sequence"] in self._recording_sequences.values())
        else:
            cursor = max(0, int(after))
            while self._cue_sequence <= cursor:
                self._cue_event.clear()
                if self._cue_sequence > cursor:
                    break
                try:
                    await asyncio.wait_for(
                        self._cue_event.wait(), timeout=CUE_LONG_POLL_SECONDS
                    )
                except asyncio.TimeoutError:
                    break
            cues = tuple(cue for cue in self._emitted_cues if cue["sequence"] > cursor)
        return {"latest_sequence": self._cue_sequence, "cues": cues}

    def advance_recording(self, sequence: int) -> bool:
        """Release the current recording when its player reaches the transition."""
        if type(sequence) is not int or sequence < 1:
            raise ValueError("A positive recording cue sequence is required")
        for kind, current in tuple(self._recording_sequences.items()):
            if current == sequence and self.playback.enabled and self._instruments_for_kind(kind):
                del self._recording_sequences[kind]
                self._recording_advance.set()
                return True
        return False

    def _record_replay_cue(self, cue, instrument=None, volume=1.0) -> None:
        """Report a lightning replay group when its first cue is dispatched."""
        if cue.kind == "lightning_flash":
            count = self._replay_lightning_counts.pop(cue.event.provider, 0)
            if count:
                LOGGER.info(
                    "%s replay playback started: %d lightning flashes in score",
                    cue.event.provider, count,
                )
        self._record_emitted_cue(
            cue, instrument, volume, report_sonification=cue.kind != "lightning_flash",
        )

    def _record_emitted_cue(
        self,
        cue,
        instrument: str | None = None,
        volume: float = 1.0,
        publish_background: bool = False,
        report_sonification: bool = True,
    ) -> None:
        """Journal a cue only after it has been sent to SuperCollider."""
        instrument = instrument or next(iter(self._instruments_for_kind(cue.kind)), "none")
        if report_sonification and volume > 0:
            LOGGER.info(
                "%s sonification: %s, %s, instrument=%s, channel=%s, playback dispatched, "
                "volume=%.0f%%, duration=%.2fs, strength=%.3f, location=%.4f,%.4f",
                cue.event.provider, cue.kind,
                cue.event.traits.get("place") or cue.event.traits.get("title") or cue.event.event_id,
                instrument, cue.output_channel, volume * 100, cue.duration,
                cue.event.strength, cue.event.latitude, cue.event.longitude,
            )
        emitted_at = time.time()
        event = cue.event.as_dict()
        location = {
            "name": str(event["traits"].get("place", "")).strip(),
            "latitude": event["latitude"],
            "longitude": event["longitude"],
        }
        if cue.kind in BACKGROUND_HISTORY_KINDS:
            self._latest_background_location = location
            self._latest_sound_location = location
        elif self._latest_background_location is None:
            self._latest_sound_location = location
        history_updated = (
            cue.kind not in BACKGROUND_HISTORY_KINDS
            and cue.kind not in HIDDEN_HISTORY_KINDS
        )
        if publish_background and cue.kind in BACKGROUND_HISTORY_KINDS:
            state_key = _background_location_key(cue.event)
            signature = _background_forecast_signature(cue.event)
            previous = self._published_background_state.get(state_key)
            if previous is None or previous["signature"] != signature:
                self._published_background_state[state_key] = {
                    "signature": signature,
                    "event": event,
                    "instrument": instrument,
                    "published_at": emitted_at,
                }
                history_updated = True
        self._cue_sequence += 1
        payload = cue.as_dict()
        payload.update(
            sequence=self._cue_sequence,
            emitted_at=emitted_at,
            instrument=instrument,
            volume=max(0.0, min(1.0, float(volume))),
            history_updated=history_updated,
            role=(
                "background"
                if cue.kind in BACKGROUND_HISTORY_KINDS
                else "event"
            ),
            event=event,
        )
        self._emitted_cues.append(payload)
        if publish_background and cue.kind in self._recording_status:
            payload["recording_rotation"] = True
            self._recording_sequences[cue.kind] = self._cue_sequence
        self._cue_event.set()

    def _start_glm_sonification(self, events, report="NOAA GLM playback") -> None:
        """Replace an older flash field with the newest 20-second observation."""
        if (
            self._glm_sonification_task is not None
            and not self._glm_sonification_task.done()
        ):
            self._glm_sonification_task.cancel()
        self._glm_sonification_task = self.playback.schedule(
            self._run_glm_sonification(tuple(events), report=report),
            name="gaiascapes-glm-sonification",
        )

    def _replay_last_glm_sonification(self) -> bool:
        """Restart the latest flash field when NOAA has not published a newer one."""
        events = self._last_glm_sonification_events
        fresh = bool(events) and (
            time.time() - max(event.timestamp for event in events)
            <= GLM_FALLBACK_MAX_AGE_SECONDS
        )
        can_replay = (
            fresh
            and self.playback.enabled
            and self.config.live_mode == "continuous"
            and "noaa_glm" in self.config.enabled_sources
            and bool(self._instruments_for_kind("lightning_flash"))
        )
        self._glm_replaying_cached_field = can_replay
        if not can_replay:
            return False
        self._start_glm_sonification(
            events, report="NOAA GLM replaying previous field; waiting for new granules",
        )
        return True

    async def _run_glm_sonification(self, events, report="NOAA GLM playback") -> None:
        """Replay observed flash timing as a dense but bounded glass-note field."""
        if not events or not self._instruments_for_kind("lightning_flash"):
            return
        events = tuple(sorted(events, key=lambda event: (event.timestamp, event.event_id)))
        first_timestamp = events[0].timestamp
        loop = asyncio.get_running_loop()
        origin = loop.time()
        played = 0
        try:
            for event in events:
                if not self.playback.enabled or "noaa_glm" not in self.config.enabled_sources:
                    break
                observed_offset = max(0.0, event.timestamp - first_timestamp)
                target = origin + (observed_offset * GLM_SONIFICATION_TIME_SCALE)
                delay = target - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                if await self._play_live_event(event):
                    played += 1
        finally:
            if played:
                LOGGER.info("%s; %d sonified, playback dispatched", report, played)

    async def _restore_mtg_schedule(self) -> None:
        """Resume the still-future portion of the latest stored MTG timeline."""
        recent = await asyncio.to_thread(
            self.store.events_of_kinds_since,
            ("lightning_flash",),
            time.time() - MTG_PRESENTATION_DELAY_SECONDS,
            20000, provider="eumetsat_mtg_li", newest_first=True,
        )
        products = {}
        for event in recent:
            if event.provider != "eumetsat_mtg_li":
                continue
            product = str(event.traits.get("product", "")) or event.event_id
            products.setdefault(product, []).append(event)
        for events in products.values():
            self._start_mtg_sonification(events)

    def _start_mtg_sonification(self, events) -> bool:
        """Queue one MTG product once on its fixed delayed presentation timeline."""
        events = tuple(sorted(events, key=lambda event: (event.timestamp, event.event_id)))
        if not self.playback.enabled or not events or not self._instruments_for_kind("lightning_flash"):
            return False
        product = str(events[0].traits.get("product", "")) or (
            f"{events[0].timestamp:.3f}:{events[-1].timestamp:.3f}:{len(events)}"
        )
        if product in self._mtg_scheduled_products:
            return False
        self._mtg_scheduled_products.append(product)
        stride = max(1, int(self.config.lightning_sample_rate))
        scheduled_events = events[::stride]
        self.last_mtg_scheduled_count = len(scheduled_events)
        task = self.playback.schedule(
            self._run_mtg_sonification(scheduled_events),
            name="gaiascapes-mtg-li-sonification",
        )
        self._mtg_sonification_tasks.add(task)
        task.add_done_callback(self._finish_mtg_sonification)
        return True

    def _finish_mtg_sonification(self, task) -> None:
        """Retire a completed MTG timeline and report unexpected failures."""
        self._mtg_sonification_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            LOGGER.warning("EUMETSAT MTG LI presentation failed: %s", error)

    async def _cancel_mtg_sonification(self) -> None:
        """Cancel every active MTG product timeline during mode changes or shutdown."""
        tasks = tuple(self._mtg_sonification_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._mtg_sonification_tasks.clear()

    async def _run_mtg_sonification(self, events) -> None:
        """Present each MTG flash once at its observation time plus a fixed delay."""
        reported = False
        for event in events:
            if (
                not self.playback.enabled
                or self.config.live_mode != "continuous"
                or "eumetsat_mtg_li" not in self.config.enabled_sources
                or not self._instruments_for_kind("lightning_flash")
            ):
                break
            target = event.timestamp + MTG_PRESENTATION_DELAY_SECONDS
            remaining = target - time.time()
            if remaining < -MTG_LATE_EVENT_TOLERANCE_SECONDS:
                self.mtg_skipped_late_count += 1
                continue
            if remaining > 0:
                await asyncio.sleep(remaining)
            if (
                not self.playback.enabled
                or self.config.live_mode != "continuous"
                or "eumetsat_mtg_li" not in self.config.enabled_sources
            ):
                break
            played = await self._play_live_event(event)
            if played and not reported:
                LOGGER.info(
                    "EUMETSAT MTG LI playback started: %d sampled flashes in timeline, "
                    "%.1fs observed span, %.0f-minute presentation delay",
                    len(events), events[-1].timestamp - events[0].timestamp,
                    MTG_PRESENTATION_DELAY_SECONDS / 60.0,
                )
                reported = True
            self.mtg_played_count += 1

    async def _continuous_loop(self) -> None:
        while True:
            self._recording_advance.clear()
            try:
                await self.play_next_ambient_layers()
                self.continuous_last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.continuous_last_error = f"{type(exc).__name__}: {exc}"
            try:
                await asyncio.wait_for(self._recording_advance.wait(),
                                       timeout=self.config.continuous_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def play_next_ambient_layers(self) -> tuple[str, ...]:
        """Rotate the background and play Event 2 only when a tide turn is due."""
        cycle_at = time.time()
        background_events = await asyncio.to_thread(
            self.store.latest_events_by_kind_and_place,
            ("ocean_swell", "storm_potential"),
        )
        freshness_cutoff = time.time() - FORECAST_FALLBACK_MAX_AGE_SECONDS
        background_events = tuple(
            event for event in background_events if event.timestamp >= freshness_cutoff
        )
        groups = {kind: [] for kind in ("ocean_swell", "storm_potential")}
        for event in background_events:
            groups[event.kind].append(event)
        for events_for_kind in groups.values():
            events_for_kind.sort(key=lambda event: str(event.traits.get("place", "")))
        for kind in ("ocean_swell", "storm_potential"):
            if not groups[kind]:
                await asyncio.to_thread(self.renderer.stop_layer, kind)
        selected = []
        for kind in ("ocean_swell", "storm_potential"):
            choices = groups[kind]
            if not choices or not self._instruments_for_kind(kind):
                continue
            cursor = self._ambient_cursors[kind]
            selected.append(choices[cursor % len(choices)])
            self._ambient_cursors[kind] = cursor + 1
        for kind in ("birdsong", "frog_calls", *MARINE_KINDS):
            if not self._instruments_for_kind(kind) or kind in self._recording_sequences:
                continue
            cursor = self._ambient_cursors[kind]
            recording_client = getattr(self, kind)
            self._recording_status[kind] = {"state": "loading", "error": ""}
            try:
                recording_event = await asyncio.to_thread(recording_client.event_at, cursor)
            except Exception as exc:
                if getattr(self, kind) is recording_client and self._instruments_for_kind(kind):
                    self._recording_status[kind] = {
                        "state": "unavailable" if isinstance(exc, NoRecordingsError) else "error",
                        "error": str(exc),
                    }
                    if isinstance(exc, NoRecordingsError):
                        self._ambient_cursors[kind] = cursor + 1
                raise
            if getattr(self, kind) is recording_client and self._instruments_for_kind(kind):
                self._recording_status[kind] = {"state": "ready", "error": ""}
                selected.append(recording_event)
                self._ambient_cursors[kind] = cursor + 1
        tide_events = await asyncio.to_thread(
            self.store.events_of_kinds_since,
            ("tide_turn",),
            self._last_continuous_cycle_at,
            5000,
        )
        due_tides = [
            event
            for event in tide_events
            if self._last_continuous_cycle_at < event.timestamp <= cycle_at
            and self.config.instruments_for_event("tide_turn")
        ]
        if due_tides:
            selected.append(max(due_tides, key=lambda event: event.strength))
        if selected:
            await asyncio.gather(*(self._play_live_event(event) for event in selected))
        self._last_continuous_cycle_at = cycle_at
        return tuple(event.kind for event in selected)

    async def play_next_ambient_event(self) -> bool:
        """Compatibility wrapper for one cycle of the layered ambient scheduler."""
        return bool(await self.play_next_ambient_layers())

    async def _play_live_event(self, event: GaiaEvent) -> int:
        """Render one event now and journal it for synchronized visuals."""
        ambient_duration = self.config.continuous_interval_seconds + 1.5
        durations = {
            "lightning_flash": 0.45 + (event.strength * 0.75),
            "ocean_swell": ambient_duration,
            "tide_turn": ambient_duration,
            "storm_potential": ambient_duration,
            "birdsong": ambient_duration,
            "frog_calls": ambient_duration,
            **{kind: ambient_duration for kind in MARINE_KINDS},
        }
        source = build_score((event,), event.timestamp, 1.0, 1.0)[0]
        velocity = source.velocity
        if event.kind in {"ocean_swell", "tide_turn", "storm_potential", "birdsong", "frog_calls", *MARINE_KINDS}:
            # SuperCollider maps 20..127 to amplitude 0.08..0.58. Convert
            # through that mapping so 75% means amplitude, not MIDI velocity.
            current_amplitude = 0.08 + ((source.velocity - 20) / 107.0 * 0.5)
            reduced_amplitude = current_amplitude * 0.75
            velocity = round(20 + ((reduced_amplitude - 0.08) / 0.5 * 107.0))
        cue = ScoreCue(
            0, event, source.pitch, velocity,
            duration=durations.get(event.kind, source.duration), pan=source.pan,
        )
        played = 0
        async with self._live_play_lock:
            if not self.playback.enabled:
                return 0
            persistent_background = (
                event.kind in BACKGROUND_HISTORY_KINDS
                and self.config.background_mappings()[event.kind] == event.kind
            )
            render = (
                self.renderer.update_layer if persistent_background else self.renderer.play
            )
            for instrument, gain, channel in self._voices_with_channels(event.kind):
                rendered_cue = cue_with_gain(cue, gain, channel)
                rendered = (
                    True
                    if event.kind in {"birdsong", "frog_calls", *MARINE_KINDS}
                    else await render_call(render, rendered_cue, instrument)
                )
                if rendered is not False:
                    self._record_emitted_cue(
                        rendered_cue,
                        instrument,
                        volume=gain,
                        publish_background=persistent_background,
                        report_sonification=event.kind != "lightning_flash",
                    )
                    self.continuous_played_count += 1
                    played += 1
        return played

    def _instruments_for_kind(self, kind: str) -> tuple[str, ...]:
        """Resolve every configured slot that an environmental event triggers."""
        return tuple(instrument for instrument, _gain in self._voices_for_kind(kind))

    def _voices_with_channels(self, kind: str) -> tuple[tuple[str, float, str], ...]:
        """Keep each selected voice tied to its independent volume channel."""
        if kind in {"earthquake", "tide_turn", "lightning_flash"}:
            return tuple(
                (instrument, self.config.instrument_volumes[slot], slot)
                for slot in ("event_1", "event_2", "event_3")
                if (instrument := self.config.event_instruments[slot]) != "none"
                and EVENT_KIND_BY_VOICE[instrument] == kind
                and self.config.instrument_volumes[slot] > 0
            )
        return tuple((instrument, gain, "background")
                     for instrument, gain in self._voices_for_kind(kind))

    def _voices_for_kind(self, kind: str) -> tuple[tuple[str, float], ...]:
        """Resolve configured instruments and independent slot gains."""
        if kind in {"earthquake", "tide_turn", "lightning_flash"}:
            return self.config.voices_for_event(kind)
        instrument = self.config.background_mappings().get(kind, "none")
        gain = self.config.instrument_volumes["background"]
        # Muted recordings still need a player and completion acknowledgements
        # so their rotation can continue and later unmuting cannot strand it.
        recorded = kind in {"birdsong", "frog_calls", *MARINE_KINDS}
        return () if instrument == "none" or (gain <= 0 and not recorded) else ((instrument, gain),)


def _capture_error_message(source: str, error: Exception) -> str:
    message = str(error)
    if source.startswith("open_meteo") and message.startswith(
        "Open-Meteo is temporarily limiting requests"
    ):
        return message
    return f"{source}: {type(error).__name__}: {error}"


def _preview_volume(value) -> float:
    """Validate a preview gain shared by generated and recorded voices."""
    try:
        volume = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Preview volume must be 0..1") from exc
    if not 0.0 <= volume <= 1.0:
        raise ValueError("Preview volume must be 0..1")
    return volume


def _resolve_event_database(data_dir: Path) -> Path:
    """Move a database from an earlier project name without losing history."""
    current = data_dir / "gaia_scape.sqlite3"
    legacy_names = ("gaia_rhythms.sqlite3", "earth_rhythms.sqlite3")
    if not current.exists():
        for legacy_name in legacy_names:
            legacy = data_dir / legacy_name
            if legacy.exists():
                legacy.replace(current)
                break
    return current


def _background_location_key(event: GaiaEvent):
    place = str(event.traits.get("place", "")).strip().casefold()
    location = place or (round(event.latitude, 4), round(event.longitude, 4))
    return event.provider, event.kind, location


def _background_forecast_signature(event: GaiaEvent):
    """Return only forecast values whose change should update Event History."""
    trait_names = {
        "storm_potential": (
            "cape_jkg", "weather_code", "showers_mm", "wind_gust_kmh"
        ),
        "ocean_swell": (
            "wave_height_m", "swell_height_m", "swell_period_s",
            "swell_direction_deg",
        ),
        "birdsong": (
            "commons_page_id", "title", "creator", "license",
        ),
        "frog_calls": ("recording_id", "title", "creator", "license"),
        **{kind: ("recording_id", "title", "creator", "license") for kind in MARINE_KINDS},
    }[event.kind]
    return (
        round(event.strength, 6),
        *(event.traits.get(name) for name in trait_names),
    )


def detect_supercollider() -> dict:
    """Report command-line SuperCollider availability without requiring it."""
    sclang = _find_supercollider_executable("sclang")
    scsynth = _find_supercollider_executable("scsynth")
    return {
        "available": bool(sclang and scsynth),
        "sclang": sclang,
        "scsynth": scsynth,
    }


def _find_supercollider_executable(name: str):
    """Find PATH installs and the standard macOS application-bundle layout."""
    if executable := shutil.which(name):
        return executable
    for candidate in _bundle_candidates(name):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _bundle_candidates(name: str):
    relative = "MacOS/sclang" if name == "sclang" else "Resources/scsynth"
    bundle = Path("SuperCollider.app") / "Contents" / relative
    return (
        Path("/Applications") / bundle,
        Path.home() / "Applications" / bundle,
    )
