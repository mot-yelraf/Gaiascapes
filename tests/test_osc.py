"""Tests for OSC encoding and renderer behavior.

The cases verify byte-aligned messages, cue routing, disabled instruments,
and lifecycle messages for persistent background layers.
"""

import socket
import struct

from gaiascapes.events import GaiaEvent
from gaiascapes.score import ScoreCue
from gaiascapes_host.osc import (
    CUE_ADDRESS,
    LAYER_ADDRESS,
    LAYER_STOP_ADDRESS,
    OscRenderer,
    encode_message,
)


def test_encoder_builds_aligned_osc_message():
    packet = encode_message("/test", ("quake", 42, 0.5))

    assert packet.startswith(b"/test\0\0\0,sif\0\0\0\0")
    assert len(packet) % 4 == 0
    assert packet.endswith(struct.pack(">f", 0.5))


def test_renderer_sends_documented_cue(monkeypatch):
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def sendto(self, packet, destination):
            sent.append((packet, destination))

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    event = GaiaEvent(
        "usgs", "abc", "earthquake", 1, strength=0.5, traits={"magnitude": 3, "depth_km": 9}
    )
    cue = ScoreCue(0, event, 60, 80)
    renderer = OscRenderer(
        "127.0.0.1", 57130, instrument_mappings={"earthquake": "seismic_bells"}
    )

    renderer.play(cue)

    assert sent[0][0].startswith(CUE_ADDRESS.encode())
    assert b"seismic_bells" in sent[0][0]
    assert sent[0][1] == ("127.0.0.1", 57130)
    assert renderer.sent_count == 1


def test_renderer_does_not_send_cue_mapped_to_none(monkeypatch):
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def sendto(self, packet, destination):
            sent.append((packet, destination))

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    event = GaiaEvent("usgs", "silent", "earthquake", 1)
    cue = ScoreCue(0, event, 60, 80)
    renderer = OscRenderer(
        "127.0.0.1", 57130, instrument_mappings={"earthquake": "none"}
    )

    assert renderer.play(cue) is False
    assert sent == []
    assert renderer.sent_count == 0


def test_renderer_updates_and_releases_persistent_layer(monkeypatch):
    sent = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def sendto(self, packet, destination):
            sent.append((packet, destination))

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    event = GaiaEvent(
        "open_meteo_marine", "swell", "ocean_swell", 1,
        strength=0.5, traits={"magnitude": 2.1, "swell_period_s": 11.5},
    )
    cue = ScoreCue(0, event, 60, 80, duration=12.0)
    renderer = OscRenderer(
        "127.0.0.1", 57130, instrument_mappings={"ocean_swell": "ocean_swell"}
    )

    assert renderer.update_layer(cue) is True
    assert renderer.status()["active_layers"] == ["ocean_swell"]
    assert sent[0][0].startswith(LAYER_ADDRESS.encode())
    assert renderer.stop_layer("ocean_swell", release=4.0) is True
    assert sent[1][0].startswith(LAYER_STOP_ADDRESS.encode())
    assert renderer.status()["active_layers"] == []


def test_renderer_transmits_independent_gain_and_saved_channel_volumes(monkeypatch):
    packets = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def sendto(self, packet, destination):
            packets.append(packet)

    monkeypatch.setattr(socket, "socket", lambda *args: FakeSocket())
    event = GaiaEvent("test", "quiet", "earthquake", 1, strength=.5)
    cue = ScoreCue(0, event, 60, 120, gain=.01, output_channel="event_2")
    renderer = OscRenderer("127.0.0.1", 57130)
    for send in (renderer.play, renderer.update_layer):
        send(cue, "earthquake")
        assert packets[-1].endswith(struct.pack(">f", .01) + b"event_2\0")
    renderer.set_volumes({"background": .9, "event_1": .1, "event_2": 0, "event_3": .5})
    assert packets[-1] == encode_message("/gaia/volumes", (.9 ** 2, .1 ** 2, 0.0, .25))
    renderer.enabled = False
    count = len(packets)
    renderer.set_volumes({})
    assert len(packets) == count
