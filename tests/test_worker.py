"""Exercise worker deadlines, cancellation, and provider state transfer.

Local fixtures and a controlled HTTP server keep recovery tests independent of
external providers and installed runtime data.
"""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest

from gaiascapes.events import GaiaEvent
from gaiascapes_host.open_meteo import OpenMeteoMarineClient
from gaiascapes_host.polling import PollingCoordinator
from gaiascapes_host.usgs import UsgsClient
from gaiascapes_host.worker import call_client


def test_completed_worker_preserves_provider_cache_and_status():
    client = OpenMeteoMarineClient()
    event = GaiaEvent('open_meteo_marine', 'cached', 'ocean_swell', time.time(), strength=.5)
    client._cached_events = (event,)
    client._has_cache = True
    client._cache_updated_at = time.monotonic()
    client.last_fetch_used_fallback = True
    result = asyncio.run(call_client(client, 'fetch', timeout=5))
    assert [item.as_dict() for item in result] == [event.as_dict()]
    assert client.last_fetch_used_fallback is False
    assert client._cached_events == (event,)


@pytest.mark.parametrize('cancel', [False, True])
def test_provider_worker_recovers_after_stuck_request(cancel):
    started, release = threading.Event(), threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if len(requests) == 1:
                started.set()
                release.wait(5)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"features": []}')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = UsgsClient(f'http://127.0.0.1:{server.server_port}/feed')

    async def run():
        polling = PollingCoordinator(['usgs'])
        pending = asyncio.create_task(polling.fetch('usgs', client, 5 if cancel else .8))
        assert await asyncio.to_thread(started.wait, 3)
        if cancel:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(TimeoutError, match='worker restarted'):
                await pending
        assert await polling.fetch('usgs', client, 5) == ()
        assert len(requests) == 2

    try:
        asyncio.run(run())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
