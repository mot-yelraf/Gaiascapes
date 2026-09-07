"""Verify Xeno-canto licensing, coordinates, caching, and credential handling.

Synthetic responses cover rejected metadata and transport failures without
sending credentials to the network or touching installed runtime state.
"""

import io
import json
import urllib.error

import pytest

from gaiascapes_host.xeno_canto import COUNTRIES, XenoCantoClient, _record


def recording(**changes):
    item = dict(id="42", grp="birds", status="identified", lat="52.1", lon="-1.2",
                lic="https://creativecommons.org/licenses/by-sa/4.0/", rec="Recordist",
                en="Eurasian Wren", gen="Troglodytes", sp="troglodytes", type="song",
                cnt="United Kingdom", loc="Woodland", length="0:30", q="A",
                date="2025-05-02", time="06:30")
    item["file-name"] = "XC42-wren.mp3"
    item.update(changes)
    return item


class Response(io.BytesIO):
    headers = {"Content-Type": "audio/mpeg"}


def test_cache_rotation_and_credential_separation(tmp_path):
    requests = []
    responses = [Response(json.dumps({"recordings": [recording(), recording(id="43")]}).encode()),
                 Response(b"ID3-first"), Response(b"ID3-second")]

    def opener(request, timeout):
        requests.append(request.full_url)
        return responses.pop(0)

    client = XenoCantoClient(tmp_path, "private-test-key", opener)
    first = client.event_at(0)
    repeated = client.event_at(0)
    second = client.event_at(len(COUNTRIES))
    assert first.provider == "xeno_canto"
    assert first.latitude == 52.1 and first.longitude == -1.2
    assert first.traits["recorded_date"] == "2025-05-02"
    assert repeated.traits["recording_id"] == "42"
    assert second.traits["recording_id"] == "43"
    assert len(requests) == 3
    assert "private-test-key" in requests[0]
    assert all("private-test-key" not in url for url in requests[1:])
    assert "private-test-key" not in repr(first)
    assert "private-test-key" not in (client.media_dir / "canada.json").read_text()


@pytest.mark.parametrize("changes", [
    {"lat": "restricted_species"}, {"lon": None}, {"lat": "NaN"}, {"lat": "91"},
    {"lon": "181"}, {"grp": "land mammals"}, {"status": "questioned"},
    {"lic": "https://creativecommons.org/licenses/by-nc-nd/4.0/"},
    {"lic": "https://creativecommons.org/licenses/by-nc/4.0/"},
    {"lic": "https://creativecommons.org/licenses/by-nd/4.0/"},
    {"lic": "https://example.com/licenses/by-sa/4.0/"},
    {"file-name": "XC42.html"}, {"id": "../../config"}, {"length": "10:00"},
    {"q": "C"}, {"q": ""},
])
def test_reject_unusable_recordings(changes):
    assert _record(recording(**changes)) is None


@pytest.mark.parametrize('group', ['birds', 'frogs'])
@pytest.mark.parametrize('version', ['2.0', '2.5', '3.0', '4.0'])
def test_noncommercial_sharealike_preserves_license_and_attribution(group, version):
    license_url = f'https://creativecommons.org/licenses/by-nc-sa/{version}/'
    item = _record(recording(grp=group, lic=license_url), group)
    assert item['license'] == f'CC BY-NC-SA {version}'
    assert item['license_url'] == license_url
    assert item['creator'] == 'Recordist'
    assert item['source_url'] == 'https://xeno-canto.org/42'


@pytest.mark.parametrize('group', ['birds', 'frogs'])
def test_catalog_refreshes_old_policy_and_includes_noncommercial_recordings(tmp_path, group):
    import time
    from urllib.parse import parse_qs, urlparse

    requests = []
    responses = [Response(json.dumps({'recordings': [recording(
        id='84', grp=group, lic='https://creativecommons.org/licenses/by-nc-sa/4.0/')]}).encode()),
        Response(b'ID3-audio')]

    def opener(request, timeout):
        requests.append(request.full_url)
        return responses.pop(0)

    client = XenoCantoClient(tmp_path, 'private-test-key', opener, group=group)
    # A fresh cache from the previous license policy must not hide newly
    # eligible local recordings for the rest of its 24-hour lifetime.
    cache = client.media_dir / 'canada.json'
    cache.write_text(json.dumps({'fetched_at': time.time(),
                                 'records': [_record(recording(grp=group), group)]}))
    event = client.event_at(0)
    assert event.traits['recording_id'] == '84'
    assert event.traits['license'] == 'CC BY-NC-SA 4.0'
    query = parse_qs(urlparse(requests[0]).query)['query'][0]
    assert 'lic:' not in query
    assert ('q:">C"' in query) == (group == 'birds')
    assert client.event_at(0).traits['recording_id'] == '84'
    assert len(requests) == 2
    assert 'private-test-key' not in cache.read_text()


