"""Independent provider polling and bounded synchronous fetch dispatch.

Each source owns its cadence and overlap protection. Cancellation of an async
wait never permits another fetch to overlap the still-running worker.
"""

import asyncio
import threading
import time

from .contracts import EventProvider


class PollingCoordinator:
    """Own independent polling tasks and per-provider fetch locks."""

    def __init__(self, sources):
        self.tasks = {}
        self._fetch_locks = {source: threading.Lock() for source in sources}
        self.capture_locks = {source: asyncio.Lock() for source in sources}

    async def fetch(self, source: str, client: EventProvider, timeout: float):
        """Bound the caller's wait while preserving worker overlap protection."""
        def fetch_sync():
            lock = self._fetch_locks[source]
            if not lock.acquire(blocking=False):
                raise RuntimeError("Previous provider fetch is still running.")
            try:
                return client.fetch()
            finally:
                lock.release()

        try:
            return await asyncio.wait_for(asyncio.to_thread(fetch_sync), timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Provider fetch exceeded {timeout:g} seconds.") from exc

    def start(self, source, capture, interval) -> None:
        """Start an idempotent loop using a dynamic interval in seconds."""
        if self.running(source):
            return

        async def poll():
            while True:
                started = time.monotonic()
                try:
                    await capture()
                except Exception:
                    # Capture records the source-specific error for status.
                    pass
                await asyncio.sleep(max(1.0, interval() - (time.monotonic() - started)))

        self.tasks[source] = asyncio.create_task(poll(), name=f"gaiascapes-poll-{source}")

    def running(self, source=None) -> bool:
        """Report whether one source, or any source, is polling."""
        tasks = self.tasks.values() if source is None else (self.tasks.get(source),)
        return any(task is not None and not task.done() for task in tasks)

    async def stop(self) -> None:
        """Cancel and await all owned polling tasks."""
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
