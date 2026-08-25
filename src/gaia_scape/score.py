"""Convert normalized Earth events into time-scaled musical cues."""


class ScoreCue:
    """A scheduled renderer-neutral musical cue."""

    __slots__ = (
        "offset",
        "provider",
        "event_id",
        "kind",
        "pitch",
        "velocity",
        "duration",
        "pan",
        "event",
    )

    def __init__(self, offset, event, pitch, velocity, duration=0.35, pan=0.0):
        self.offset = float(offset)
        self.provider = event.provider
        self.event_id = event.event_id
        self.kind = event.kind
        self.pitch = int(pitch)
        self.velocity = int(velocity)
        self.duration = float(duration)
        self.pan = max(-1.0, min(1.0, float(pan)))
        self.event = event

    def as_dict(self):
        """Return a JSON-serializable cue summary."""
        return {
            "offset": self.offset,
            "provider": self.provider,
            "event_id": self.event_id,
            "kind": self.kind,
            "pitch": self.pitch,
            "velocity": self.velocity,
            "duration": self.duration,
            "pan": self.pan,
        }


def longitude_to_pan(longitude):
    """Map longitude from -180..180 degrees to stereo pan -1..1."""
    longitude = max(-180.0, min(180.0, float(longitude)))
    return longitude / 180.0


def _lightning_pitch(event, geographic_pitch, note_max):
    """Give individual flashes a higher, deterministic pentatonic contour."""
    scale = (0, 2, 4, 7, 9)
    try:
        identity = int(event.traits.get("flash_id"))
    except (TypeError, ValueError):
        identity = sum(ord(character) for character in event.event_id)
    energy_step = int(round(event.strength * 8.0))
    longitude_step = int((max(-180.0, min(180.0, event.longitude)) + 180.0) / 30.0)
    satellite_step = sum(
        ord(character) for character in str(event.traits.get("satellite", ""))
    )
    interval = 4 + scale[
        (identity + energy_step + longitude_step + satellite_step) % len(scale)
    ]
    return min(int(note_max) + 8, geographic_pitch + interval)


def build_score(
    events,
    window_start,
    window_seconds,
    performance_seconds,
    note_min=36,
    note_max=84,
):
    """Build a sorted score while preserving relative event time."""
    scale = float(performance_seconds) / max(1.0, float(window_seconds))
    width = max(0, int(note_max) - int(note_min))
    cues = []
    for event in events:
        offset = max(0.0, (event.timestamp - float(window_start)) * scale)
        latitude_ratio = (max(-90.0, min(90.0, event.latitude)) + 90.0) / 180.0
        pitch = int(note_min) + int(round(latitude_ratio * width))
        if event.kind == "lightning_flash":
            pitch = _lightning_pitch(event, pitch, note_max)
        velocity = 20 + int(round(event.strength * 107.0))
        duration = 0.18 + (event.strength * 1.6)
        cues.append(
            ScoreCue(
                offset,
                event,
                pitch,
                velocity,
                duration=duration,
                pan=longitude_to_pan(event.longitude),
            )
        )
    cues.sort(key=lambda cue: (cue.offset, cue.event_id))
    return tuple(cues)