def test_api_error_redacts_key_and_backs_off(tmp_path):
    requests = []

    def opener(request, timeout):
        requests.append(request)
        raise urllib.error.HTTPError(request.full_url, 429, "private-test-key", {}, None)

    client = XenoCantoClient(tmp_path, "private-test-key", opener)
    with pytest.raises(RuntimeError, match="rate limit") as error:
        client.event_at(0)
    assert "private-test-key" not in str(error.value)
    assert error.value.__suppress_context__
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        client.event_at(0)
    assert len(requests) == 1


def test_reject_html_download_without_leaving_media(tmp_path):
    responses = [Response(json.dumps({"recordings": [recording()]}).encode()), Response(b"<html>")]
    responses[1].headers = {"Content-Type": "text/html"}
    client = XenoCantoClient(tmp_path, "test", lambda request, timeout: responses.pop(0))
    with pytest.raises(RuntimeError, match="audio file"):
        client.event_at(0)
    assert not list(client.media_dir.glob("*.mp3*"))


def test_selected_region_filters_recordings_and_separates_moved_cache(tmp_path):
    from urllib.parse import parse_qs, urlparse

    requests = []
    region = {"name": "Chosen woodland", "latitude": 52.0, "longitude": -1.0}
    responses = [
        Response(json.dumps({"recordings": [recording(id="99", lat="40", lon="-105"), recording()]}).encode()),
        Response(b"ID3-first"),
        Response(json.dumps({"recordings": [recording(id="43", lat="40.1", lon="-105.1")]}).encode()),
        Response(b"ID3-second"),
    ]
    def opener(request, timeout):
        requests.append(request.full_url)
        return responses.pop(0)

    client = XenoCantoClient(tmp_path, "test", opener, locations=[region])
    event = client.event_at(0)
    assert event.traits["recording_id"] == "42"
    assert (event.latitude, event.longitude) == (52.1, -1.2)
    assert event.traits["region_name"] == "Chosen woodland"
    assert client.event_at(0).traits["recording_id"] == "42"
    assert len(requests) == 2
    query = parse_qs(urlparse(requests[0]).query)["query"][0]
    assert "box:" in query and "cnt:" not in query
    moved = {"name": "Colorado", "latitude": 40.0, "longitude": -105.0}
    client = XenoCantoClient(tmp_path, "test", opener, locations=[moved])
    assert client.event_at(0).traits["recording_id"] == "43"
    assert len(list(client.media_dir.glob("region-*.json"))) == 2


def test_region_search_checks_later_pages_and_reports_empty_region(tmp_path):
    from gaiascapes_host.xeno_canto import NoBirdsongRecordingsError

    responses = [
        Response(json.dumps({"numPages": 2, "recordings": [recording(lat="0", lon="0")]}).encode()),
        Response(json.dumps({"numPages": 2, "recordings": [recording()]}).encode()),
        Response(b"ID3-audio"),
        Response(json.dumps({"recordings": [recording()]}).encode()),
    ]
    client = XenoCantoClient(tmp_path, "test", lambda request, timeout: responses.pop(0),
                            locations=[{"name": "Woodland", "latitude": 52, "longitude": -1},
                                       {"name": "Distant region", "latitude": 0, "longitude": 0}])
    assert client.event_at(0).traits["recording_id"] == "42"
    with pytest.raises(NoBirdsongRecordingsError, match="within 100 km of Distant region"):
        client.event_at(1)


def test_region_bounds_cover_date_line_and_poles():
    from gaiascapes_host.xeno_canto import _region_boxes, _within_region

    for longitude in (-179.8, 179.8):
        location = {"latitude": 0, "longitude": longitude}
        boxes = _region_boxes(location)
        assert len(boxes) == 2
        assert all(-180 <= west <= east <= 180 for _, west, _, east in boxes)
        assert _within_region({"latitude": 0, "longitude": -longitude}, location)
        assert not _within_region({"latitude": 0, "longitude": 0}, location)
    for latitude in (-90, 90):
        south, west, north, east = _region_boxes({"latitude": latitude, "longitude": 0})[0]
        assert -90 <= south <= north <= 90
        assert (west, east) == (-180, 180)


