"""Validated configuration candidates and persistent settings commits.

Candidates preserve process-local environment overrides while allowing callers
to save successfully before changing any live component or retained history.
"""

import asyncio
from copy import deepcopy
from dataclasses import fields

from .config import AppConfig


def settings_candidate(config: AppConfig, changes: dict) -> AppConfig:
    """Build and validate an independent candidate without mutating runtime state."""
    candidate = deepcopy(config)
    names = {item.name for item in fields(AppConfig)}
    for key, value in changes.items():
        if key not in names:
            raise ValueError(f"Unknown setting: {key}")
        setattr(candidate, key, deepcopy(value))
    candidate.validate()
    return candidate


async def persist_settings(candidate: AppConfig, path) -> None:
    """Finish an atomic save even if the requesting client disconnects."""
    task = asyncio.create_task(asyncio.to_thread(candidate.save, path))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # The caller must finish applying a committed configuration.
        await task
