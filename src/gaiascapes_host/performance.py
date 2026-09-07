"""Asynchronous score playback lifecycle.

Playback schedules renderer-neutral cues against a monotonic clock, supports
cancellation, and reports lightweight progress to the host service.
"""

from __future__ import annotations

import asyncio
import time

from gaiascapes.score import ScoreCue

from .contracts import Renderer
from .playback import render_call


def cue_with_gain(cue, gain: float):
    """Return a cue whose MIDI velocity produces the requested amplitude gain."""
    gain = max(0.0, min(1.0, float(gain)))
    source_amplitude = 0.08 + ((cue.velocity - 20) / 107.0 * 0.5)
    target_amplitude = source_amplitude * gain
    velocity = round(20 + ((target_amplitude - 0.08) / 0.5 * 107.0))
    return ScoreCue(
        cue.offset,
        cue.event,
        cue.pitch,
        max(0, min(127, velocity)),
        duration=cue.duration,
        pan=cue.pan,
    )


class PerformancePlayer:
    """Own at most one score playback task."""

    def __init__(self, renderer: Renderer, on_played=None, instruments_for_cue=None):
        self.renderer = renderer
        self.on_played = on_played
        self.instruments_for_cue = instruments_for_cue
        self._task = None
        self._lifecycle_lock = asyncio.Lock()
        self.started_at = None
        self.finished_at = None
        self.cue_count = 0
        self.played_count = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        """Report whether a score playback task is currently active."""
        return self._task is not None and not self._task.done()

    async def start(self, score) -> None:
        """Cancel an existing performance and begin the supplied score."""
        async with self._lifecycle_lock:
            await self._stop()
            score = tuple(score)
            self.started_at = time.time()
            self.finished_at = None
            self.cue_count = sum(len(self._voices(cue)) for cue in score)
            self.played_count = 0
            self.last_error = ""
            self._task = asyncio.create_task(self._run(score), name="gaiascapes-performance")

    async def stop(self) -> None:
        """Stop current playback promptly."""
        async with self._lifecycle_lock:
            await self._stop()

    async def _stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self, score) -> None:
        loop = asyncio.get_running_loop()
        origin = loop.time()
        try:
            for cue in score:
                delay = origin + cue.offset - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                for instrument, gain in self._voices(cue):
                    rendered_cue = cue_with_gain(cue, gain)
                    rendered = await render_call(
                        self.renderer.play, rendered_cue, instrument
                    )
                    if rendered is not False:
                        if self.on_played is not None:
                            self.on_played(rendered_cue, instrument, volume=gain)
                        self.played_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.finished_at = time.time()

    def _voices(self, cue) -> tuple[tuple[str | None, float], ...]:
        if self.instruments_for_cue is None:
            return ((None, 1.0),)
        voices = []
        for selection in self.instruments_for_cue(cue):
            if isinstance(selection, tuple):
                instrument, gain = selection
            else:
                instrument, gain = selection, 1.0
            if float(gain) > 0:
                voices.append((instrument, float(gain)))
        return tuple(voices)

    def status(self) -> dict:
        """Return playback lifecycle, cue counts, and the latest error."""
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cue_count": self.cue_count,
            "played_count": self.played_count,
            "last_error": self.last_error,
        }
