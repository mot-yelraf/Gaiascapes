"""Tests for provider-independent public-IP location resolution.

The tests use local response doubles so location behavior remains deterministic
and never contacts an external geolocation service.
"""

import json

from gaiascapes_host.geoip import GeoIpLocationResolver


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_geoip_uses_https_fallback_and_caches_success():
    calls = []
    responses = [
        {"latitude": "outside", "longitude": 0},
        {
            "success": True,
            "lat": 39.7392,
            "lon": -104.9903,
            "city": "Denver",
            "region": "Colorado",
            "country": "United States",
            "timezone": {"id": "America/Denver"},
        },
    ]

    def opener(request, *, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(responses.pop(0))

    resolver = GeoIpLocationResolver(timeout_seconds=1.25, opener=opener)
    first = resolver.resolve()
    second = resolver.resolve()

    assert first == second == {
        "name": "Denver, Colorado, United States",
        "latitude": 39.7392,
        "longitude": -104.9903,
        "timezone": "America/Denver",
        "provider": "ipwho.is",
    }
    assert calls == [
        ("https://ipapi.co/json/", 1.25),
        ("https://ipwho.is/", 1.25),
    ]


def test_geoip_rejects_failed_and_out_of_range_responses():
    responses = [
        {"success": False, "latitude": 40, "longitude": -105},
        {"lat": 95, "lon": -105},
    ]

    def opener(_request, *, timeout):
        assert timeout == 2.5
        return FakeResponse(responses.pop(0))

    assert GeoIpLocationResolver(opener=opener).resolve() is None
