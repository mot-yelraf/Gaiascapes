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
from dataclasses import dataclass
from pathlib import Path

from gaia_scape.events import GaiaEvent
from gaia_scape.score import ScoreCue, build_score, event_duration

from .capture import EventStore
from .config import AppConfig, EVENT_INSTRUMENT_OPTIONS, SUPPORTED_SOURCES
from .open_meteo import (
    OpenMeteoMarineClient,
    OpenMeteoStormClient,
    provider_locations,
)
from .noaa_glm import GLM_POLL_SECONDS, NoaaGlmClient
from .osc import OscRenderer
from .performance import PerformancePlayer, cue_with_gain
from .usgs import UsgsClient


CUE_LONG_POLL_SECONDS = 2.0
BACKGROUND_HISTORY_KINDS = frozenset({"ocean_swell", "storm_potential"})
HIDDEN_HISTORY_KINDS = frozenset({"lightning_flash"})
LOGGER = logging.getLogger("uvicorn.error")
GLM_SONIFICATION_TIME_SCALE = 1.0
RECOVERY_MAX_RETRY_SECONDS = 15 * 60.0
GLM_FALLBACK_MAX_AGE_SECONDS = 5 * 60.0
FORECAST_FALLBACK_MAX_AGE_SECONDS = 3 * 60 * 60.0
SOURCE_LABELS = {
    "usgs": "USGS earthquakes",
    "open_meteo_marine": "Open-Meteo marine",
    "open_meteo_storm": "Open-Meteo storm outlook",
    "noaa_glm": "NOAA GLM lightning",
}
SOURCE_FALLBACK_MAX_AGE = {
    "open_meteo_marine": FORECAST_FALLBACK_MAX_AGE_SECONDS,
    "open_meteo_storm": FORECAST_FALLBACK_MAX_AGE_SECONDS,
    "noaa_glm": GLM_FALLBACK_MAX_AGE_SECONDS,
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


class GaiaScapeService:
    """Coordinate provider polling without coupling it to HTTP routes."""

    def __init__(
        self,
        config: AppConfig,
        data_dir: Path,
        usgs_client=None,
        marine_client=None,
        storm_client=None,
        glm_client=None,
    ):
        self.config = config
        self.data_dir = Path(data_dir)
        self.store = EventStore(_resolve_event_database(self.data_dir))
        self.store.initialize()
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
        self.renderer = OscRenderer(
            config.osc_host,
            config.osc_port,
            config.osc_enabled,
            config.background_mappings(),
        )
        self._cue_sequence = 0
        self._emitted_cues = deque(maxlen=1000)
        self._cue_event = asyncio.Event()
        self._latest_sound_location = None
        self._latest_background_location = None
        self._published_background_state = {}
        self.player = PerformancePlayer(
            self.renderer,
            self._record_emitted_cue,
            lambda cue: self._voices_for_kind(cue.kind),
        )
        self._capture_lock = asyncio.Lock()
        self._poll_task = None
        self._glm_poll_task = None
        self._glm_sonification_task = None
        self._last_glm_sonification_events = ()
        self._glm_replaying_cached_field = False
        self._continuous_task = None
        self._glm_capture_lock = asyncio.Lock()
        self._live_play_lock = asyncio.Lock()
        self._ambient_cursors = {
            kind: 0 for kind in ("ocean_swell", "storm_potential")
        }
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
            500,
        )
        if not recent:
            return
        newest = max(event.timestamp for event in recent)
        self._last_glm_sonification_events = tuple(
            event for event in recent if event.timestamp >= newest - GLM_POLL_SECONDS
        )[-120:]

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
            "degraded": "Gaia Scape is degraded. At least one enabled data source is using fallback data or recovering.",
            "offline": "All enabled environmental data sources are offline. Automatic recovery will continue.",
            "recovering": "Gaia Scape is attempting to recover its environmental data sources.",
            "waiting": "Gaia Scape is waiting for its first environmental data update.",
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
        """Start one idempotent background polling loop."""
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(
                self._poll_loop(), name="gaia-scape-capture"
            )
        if self._glm_poll_task is None or self._glm_poll_task.done():
            self._glm_poll_task = asyncio.create_task(
                self._glm_poll_loop(), name="gaia-scape-glm-capture"
            )

    async def start_continuous(self) -> None:
        """Start the ambient live-event stream without duplicating it."""
        if self._continuous_task is None or self._continuous_task.done():
            self._last_continuous_cycle_at = time.time()
            self._continuous_task = asyncio.create_task(
                self._continuous_loop(), name="gaia-scape-continuous"
            )

    async def stop_continuous(self) -> None:
        """Stop only the ambient live-event stream."""
        if self._continuous_task is not None and not self._continuous_task.done():
            self._continuous_task.cancel()
            try:
                await self._continuous_task
            except asyncio.CancelledError:
                pass
        self._continuous_task = None
        if (
            self._glm_sonification_task is not None
            and not self._glm_sonification_task.done()
        ):
            self._glm_sonification_task.cancel()
            try:
                await self._glm_sonification_task
            except asyncio.CancelledError:
                pass
        self._glm_sonification_task = None
        self._glm_replaying_cached_field = False
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
        """Stop capture and playback tasks."""
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        if self._glm_poll_task is not None and not self._glm_poll_task.done():
            self._glm_poll_task.cancel()
            try:
                await self._glm_poll_task
            except asyncio.CancelledError:
                pass
        self._glm_poll_task = None
        if (
            self._glm_sonification_task is not None
            and not self._glm_sonification_task.done()
        ):
            self._glm_sonification_task.cancel()
            try:
                await self._glm_sonification_task
            except asyncio.CancelledError:
                pass
        self._glm_sonification_task = None
        await self.stop_continuous()
        await self.player.stop()

    async def capture_once(self, respect_backoff: bool = False) -> dict:
        """Fetch, normalize, persist, and prune all enabled provider feeds."""
        async with self._capture_lock:
            self.last_capture_at = time.time()
            clients = (
                ("usgs", self.usgs),
                ("open_meteo_marine", self.marine),
                ("open_meteo_storm", self.storm),
            )
            enabled_clients = tuple(
                (source, client)
                for source, client in clients
                if source in self.config.enabled_sources
            )
            if not enabled_clients:
                self.last_capture_count = 0
                self.last_capture_inserted = 0
                self.last_capture_error = ""
                return {"received": 0, "inserted": 0, "pruned": 0, "disabled": True}
            try:
                events = []
                errors = []
                forecast_catalogs = []
                backing_off = []
                for source, client in enabled_clients:
                    if respect_backoff and not self._source_can_retry(source):
                        backing_off.append(source)
                        continue
                    self._mark_source_recovering(source)
                    try:
                        source_events = tuple(await asyncio.to_thread(client.fetch))
                        events.extend(source_events)
                        locations = getattr(client, "locations", ())
                        if source.startswith("open_meteo_") and locations:
                            forecast_catalogs.append((source, tuple(locations)))
                        self._mark_source_success(source, source_events, client)
                    except Exception as exc:
                        self._mark_source_failure(source, exc)
                        error = _capture_error_message(source, exc)
                        if error not in errors:
                            errors.append(error)
                if errors and not events and not backing_off:
                    raise RuntimeError("; ".join(errors))
                inserted_events = await asyncio.to_thread(self.store.add_new_events, events)
                inserted = len(inserted_events)
                cutoff = time.time() - (self.config.retention_days * 86400)
                pruned = await asyncio.to_thread(self.store.prune_before, cutoff)
                for provider, active_places in forecast_catalogs:
                    pruned += await asyncio.to_thread(
                        self.store.prune_provider_locations, provider, active_places
                    )
                self.last_capture_count = len(events)
                self.last_capture_inserted = inserted
                active_errors = list(errors)
                active_errors.extend(
                    self._source_recovery[source].last_error
                    for source in backing_off
                    if self._source_recovery[source].last_error
                )
                self.last_capture_error = "; ".join(dict.fromkeys(active_errors))
                if self.config.live_mode == "continuous":
                    for kind in ("earthquake", "lightning_flash"):
                        matching = [event for event in inserted_events if event.kind == kind]
                        if matching:
                            await self._play_live_event(
                                max(matching, key=lambda event: event.strength)
                            )
                return {
                    "received": len(events),
                    "inserted": inserted,
                    "pruned": pruned,
                }
            except Exception as exc:
                self.last_capture_error = f"{type(exc).__name__}: {exc}"
                raise

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
                events = tuple(await asyncio.to_thread(self.glm.fetch))
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
                LOGGER.info(
                    "NOAA GLM update: %d granules, %d raw flashes, "
                    "%d sampled, %d new, %d sonified",
                    granule_count,
                    raw_count,
                    len(events),
                    len(inserted_events),
                    len(sonification_events),
                )
                if sonification_events:
                    self._last_glm_sonification_events = sonification_events
                    self._glm_replaying_cached_field = False
                    if self.config.live_mode == "continuous":
                        self._start_glm_sonification(sonification_events)
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
        await self.player.start(score)
        return {
            "event_count": len(events),
            "cue_count": self.player.cue_count,
            "hours": hours,
            "performance_seconds": duration,
        }

    async def recent_events(self, hours=None, limit=500):
        """Return recently occurring or recently emitted stored events."""
        hours = self.config.replay_hours if hours is None else float(hours)
        hours = max(0.05, min(24.0, hours))
        cutoff = time.time() - (hours * 3600.0)
        events = await asyncio.to_thread(
            self.store.events_since, cutoff, 20000
        )
        events = tuple(
            event
            for event in events
            if event.kind not in BACKGROUND_HISTORY_KINDS
            and event.kind not in HIDDEN_HISTORY_KINDS
        )
        recent_cues = tuple(
            cue
            for cue in self._emitted_cues
            if cue["emitted_at"] >= cutoff
            and cue["event"]["kind"] not in BACKGROUND_HISTORY_KINDS
            and cue["event"]["kind"] not in HIDDEN_HISTORY_KINDS
        )
        event_keys = {(event.provider, event.event_id) for event in events}
        emitted_keys = {
            (cue["event"]["provider"], cue["event"]["event_id"])
            for cue in recent_cues
        }
        missing_events = await asyncio.to_thread(
            self.store.events_by_keys, emitted_keys - event_keys
        )
        events = (*events, *missing_events)
        emitted_instruments = {}
        for cue in recent_cues:
            key = (cue["event"]["provider"], cue["event"]["event_id"])
            instruments = emitted_instruments.setdefault(key, [])
            if cue["instrument"] not in instruments:
                instruments.append(cue["instrument"])
        emitted_times = {
            (cue["event"]["provider"], cue["event"]["event_id"]): cue["emitted_at"]
            for cue in recent_cues
        }
        history = []
        for event in events:
            item = event.as_dict()
            key = (event.provider, event.event_id)
            instruments = emitted_instruments.get(key)
            if instruments is None:
                instruments = list(dict.fromkeys(self._instruments_for_kind(event.kind)))
            item["instruments"] = instruments
            item["instrument"] = instruments[0] if instruments else "none"
            item["emitted_at"] = emitted_times.get(key)
            history.append(item)
        for state in self._published_background_state.values():
            event = state["event"]
            if event["timestamp"] < cutoff:
                continue
            item = dict(event)
            item["instruments"] = [state["instrument"]]
            item["instrument"] = state["instrument"]
            item["emitted_at"] = state["published_at"]
            history.append(item)
        history.sort(
            key=lambda item: (
                item["emitted_at"] is not None,
                item["emitted_at"] or item["timestamp"],
            ),
            reverse=True,
        )
        return tuple(history[:max(1, min(20000, int(limit)))])

    async def status(self) -> dict:
        """Build the observable application status contract."""
        count, latest = await asyncio.gather(
            asyncio.to_thread(self.store.count, HIDDEN_HISTORY_KINDS),
            asyncio.to_thread(self.store.latest_timestamp, HIDDEN_HISTORY_KINDS),
        )
        glm_status = self.glm.status() if hasattr(self.glm, "status") else {}
        source_health = {
            source: self._source_recovery_status(source)
            for source in SUPPORTED_SOURCES
        }
        return {
            "capture": {
                "polling": self._poll_task is not None and not self._poll_task.done(),
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
                "latest_earthquake_event": self._latest_emitted_event(
                    "event", kind="earthquake"
                ),
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
                "health": source_health,
                "recovery": self._overall_recovery_status(source_health),
            },
            "glm": {
                **glm_status,
                "enabled": "noaa_glm" in self.config.enabled_sources,
                "polling": self._glm_poll_task is not None
                and not self._glm_poll_task.done(),
                "interval_seconds": GLM_POLL_SECONDS,
                "last_at": self.last_glm_capture_at,
                "last_received": self.last_glm_received,
                "last_inserted": self.last_glm_inserted,
                "replaying_cached_field": self._glm_replaying_cached_field,
                "cached_flash_count": len(self._last_glm_sonification_events),
                "last_error": self.last_glm_error
                or str(glm_status.get("last_error", "")),
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
        self,
        enabled_sources,
        event_instruments,
        units: str | None = None,
        instrument_volumes=None,
        lightning_sample_rate=None,
    ) -> None:
        """Apply validated capture and instrument settings to live components."""
        previous_sources = self.config.enabled_sources
        previous_instruments = self.config.event_instruments
        previous_units = self.config.units
        previous_volumes = self.config.instrument_volumes
        previous_lightning_sample_rate = self.config.lightning_sample_rate
        try:
            self.config.enabled_sources = list(enabled_sources)
            self.config.event_instruments = dict(event_instruments)
            if units is not None:
                self.config.units = units
            if instrument_volumes is not None:
                self.config.instrument_volumes = dict(instrument_volumes)
            if lightning_sample_rate is not None:
                self.config.lightning_sample_rate = lightning_sample_rate
            self.config.validate()
        except (TypeError, ValueError):
            self.config.enabled_sources = previous_sources
            self.config.event_instruments = previous_instruments
            self.config.units = previous_units
            self.config.instrument_volumes = previous_volumes
            self.config.lightning_sample_rate = previous_lightning_sample_rate
            raise
        self.glm.sonification_sample_stride = self.config.lightning_sample_rate
        for source in set(self.config.enabled_sources) - set(previous_sources):
            self._source_recovery[source] = _SourceRecovery(
                last_data_at=self.store.latest_ingested_at_for_provider(source)
            )
        self.renderer.instrument_mappings = self.config.background_mappings()
        for kind in ("ocean_swell", "storm_potential"):
            if self.renderer.instrument_mappings[kind] != kind:
                self.renderer.stop_layer(kind)

    def apply_forecast_locations(self, ocean_swell_locations, storm_outlook_locations) -> int:
        """Validate and apply editable Open-Meteo sampling catalogs."""
        previous_ocean = self.config.ocean_swell_locations
        previous_storm = self.config.storm_outlook_locations
        try:
            self.config.ocean_swell_locations = ocean_swell_locations
            self.config.storm_outlook_locations = storm_outlook_locations
            self.config.validate()
        except (TypeError, ValueError):
            self.config.ocean_swell_locations = previous_ocean
            self.config.storm_outlook_locations = previous_storm
            raise
        ocean_changed = previous_ocean != self.config.ocean_swell_locations
        storm_changed = previous_storm != self.config.storm_outlook_locations
        marine_locations = provider_locations(
            self.config.ocean_swell_locations, "swell"
        )
        storm_locations = provider_locations(
            self.config.storm_outlook_locations, "storm"
        )
        if isinstance(self.marine, OpenMeteoMarineClient):
            self.marine.locations = marine_locations
            self.marine._has_cache = False
        if isinstance(self.storm, OpenMeteoStormClient):
            self.storm.locations = storm_locations
            self.storm._has_cache = False
        pruned = self.store.prune_provider_locations(
            "open_meteo_marine", marine_locations
        )
        pruned += self.store.prune_provider_locations(
            "open_meteo_storm", storm_locations
        )
        if ocean_changed or storm_changed:
            changed_kinds = {
                kind
                for kind, changed in (
                    ("ocean_swell", ocean_changed),
                    ("storm_potential", storm_changed),
                )
                if changed
            }
            self._emitted_cues = deque(
                (
                    cue for cue in self._emitted_cues
                    if cue["event"]["kind"] not in changed_kinds
                ),
                maxlen=1000,
            )
            for key in tuple(self._published_background_state):
                if key[1] in changed_kinds:
                    del self._published_background_state[key]
            self._latest_background_location = None
            self._latest_sound_location = None
            for kind in changed_kinds:
                self._ambient_cursors[kind] = 0
                self.renderer.stop_layer(kind)
        return pruned

    async def preview_instrument(
        self, instrument: str, kind: str = "earthquake", volume: float = 1.0
    ) -> dict:
        """Play a representative cue through the selected host instrument."""
        instrument = str(instrument)
        kind = str(kind)
        if kind not in EVENT_INSTRUMENT_OPTIONS:
            raise ValueError(f"Unsupported event kind: {kind}")
        if instrument not in EVENT_INSTRUMENT_OPTIONS[kind]:
            raise ValueError(f"Unsupported SuperCollider instrument for {kind}: {instrument}")
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
        try:
            volume = float(volume)
        except (TypeError, ValueError) as exc:
            raise ValueError("Preview volume must be 0..1") from exc
        if not 0.0 <= volume <= 1.0:
            raise ValueError("Preview volume must be 0..1")
        cue = cue_with_gain(cue, volume)
        rendered = await asyncio.to_thread(self.renderer.play, cue, instrument)
        if rendered is not False:
            if kind in {"earthquake", "tide_turn", "lightning_flash"}:
                await asyncio.to_thread(self.store.add_events, (event,))
            self._record_emitted_cue(cue, instrument, volume=volume)
        return {"played": rendered is not False, "instrument": instrument, "kind": kind}

    async def emitted_cues(self, after=None) -> dict:
        """Return cue events emitted after a browser.s sequence cursor."""
        if after is None:
            cues = ()
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

    def _record_emitted_cue(
        self,
        cue,
        instrument: str | None = None,
        volume: float = 1.0,
        publish_background: bool = False,
    ) -> None:
        """Journal a cue only after it has been sent to SuperCollider."""
        instrument = instrument or next(iter(self._instruments_for_kind(cue.kind)), "none")
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
                if cue.kind in {"ocean_swell", "storm_potential"}
                else "event"
            ),
            event=event,
        )
        self._emitted_cues.append(payload)
        self._cue_event.set()

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.capture_once(respect_backoff=True)
            except Exception:
                # The error is retained in status; the next interval retries.
                pass
            await asyncio.sleep(self.config.poll_seconds)

    async def _glm_poll_loop(self) -> None:
        """Poll GLM on its native cadence, independently of hourly forecasts."""
        while True:
            cycle_started = time.monotonic()
            if "noaa_glm" in self.config.enabled_sources:
                try:
                    await self.capture_glm_once(respect_backoff=True)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # The provider-specific error remains visible in status and logs.
                    pass
            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(1.0, GLM_POLL_SECONDS - elapsed))

    def _start_glm_sonification(self, events) -> None:
        """Replace an older flash field with the newest 20-second observation."""
        if (
            self._glm_sonification_task is not None
            and not self._glm_sonification_task.done()
        ):
            self._glm_sonification_task.cancel()
        self._glm_sonification_task = asyncio.create_task(
            self._run_glm_sonification(tuple(events)),
            name="gaia-scape-glm-sonification",
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
            and self.config.live_mode == "continuous"
            and "noaa_glm" in self.config.enabled_sources
            and bool(self._instruments_for_kind("lightning_flash"))
        )
        self._glm_replaying_cached_field = can_replay
        if not can_replay:
            return False
        LOGGER.info(
            "NOAA GLM unchanged: replaying previous field with %d sonified flashes",
            len(events),
        )
        self._start_glm_sonification(events)
        return True

    async def _run_glm_sonification(self, events) -> None:
        """Replay observed flash timing as a dense but bounded glass-note field."""
        if not events or not self._instruments_for_kind("lightning_flash"):
            return
        events = tuple(sorted(events, key=lambda event: (event.timestamp, event.event_id)))
        first_timestamp = events[0].timestamp
        loop = asyncio.get_running_loop()
        origin = loop.time()
        for event in events:
            if "noaa_glm" not in self.config.enabled_sources:
                break
            observed_offset = max(0.0, event.timestamp - first_timestamp)
            target = origin + (observed_offset * GLM_SONIFICATION_TIME_SCALE)
            delay = target - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            await self._play_live_event(event)

    async def _continuous_loop(self) -> None:
        while True:
            try:
                await self.play_next_ambient_layers()
                self.continuous_last_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.continuous_last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(self.config.continuous_interval_seconds)

    async def play_next_ambient_layers(self) -> tuple[str, ...]:
        """Rotate the background and play Event 2 only when a tide turn is due."""
        cycle_at = time.time()
        background_events = await asyncio.to_thread(
            self.store.latest_events_by_kind_and_place,
            BACKGROUND_HISTORY_KINDS,
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

    async def _play_live_event(self, event: GaiaEvent) -> None:
        """Render one event now and journal it for synchronized visuals."""
        ambient_duration = self.config.continuous_interval_seconds + 1.5
        durations = {
            "lightning_flash": 0.45 + (event.strength * 0.75),
            "ocean_swell": ambient_duration,
            "tide_turn": ambient_duration,
            "storm_potential": ambient_duration,
        }
        source = build_score((event,), event.timestamp, 1.0, 1.0)[0]
        velocity = source.velocity
        if event.kind in {"ocean_swell", "tide_turn", "storm_potential"}:
            # SuperCollider maps 20..127 to amplitude 0.08..0.58. Convert
            # through that mapping so 75% means amplitude, not MIDI velocity.
            current_amplitude = 0.08 + ((source.velocity - 20) / 107.0 * 0.5)
            reduced_amplitude = current_amplitude * 0.75
            velocity = round(20 + ((reduced_amplitude - 0.08) / 0.5 * 107.0))
        cue = ScoreCue(
            0, event, source.pitch, velocity,
            duration=durations.get(event.kind, source.duration), pan=source.pan,
        )
        async with self._live_play_lock:
            persistent_background = (
                event.kind in {"ocean_swell", "storm_potential"}
                and self.config.background_mappings()[event.kind] == event.kind
            )
            render = (
                self.renderer.update_layer if persistent_background else self.renderer.play
            )
            for instrument, gain in self._voices_for_kind(event.kind):
                rendered_cue = cue_with_gain(cue, gain)
                rendered = await asyncio.to_thread(render, rendered_cue, instrument)
                if rendered is not False:
                    self._record_emitted_cue(
                        rendered_cue,
                        instrument,
                        volume=gain,
                        publish_background=persistent_background,
                    )
                    self.continuous_played_count += 1

    def _instruments_for_kind(self, kind: str) -> tuple[str, ...]:
        """Resolve every configured slot that an environmental event triggers."""
        return tuple(instrument for instrument, _gain in self._voices_for_kind(kind))

    def _voices_for_kind(self, kind: str) -> tuple[tuple[str, float], ...]:
        """Resolve configured instruments and independent slot gains."""
        if kind in {"earthquake", "tide_turn", "lightning_flash"}:
            return self.config.voices_for_event(kind)
        instrument = self.config.background_mappings().get(kind, "none")
        gain = self.config.instrument_volumes["background"]
        return () if instrument == "none" or gain <= 0 else ((instrument, gain),)


def _capture_error_message(source: str, error: Exception) -> str:
    message = str(error)
    if source.startswith("open_meteo") and message.startswith(
        "Open-Meteo is temporarily limiting requests"
    ):
        return message
    return f"{source}: {type(error).__name__}: {error}"


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
