"""Asynchronous score playback lifecycle."""

from __future__ import annotations

import asyncio
import time


class PerformancePlayer:
    """Own at most one score playback task."""

    def __init__(self, renderer, on_played=None):
        self.renderer = renderer
        self.on_played = on_played
        self._task = None
        self.started_at = None
        self.finished_at = None
        self.cue_count = 0
        self.played_count = 0
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, score) -> None:
        """Cancel an existing performance and begin the supplied score."""
        await self.stop()
        self.started_at = time.time()
        self.finished_at = None
        self.cue_count = len(score)
        self.played_count = 0
        self.last_error = ""
        self._task = asyncio.create_task(self._run(score), name="gaia-rhythms-performance")

    async def stop(self) -> None:
        """Stop current playback promptly."""
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
                await asyncio.to_thread(self.renderer.play, cue)
                if self.on_played is not None:
                    self.on_played(cue)
                self.played_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.finished_at = time.time()

    def status(self) -> dict:
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cue_count": self.cue_count,
            "played_count": self.played_count,
            "last_error": self.last_error,
        }
