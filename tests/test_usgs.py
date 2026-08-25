from gaia_scape_host.usgs import normalized_strength, parse_document


def test_parse_document_normalizes_valid_features_and_sorts():
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "second",
                "properties": {"time": 200000, "mag": 4.0, "place": "Two"},
                "geometry": {"coordinates": [-120.0, 35.0, 12.5]},
            },
            {
                "id": "first",
                "properties": {"time": 100000, "mag": 2.0, "place": "One"},
                "geometry": {"coordinates": [10.0, -20.0, 3.0]},
            },
            {"id": "bad", "properties": {}, "geometry": None},
        ],
    }

    events = parse_document(document)

    assert [event.event_id for event in events] == ["first", "second"]
    assert events[1].traits == {
        "magnitude": 4.0,
        "depth_km": 12.5,
        "place": "Two",
        "url": "",
    }
    assert events[1].longitude == -120.0


def test_magnitude_strength_is_bounded_but_raw_value_is_preserved():
    assert normalized_strength(-20) == (0.0, -20.0)
    assert normalized_strength(20) == (1.0, 20.0)

