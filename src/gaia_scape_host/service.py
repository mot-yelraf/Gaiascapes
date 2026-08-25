"""Application orchestration for capture, history, and performance."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections import deque
from pathlib import Path

from gaia_scape.events import GaiaEvent
from gaia_scape.score import ScoreCue, build_score

from .capture import EventStore
from .config import AppConfig, EVENT_INSTRUMENT_OPTIONS
from .open_meteo import OpenMeteoMarineClient, OpenMeteoStormClient
from .noaa_glm import GLM_POLL_SECONDS, NoaaGlmClient
from .osc import OscRenderer
from .performance import PerformancePlayer, cue_with_gain
from .usgs import UsgsClient


CUE_LONG_POLL_SECONDS = 2.0
BACKGROUND_HISTORY_KINDS = frozenset({"ocean_swell", "storm_potential"})
HIDDEN_HISTORY_KINDS = frozenset({"lightning_flash"})
LOGGER = logging.getLogger("uvicorn.error")
GLM_SONIFICATION_TIME_SCALE = 1.0


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
        self.usgs = usgs_client or UsgsClient(config.usgs_url)
        self.marine = marine_client or OpenMeteoMarineClient()
        self.storm = storm_client or OpenMeteoStormClient()
        self.glm = glm_client or NoaaGlmClient()
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

    async def capture_once(self) -> dict:
        """Fetch, normalize, persist, and prune all enabled provider feeds."""
        async with self._capture_lock:
            self.last_capture_at = time.time()
            clients = (
                ("usgs", self.usgs),
                ("open_meteo_marine", self.marine),
                ("open_meteo_storm", self.storm),
            )
            enabled_clients = tuple(
                client for source, client in clients if source in self.config.enabled_sources
            )
            if not enabled_clients:
                self.last_capture_count = 0
                self.last_capture_inserted = 0
                self.last_capture_error = ""
                return {"received": 0, "inserted": 0, "pruned": 0, "disabled": True}
            try:
                events = []
                errors = []
                for client in enabled_clients:
                    try:
                        events.extend(await asyncio.to_thread(client.fetch))
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}")
                if errors and not events:
                    raise RuntimeError("; ".join(errors))
                inserted_events = await asyncio.to_thread(self.store.add_new_events, events)
                inserted = len(inserted_events)
                cutoff = time.time() - (self.config.retention_days * 86400)
                pruned = await asyncio.to_thread(self.store.prune_before, cutoff)
                self.last_capture_count = len(events)
                self.last_capture_inserted = inserted
                self.last_capture_error = "; ".join(errors)
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

    async def capture_glm_once(self) -> dict:
        """Retrieve, persist, and sound one independent NOAA GLM update."""
        async with self._glm_capture_lock:
            self.last_glm_capture_at = time.time()
            if "noaa_glm" not in self.config.enabled_sources:
                self.last_glm_received = 0
                self.last_glm_inserted = 0
                self.last_glm_error = ""
                return {"received": 0, "inserted": 0, "disabled": True}
            try:
                events = await asyncio.to_thread(self.glm.fetch)
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
                if self.config.live_mode == "continuous" and sonification_events:
                    self._start_glm_sonification(sonification_events)
                return {
                    "received": len(events),
                    "raw_flashes": raw_count,
                    "inserted": len(inserted_events),
                    "pruned": pruned,
                }
            except Exception as exc:
                self.last_glm_error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("NOAA GLM update failed: %s", self.last_glm_error)
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
            "sources": {"enabled": list(self.config.enabled_sources)},
            "glm": {
                **glm_status,
                "enabled": "noaa_glm" in self.config.enabled_sources,
                "polling": self._glm_poll_task is not None
                and not self._glm_poll_task.done(),
                "interval_seconds": GLM_POLL_SECONDS,
                "last_at": self.last_glm_capture_at,
                "last_received": self.last_glm_received,
                "last_inserted": self.last_glm_inserted,
                "last_error": self.last_glm_error
                or str(glm_status.get("last_error", "")),
            },
        }

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
    ) -> None:
        """Apply validated capture and instrument settings to live components."""
        previous_sources = self.config.enabled_sources
        previous_instruments = self.config.event_instruments
        previous_units = self.config.units
        previous_volumes = self.config.instrument_volumes
        try:
            self.config.enabled_sources = list(enabled_sources)
            self.config.event_instruments = dict(event_instruments)
            if units is not None:
                self.config.units = units
            if instrument_volumes is not None:
                self.config.instrument_volumes = dict(instrument_volumes)
            self.config.validate()
        except (TypeError, ValueError):
            self.config.enabled_sources = previous_sources
            self.config.event_instruments = previous_instruments
            self.config.units = previous_units
            self.config.instrument_volumes = previous_volumes
            raise
        self.renderer.instrument_mappings = self.config.background_mappings()
        for kind in ("ocean_swell", "storm_potential"):
            if self.renderer.instrument_mappings[kind] != kind:
                self.renderer.stop_layer(kind)

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
            "lightning_flash": (-31.95, 115.86, 0.82, 5.4, 18.0, "Lightning preview"),
            "storm_potential": (1.0, 35.0, 0.8, 2.4, 75.0, "Storm potential preview"),
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
        preview_pitch = 54 if kind == "lightning_flash" else 50
        cue = ScoreCue(
            0, event, pitch=preview_pitch, velocity=116, duration=2.4, pan=0.0
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
                await self.capture_once()
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
                    await self.capture_glm_once()
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
        events = await asyncio.to_thread(
            self.store.events_since, cycle_at - 86400.0, 5000
        )
        latest_by_location = {}
        for event in events:
            if event.kind not in {"ocean_swell", "storm_potential"}:
                continue
            place = str(event.traits.get("place", ""))
            latest_by_location[(event.kind, place)] = event
        groups = {kind: [] for kind in ("ocean_swell", "storm_potential")}
        for event in latest_by_location.values():
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
        due_tides = [
            event
            for event in events
            if event.kind == "tide_turn"
            and self._last_continuous_cycle_at < event.timestamp <= cycle_at
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
            "earthquake": 3.2,
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
