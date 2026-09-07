"""Provider- and renderer-independent Gaiascapes domain logic.

The package exports normalized events and score-building primitives that can
be reused without the host service, capture providers, or audio renderer.
"""

__version__ = "v0.26.250.13"

from .events import GaiaEvent
from .score import ScoreCue, build_score

__all__ = ["GaiaEvent", "ScoreCue", "build_score"]
