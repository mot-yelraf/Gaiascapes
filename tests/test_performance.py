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

    assert quieter.velocity == cue.velocity
    assert quieter.gain == 0.35 ** 2
    assert quieter.pitch == cue.pitch
    assert quieter.duration == cue.duration
    assert quieter.pan == cue.pan
    assert quieter.offset == cue.offset


def test_volume_taper_matches_recorded_player_at_low_and_high_settings():
    import pytest

    cue = ScoreCue(0, GaiaEvent("test", "quiet", "earthquake", 1), 60, 100)
    for slider, expected in ((0, 0), (.1, .01), (.5, .25), (.9, .81), (1, 1)):
        adjusted = cue_with_gain(cue, slider, "event_2")
        assert adjusted.gain == pytest.approx(expected)
        assert adjusted.velocity == 100
        assert adjusted.output_channel == "event_2"
