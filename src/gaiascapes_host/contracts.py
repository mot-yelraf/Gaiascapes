"""Structural interfaces for capture providers and audio renderers.

These small contracts describe normalized inputs and outputs without requiring
providers or renderers to inherit from framework-specific base classes.
"""

from typing import Protocol

from gaiascapes.events import GaiaEvent
from gaiascapes.score import ScoreCue


class EventProvider(Protocol):
    """Fetch one normalized batch; raise an exception on provider failure."""

    def fetch(self) -> tuple[GaiaEvent, ...]:
        """Return observations without owning persistence or playback."""
        ...


class Renderer(Protocol):
    """Consume neutral score cues and report transport status."""

    def play(self, cue: ScoreCue, instrument: str | None = None) -> bool | None:
        """Send a cue; False means suppressed, None permits visual-only use."""
        ...

    def update_layer(self, cue: ScoreCue, instrument: str | None = None) -> bool | None:
        """Update a persistent background layer."""
        ...

    def stop_layer(self, kind: str, release: float = 3.0) -> bool:
        """Release a persistent layer."""
        ...

    def set_volumes(self, volumes: dict[str, float]) -> None:
        """Apply saved volume controls to active output channels."""
        ...

    def status(self) -> dict:
        """Report transport state, without claiming audible delivery."""
        ...
