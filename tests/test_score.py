from gaia_rhythms.events import GaiaEvent
from gaia_rhythms.score import build_score, longitude_to_pan


def test_score_preserves_relative_time_and_maps_geography():
    events = (
        GaiaEvent("usgs", "later", "earthquake", 1060, 90, 180, 1.0),
        GaiaEvent("usgs", "first", "earthquake", 1000, -90, -180, 0.0),
    )

    score = build_score(events, 1000, 120, 12)

    assert [cue.event_id for cue in score] == ["first", "later"]
    assert [cue.offset for cue in score] == [0.0, 6.0]
    assert score[0].pitch == 36
    assert score[1].pitch == 84
    assert score[0].pan == -1.0
    assert score[1].pan == 1.0
    assert longitude_to_pan(0) == 0.0


def test_event_strength_is_bounded():
    assert GaiaEvent("x", "1", "test", 1, strength=-2).strength == 0.0
    assert GaiaEvent("x", "2", "test", 1, strength=9).strength == 1.0


def test_lightning_flash_is_four_semitones_higher_than_other_events():
    earthquake = GaiaEvent("x", "quake", "earthquake", 1, latitude=0)
    lightning = GaiaEvent("x", "flash", "lightning_flash", 1, latitude=0)

    score = build_score((earthquake, lightning), 1, 1, 1)

    pitches = {cue.kind: cue.pitch for cue in score}
    assert pitches["lightning_flash"] >= pitches["earthquake"] + 4


def test_lightning_flash_ids_create_pitch_variation_at_one_location():
    flashes = tuple(
        GaiaEvent(
            "noaa_glm", f"flash-{index}", "lightning_flash", 1,
            latitude=20, longitude=-80, strength=0.7,
            traits={"flash_id": index},
        )
        for index in range(5)
    )

    score = build_score(flashes, 1, 1, 1)

    assert len({cue.pitch for cue in score}) == 5
