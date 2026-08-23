"""Minimal Open Sound Control encoder and UDP renderer."""

from __future__ import annotations

import socket
import struct


CUE_ADDRESS = "/gaia/cue"


def _osc_string(value: str) -> bytes:
    encoded = str(value).encode("utf-8") + b"\0"
    return encoded + (b"\0" * ((-len(encoded)) % 4))


def encode_message(address: str, arguments) -> bytes:
    """Encode OSC strings, integers, and floats without a third-party runtime."""
    tags = [","]
    payload = []
    for value in arguments:
        if isinstance(value, str):
            tags.append("s")
            payload.append(_osc_string(value))
        elif isinstance(value, bool):
            tags.append("i")
            payload.append(struct.pack(">i", int(value)))
        elif isinstance(value, int):
            tags.append("i")
            payload.append(struct.pack(">i", value))
        elif isinstance(value, float):
            tags.append("f")
            payload.append(struct.pack(">f", value))
        else:
            raise TypeError(f"Unsupported OSC argument type: {type(value).__name__}")
    return _osc_string(address) + _osc_string("".join(tags)) + b"".join(payload)


class OscRenderer:
    """Send the documented Gaia Rhythms cue contract over UDP."""

    def __init__(self, host: str, port: int, enabled: bool = True, instrument_mappings=None):
        self.host = str(host)
        self.port = int(port)
        self.enabled = bool(enabled)
        self.instrument_mappings = dict(instrument_mappings or {})
        self.sent_count = 0
        self.last_error = ""

    def play(self, cue, instrument=None) -> None:
        """Send one immediate cue to SuperCollider."""
        if not self.enabled:
            return
        event = cue.event
        magnitude = float(event.traits.get("magnitude", 0.0))
        secondary = float(
            event.traits.get(
                "depth_km",
                event.traits.get(
                    "swell_period_s", event.traits.get("wind_gust_kmh", 0.0)
                ),
            )
        )
        arguments = (
            cue.event_id,
            cue.kind,
            instrument or self.instrument_mappings.get(cue.kind, cue.kind),
            cue.pitch,
            cue.velocity,
            cue.duration,
            cue.pan,
            event.strength,
            event.longitude,
            event.latitude,
            magnitude,
            secondary,
        )
        try:
            packet = encode_message(CUE_ADDRESS, arguments)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as output:
                output.sendto(packet, (self.host, self.port))
            self.sent_count += 1
            self.last_error = ""
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise

    def status(self) -> dict:
        """Return renderer status for the web application."""
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "sent_count": self.sent_count,
            "last_error": self.last_error,
            "instrument_mappings": dict(self.instrument_mappings),
        }
