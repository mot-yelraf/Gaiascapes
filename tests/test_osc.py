import socket
import struct

from gaia_rhythms.events import GaiaEvent
from gaia_rhythms.score import ScoreCue
from gaia_rhythms_host.osc import CUE_ADDRESS, OscRenderer, encode_message


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
