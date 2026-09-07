"""Verify host-first sound catalogs without external location or provider calls.

Tests cover startup ordering, persistent settings, disabled and unavailable
GeoIP, duplicate sampling coordinates, and refreshed locations after restart.
"""

from copy import deepcopy
import json
import re

from fastapi.testclient import TestClient
import pytest

from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig, locations_with_system_location
from gaiascapes_host.service import GaiascapesService


class LocationResolver:
    """Return a deterministic location and count lookups."""

    def __init__(self, location):
        self.location = location
        self.calls = 0

    def resolve(self):
        """Return the test location without making a network request."""
        self.calls += 1
        return self.location


def test_local_catalog_preserves_count_and_swaps_duplicate_coordinates():
    catalog = AppConfig().frog_calls_locations
    original = deepcopy(catalog)
    location = dict(catalog[7], name='Test City')
    result = locations_with_system_location(catalog, location)
    assert len(result) == 19
    assert result[0] == dict(location, name='My location: Test City')
    assert result[7] == original[0]
    assert len({(item['latitude'], item['longitude']) for item in result}) == 19
    assert catalog == original
    same_first = locations_with_system_location(result, location)
    assert same_first == result


def test_startup_initializes_clients_and_persisted_lists_before_polling(tmp_path, monkeypatch):
    config = AppConfig(enabled_sources=[], osc_enabled=False, birdsong_provider='xeno_canto',
                       xeno_canto_api_key='test-key')
    config.frog_calls_locations[0] = {'name': 'My wetland', 'latitude': 40.1, 'longitude': -75.2}
    config.save(tmp_path / 'config.json')
    original = deepcopy(config)
    location = {'name': 'Denver, Colorado', 'latitude': 39.7392, 'longitude': -104.9903}
    resolver = LocationResolver(location)
    observed = []

    async def start_polling(service):
        observed.append(service.config.storm_outlook_locations[0])

    monkeypatch.setattr(GaiascapesService, 'start_polling', start_polling)
    monkeypatch.setenv('GAIA_SCAPE_HTTP_PORT', '18868')
    monkeypatch.setenv('GAIA_SCAPE_OSC_PORT', '19130')
    app = create_app(tmp_path, geoip_resolver=resolver)
    expected = dict(location, name='My location: Denver, Colorado')
    with TestClient(app) as client:
        assert observed == [expected]
        payload = client.get('/api/system-location').json()
        client.get('/api/system-location')
        assert resolver.calls == 1
        for kind in ('birdsong', 'storm_outlook'):
            catalog = payload['sound_locations'][kind]
            assert catalog == [expected, *getattr(original, f'{kind}_locations')[1:]]
            assert payload['default_sound_locations'][kind][0] == expected
        assert app.state.service.birdsong.locations[0] == expected
        assert list(app.state.service.frog_calls.locations) == original.frog_calls_locations
        assert payload['sound_locations']['frog_calls'] == original.frog_calls_locations
        assert payload['default_sound_locations']['frog_calls'] == AppConfig().frog_calls_locations
        assert app.state.service.storm.locations[0][1:] == (
            expected['name'], expected['latitude'], expected['longitude'])
        assert app.state.config.ocean_swell_locations == original.ocean_swell_locations
        home = client.get('/').text
        data = json.loads(re.search(r'<script[^>]+id="forecastLocationData"[^>]*>(.*?)</script>', home, re.S)[1])
        assert data['current']['birdsong'][0] == expected
        assert data['defaults']['storm_outlook'][0] == expected
        assert data['current']['commons_birdsong'] == original.birdsong_locations
    saved = json.loads((tmp_path / 'config.json').read_text())
    assert saved['http_port'] == 8768 and saved['osc_port'] == 57130
    assert saved['birdsong_locations'][0] == expected
    assert saved['frog_calls_locations'] == original.frog_calls_locations


@pytest.mark.parametrize('enabled,expected_calls', [(False, 0), (True, 1)])
def test_disabled_or_unavailable_geoip_preserves_saved_catalogs(tmp_path, enabled, expected_calls):
    config = AppConfig(enabled_sources=[], osc_enabled=False, system_location_enabled=enabled)
    config.save(tmp_path / 'config.json')
    original = (tmp_path / 'config.json').read_bytes()
    resolver = LocationResolver(None)
    with TestClient(create_app(tmp_path, auto_capture=False, geoip_resolver=resolver)) as client:
        assert client.get('/api/system-location').json()['location'] is None
    assert resolver.calls == expected_calls
    assert (tmp_path / 'config.json').read_bytes() == original


def test_location_refreshes_after_restart_and_failed_lookup_can_retry(tmp_path):
    AppConfig(enabled_sources=[], osc_enabled=False).save(tmp_path / 'config.json')
    resolver = LocationResolver(None)
    first = {'name': 'First City', 'latitude': 40, 'longitude': -105}
    second = {'name': 'Second City', 'latitude': 42, 'longitude': -106}
    with TestClient(create_app(tmp_path, auto_capture=False, geoip_resolver=resolver)) as client:
        assert client.get('/api/system-location').json()['location'] is None
        resolver.location = first
        assert client.get('/api/system-location').json()['sound_locations']['birdsong'][0]['latitude'] == 40
    with TestClient(create_app(tmp_path, auto_capture=False, geoip_resolver=LocationResolver(second))) as client:
        payload = client.get('/api/system-location').json()
        assert payload['sound_locations']['birdsong'][0] == dict(second, name='My location: Second City')
        assert len(payload['sound_locations']['birdsong']) == 19
