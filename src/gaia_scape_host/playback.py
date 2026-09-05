"""Continuous playback lifecycle independent of the selected UI mode.

An explicit enabled state gates new schedules after Stop. The controller owns
all continuous tasks so shutdown drains them before releasing audio layers.
"""

import asyncio


class PlaybackController:
    """Own continuous task cancellation and the playback-enabled state."""

    def __init__(self):
        self.enabled = False
        self.tasks = set()

    def start(self) -> None:
        """Permit new continuous schedules."""
        self.enabled = True

    def schedule(self, coroutine, name):
        """Own a continuous task, or close it when playback is paused."""
        if not self.enabled:
            coroutine.close()
            return None
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def stop(self) -> None:
        """Reject new schedules immediately and drain existing tasks."""
        self.enabled = False
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


async def render_call(function, *args):
    """Drain an in-flight transport call before acknowledging cancellation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
