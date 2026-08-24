"""Application orchestration for capture, history, and performance."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from collections import deque
from pathlib import Path

from gaia_rhythms.events import GaiaEvent
from gaia_rhythms.score import ScoreCue, build_score

from .capture import EventStore
from .config import AppConfig, EVENT_INSTRUMENT_OPTIONS
from .open_meteo import OpenMeteoMarineClient, OpenMeteoStormClient
from .osc import OscRenderer
from .performance import PerformancePlayer
from .usgs import UsgsClient


CUE_LONG_POLL_SECONDS = 2.0


class GaiaRhythmsService:
    """Coordinate provider polling without coupling it to HTTP routes."""

    def __init__(
        self,
        config: AppConfig,
        data_dir: Path,
        usgs_client=None,
        marine_client=None,
        storm_client=None,
    ):
        self.config = config
        self.data_dir = Path(data_dir)
        self.store = EventStore(_resolve_event_database(self.data_dir))
        self.store.initialize()
        self.usgs = usgs_client or UsgsClient(config.usgs_url)
        self.marine = marine_client or OpenMeteoMarineClient()
        self.storm = storm_client or OpenMeteoStormClient()
        self.renderer = OscRenderer(
            config.osc_host,
            config.osc_port,
            config.osc_enabled,
            config.event_instruments,
        )
        self._cue_sequence = 0
        self._emitted_cues = deque(maxlen=1000)
        self._cue_event = asyncio.Event()
        self.player = PerformancePlayer(self.renderer, self._record_emitted_cue)
        self._capture_lock = asyncio.Lock()
        self._poll_task = None
        self._continuous_task = None
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

    async def start_polling(self) -> None:
        """Start one idempotent background polling loop."""
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(
                self._poll_loop(), name="gaia-rhythms-capture"
            )

    async def start_continuous(self) -> None:
        """Start the ambient live-event stream without duplicating it."""
        if self._continuous_task is None or self._continuous_task.done():
            self._last_continuous_cycle_at = time.time()
            self._continuous_task = asyncio.create_task(
                self._continuous_loop(), name="gaia-rhythms-continuous"
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
                    earthquakes = [event for event in inserted_events if event.kind == "earthquake"]
                    if earthquakes:
                        await self._play_live_event(max(earthquakes, key=lambda event: event.strength))
                return {
                    "received": len(events),
                    "inserted": inserted,
                    "pruned": pruned,
                }
            except Exception as exc:
                self.last_capture_error = f"{type(exc).__name__}: {exc}"
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
            "cue_count": len(score),
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
        recent_cues = tuple(
            cue for cue in self._emitted_cues if cue["emitted_at"] >= cutoff
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
        emitted_instruments = {
            (cue["event"]["provider"], cue["event"]["event_id"]): cue["instrument"]
            for cue in recent_cues
        }
        emitted_times = {
            (cue["event"]["provider"], cue["event"]["event_id"]): cue["emitted_at"]
            for cue in recent_cues
        }
        history = []
        for event in events:
            item = event.as_dict()
            key = (event.provider, event.event_id)
            item["instrument"] = emitted_instruments.get(
                key,
                self.config.event_instruments.get(event.kind, event.kind),
            )
            item["emitted_at"] = emitted_times.get(key)
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
            asyncio.to_thread(self.store.count),
            asyncio.to_thread(self.store.latest_timestamp),
        )
        latest_cue = self._emitted_cues[-1] if self._emitted_cues else None
        latest_location = (
            {
                "name": str(latest_cue["event"]["traits"].get("place", "")).strip(),
                "latitude": latest_cue["event"]["latitude"],
                "longitude": latest_cue["event"]["longitude"],
            }
            if latest_cue is not None
            else None
        )
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
                "latest_location": latest_location,
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
        }

    def apply_audio_settings(self, enabled_sources, event_instruments) -> None:
        """Apply validated capture and instrument settings to live components."""
        previous_sources = self.config.enabled_sources
        previous_instruments = self.config.event_instruments
        try:
            self.config.enabled_sources = list(enabled_sources)
            self.config.event_instruments = dict(event_instruments)
            self.config.validate()
        except (TypeError, ValueError):
            self.config.enabled_sources = previous_sources
            self.config.event_instruments = previous_instruments
            raise
        self.renderer.instrument_mappings = dict(self.config.event_instruments)
        for kind in ("ocean_swell", "storm_potential"):
            if self.config.event_instruments[kind] != kind:
                self.renderer.stop_layer(kind)

    async def preview_instrument(self, instrument: str, kind: str = "earthquake") -> dict:
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
        cue = ScoreCue(0, event, pitch=50, velocity=116, duration=2.4, pan=0.0)
        rendered = await asyncio.to_thread(self.renderer.play, cue, instrument)
        if rendered is not False:
            if kind in {"earthquake", "tide_turn"}:
                await asyncio.to_thread(self.store.add_events, (event,))
            self._record_emitted_cue(cue, instrument)
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

    def _record_emitted_cue(self, cue, instrument: str | None = None) -> None:
        """Journal a cue only after it has been sent to SuperCollider."""
        instrument = instrument or self.config.event_instruments.get(cue.kind, cue.kind)
        self._cue_sequence += 1
        payload = cue.as_dict()
        payload.update(
            sequence=self._cue_sequence,
            emitted_at=time.time(),
            instrument=instrument,
            role=(
                "background"
                if cue.kind in {"ocean_swell", "storm_potential"}
                else "event"
            ),
            event=cue.event.as_dict(),
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
            if not choices or self.config.event_instruments[kind] == "none":
                continue
            cursor = self._ambient_cursors[kind]
            selected.append(choices[cursor % len(choices)])
            self._ambient_cursors[kind] = cursor + 1
        due_tides = [
            event
            for event in events
            if event.kind == "tide_turn"
            and self._last_continuous_cycle_at < event.timestamp <= cycle_at
            and self.config.event_instruments["tide_turn"] != "none"
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
                and self.config.event_instruments[event.kind] == event.kind
            )
            render = (
                self.renderer.update_layer if persistent_background else self.renderer.play
            )
            rendered = await asyncio.to_thread(render, cue)
            if rendered is not False:
                self._record_emitted_cue(
                    cue, self.config.event_instruments[event.kind]
                )
                self.continuous_played_count += 1


def _resolve_event_database(data_dir: Path) -> Path:
    """Move the pre-Gaia database name in place without losing captured history."""
    current = data_dir / "gaia_rhythms.sqlite3"
    legacy = data_dir / "earth_rhythms.sqlite3"
    if not current.exists() and legacy.exists():
        legacy.replace(current)
    return current


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
