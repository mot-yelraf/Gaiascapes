"""Provider-independent terrestrial event representation.

Normalized events provide the stable boundary between external Earth-data
providers, local persistence, score construction, and visual presentation.
"""


class GaiaEvent:
    """A compact normalized event suitable for storage and score building."""

    __slots__ = (
        "provider",
        "event_id",
        "kind",
        "timestamp",
        "latitude",
        "longitude",
        "strength",
        "traits",
    )

    def __init__(
        self,
        provider,
        event_id,
        kind,
        timestamp,
        latitude=0.0,
        longitude=0.0,
        strength=0.0,
        traits=None,
    ):
        self.provider = str(provider)
        self.event_id = str(event_id)
        self.kind = str(kind)
        self.timestamp = float(timestamp)
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.strength = max(0.0, min(1.0, float(strength)))
        self.traits = dict(traits or {})

    def as_dict(self):
        """Return a JSON-serializable representation."""
        return {
            "provider": self.provider,
            "event_id": self.event_id,
            "kind": self.kind,
            "timestamp": self.timestamp,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "strength": self.strength,
            "traits": dict(self.traits),
        }