def test_frog_queries_filter_group_and_use_separate_cache(tmp_path):
    from urllib.parse import parse_qs, urlparse

    region = {"name": "Wetland", "latitude": 52.0, "longitude": -1.0}
    bird = recording()
    frog = recording(id="84", grp="frogs", en="Common Tree Frog", gen="Hyla", sp="arborea",
                     length="0:03", q="", lic="https://creativecommons.org/licenses/by/4.0/")
    assert _record(frog) is None
    assert _record(bird, "frogs") is None
    responses = [Response(json.dumps({"recordings": [bird, frog]}).encode()), Response(b"ID3-frog")]
    requests = []
    def opener(request, timeout):
        requests.append(request.full_url)
        return responses.pop(0)

    birds = XenoCantoClient(tmp_path, "shared-key", locations=[region])
    frogs = XenoCantoClient(tmp_path, "shared-key", opener, locations=[region], group="frogs")
    event = frogs.event_at(0)
    assert event.kind == "frog_calls"
    assert event.traits["recording_id"] == "84"
    assert event.traits["media_url"] == "/frog-calls-media/xeno-canto/XC84.mp3"
    assert event.traits["creator"] == "Recordist"
    assert (event.latitude, event.longitude) == (52.1, -1.2)
    assert birds.media_dir != frogs.media_dir
    query = parse_qs(urlparse(requests[0]).query)["query"][0]
    assert "grp:frogs" in query
    assert "q:" not in query and "lic:" not in query
    assert event.traits["license"] == "CC BY 4.0"
    assert "shared-key" not in requests[1]
    assert frogs.event_at(0).traits["recording_id"] == "84"
    assert len(requests) == 2
    assert not list(birds.media_dir.glob("*.json"))


def test_empty_frog_region_never_falls_back_to_birds(tmp_path):
    from gaiascapes_host.xeno_canto import NoRecordingsError

    document = {"recordings": [recording()]}
    client = XenoCantoClient(tmp_path, "test", lambda request, timeout: Response(json.dumps(document).encode()),
                            locations=[{"name": "Wetland", "latitude": 52, "longitude": -1}], group="frogs")
    with pytest.raises(NoRecordingsError, match="frogs recordings within 100 km of Wetland"):
        client.event_at(0)
    assert not list(client.media_dir.glob("*.mp3"))


@pytest.mark.parametrize('name', ['My location: Silver City, New Mexico, United States', 'Silver City, NM'])
def test_new_mexico_plays_selected_roadrunner_outside_radius(tmp_path, name):
    from urllib.parse import parse_qs, urlparse
    from gaiascapes_host.xeno_canto import _within_region

    location = {'name': name, 'latitude': 32.77, 'longitude': -108.28}
    roadrunner = recording(id='254791', en='Greater Roadrunner', gen='Geococcyx',
                          sp='californianus', lat='31.84', lon='-109.025',
                          loc='Rodeo, Hidalgo County, New Mexico', cnt='United States',
                          rec='Richard E. Webster', length='1:14', q='B',
                          lic='https://creativecommons.org/licenses/by-nc-sa/4.0/')
    assert not _within_region(_record(roadrunner), location)
    responses = [Response(json.dumps({'recordings': [recording(), roadrunner]}).encode()),
                 Response(b'ID3-roadrunner')]
    requests = []

    def opener(request, timeout):
        requests.append(request.full_url)
        return responses.pop(0)

    client = XenoCantoClient(tmp_path, 'private-test-key', opener, locations=[location])
    event = client.event_at(0)
    assert event.traits['recording_id'] == '254791'
    assert event.traits['title'] == 'Greater Roadrunner · song'
    assert event.traits['creator'] == 'Richard E. Webster'
    assert event.traits['license'] == 'CC BY-NC-SA 4.0'
    assert event.traits['source_url'] == 'https://xeno-canto.org/254791'
    assert event.traits['recording_selection'] == 'New Mexico state bird'
    assert 'region_radius_km' not in event.traits
    assert (event.latitude, event.longitude) == (31.84, -109.025)
    assert event.traits['region_latitude'] == 32.77
    query = parse_qs(urlparse(requests[0]).query)['query'][0]
    assert 'nr:254791' in query and 'box:' not in query
    assert client.event_at(1).traits['recording_id'] == '254791'
    assert len(requests) == 2


def test_unavailable_new_mexico_roadrunner_does_not_substitute_other_birds(tmp_path):
    from gaiascapes_host.xeno_canto import NoRecordingsError

    client = XenoCantoClient(tmp_path, 'test',
                            lambda request, timeout: Response(json.dumps({'recordings': [recording()]}).encode()),
                            locations=[{'name': 'Albuquerque, New Mexico', 'latitude': 35.08, 'longitude': -106.65}])
    with pytest.raises(NoRecordingsError, match='Greater Roadrunner song .* unavailable or unsuitable'):
        client.event_at(0)


def test_new_mexico_frogs_still_use_regional_search(tmp_path):
    from urllib.parse import parse_qs, urlparse

    requests = []
    frog = recording(grp='frogs', en='Canyon Tree Frog', lat='32.77', lon='-108.28')

    def opener(request, timeout):
        requests.append(request.full_url)
        return Response(json.dumps({'recordings': [frog]}).encode())

    location = {'name': 'Silver City, NM', 'latitude': 32.77, 'longitude': -108.28}
    client = XenoCantoClient(tmp_path, 'test', opener, locations=[location], group='frogs')
    assert client._catalog(location['name'], location)[0]['id'] == '42'
    query = parse_qs(urlparse(requests[0]).query)['query'][0]
    assert 'box:' in query and 'nr:' not in query
