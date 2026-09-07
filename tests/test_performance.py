"""Tests for asynchronous performance helpers.

The focused coverage ensures per-slot gain changes renderer amplitude without
altering the musical identity or timing of a score cue.
"""

from gaiascapes.events import GaiaEvent
from gaiascapes.score import ScoreCue
from gaiascapes_host.performance import cue_with_gain


def test_cue_gain_scales_renderer_amplitude_without_changing_music():
    event = GaiaEvent("test", "event", "lightning_flash", 1)
    cue = ScoreCue(2.0, event, pitch=72, velocity=120, duration=0.8, pan=0.4)

    quieter = cue_with_gain(cue, 0.35)

    assert quieter.velocity < cue.velocity
    assert quieter.pitch == cue.pitch
    assert quieter.duration == cue.duration
    assert quieter.pan == cue.pan
    assert quieter.offset == cue.offset
