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


def cue_with_gain(cue, gain: float, output_channel: str = "preview"):
    """Apply the squared slider curve independently of musical velocity."""
    gain = max(0.0, min(1.0, float(gain)))
    return ScoreCue(
        cue.offset, cue.event, cue.pitch, cue.velocity,
        duration=cue.duration, pan=cue.pan,
        gain=gain ** 2, output_channel=output_channel,
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
                for instrument, gain, channel in self._voices(cue):
                    rendered_cue = cue_with_gain(cue, gain, channel)
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

    def _voices(self, cue) -> tuple[tuple[str | None, float, str], ...]:
        if self.instruments_for_cue is None:
            return ((None, 1.0, "preview"),)
        voices = []
        for selection in self.instruments_for_cue(cue):
            channel = "preview"
            if isinstance(selection, tuple):
                instrument, gain = selection[:2]
                if len(selection) == 3:
                    channel = selection[2]
            else:
                instrument, gain = selection, 1.0
            if float(gain) > 0:
                voices.append((instrument, float(gain), channel))
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
