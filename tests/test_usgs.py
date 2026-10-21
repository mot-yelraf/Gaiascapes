"""Tests for USGS earthquake normalization.

Representative GeoJSON features verify validation, ordering, strength bounds,
and preservation of provider magnitude and location metadata.
"""

from gaiascapes_host.usgs import normalized_strength, parse_document


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


def test_usgs_fetch_uses_ipv4_when_dns_lists_unreachable_ipv6_first(monkeypatch):
    import json
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from gaiascapes_host.usgs import UsgsClient

    payload = json.dumps({'features': [{
        'id': 'local-quake', 'properties': {'time': 200000, 'mag': 3.2},
        'geometry': {'coordinates': [-105, 40, 12]},
    }]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        monkeypatch.setenv('NO_PROXY', '*')
        monkeypatch.setenv('no_proxy', '*')
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *_a, **_kw: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:db8::1', port, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port)),
        ])
        try:
            events = UsgsClient(f'http://127.0.0.1:{port}/feed').fetch()
            assert [event.event_id for event in events] == ['local-quake']
            assert events[0].traits['magnitude'] == 3.2
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_usgs_response_size_limit_survives_transport_change(monkeypatch):
    import io
    import pytest
    from gaiascapes_host import usgs

    response = io.BytesIO(b'{}')
    response.headers = {'Content-Length': str(usgs.MAX_DOCUMENT_BYTES + 1)}
    requests = []

    def open_url(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(usgs, 'open_url', open_url)
    with pytest.raises(ValueError, match='exceeds size limit'):
        usgs.UsgsClient('https://example.org/feed', timeout=17).fetch()
    assert requests[0][0].full_url == 'https://example.org/feed'
    assert requests[0][1] == 17
    assert requests[0][0].get_header('User-agent').startswith('Gaiascapes/')
