"""Verify shuffled background visits and unchanged realtime scheduling.

Provider doubles exercise scheduling without network, audio, or installed state.
"""

import asyncio
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from gaiascapes.events import GaiaEvent
from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig


def test_location_order_persists_and_rejects_invalid_values(tmp_path):
    client = TestClient(create_app(tmp_path, auto_capture=False))
    assert AppConfig().sound_location_order == 'sequential'
    assert client.put('/api/settings/locations', json={'sound_location_order':'random'}).status_code == 200
    assert AppConfig.load(tmp_path/'config.json').sound_location_order == 'random'
    html = client.get('/').text
    assert html.index('id="soundLocationOrder"') < html.index('id="mapProjection"')
    assert client.put('/api/settings/locations', json={'sound_location_order':'invalid'}).status_code == 422
    assert AppConfig.load(tmp_path/'config.json').sound_location_order == 'random'


@pytest.mark.parametrize('kind', ['birdsong', 'frog_calls', 'whale_song', 'dolphin_calls',
                                  'ocean_swell', 'storm_potential'])
@pytest.mark.parametrize('order', ['sequential', 'random'])
def test_background_rounds_preserve_locations_clips_and_due_tides(tmp_path, monkeypatch, kind, order):
    svc = create_app(tmp_path, auto_capture=False).state.service
    svc.config.sound_location_order = order
    monkeypatch.setattr('gaiascapes_host.service.random.shuffle', lambda values: values.reverse())
    svc._instruments_for_kind = lambda selected: ('test',) if selected == kind else ()
    svc.config.event_instruments['event_2'] = 'tidal_bell'
    now = time.time()
    svc._last_continuous_cycle_at = now - 1
    svc.store.add_events([
        GaiaEvent('forecast', str(i), kind, now, latitude=i, longitude=i,
                  traits={'place':str(i)}) for i in range(3)
    ] + [GaiaEvent('tide', 'due', 'tide_turn', now, strength=.8),
         GaiaEvent('tide', 'future', 'tide_turn', now+3600, strength=1)])
    fetched, played = [], []
    if kind not in {'ocean_swell','storm_potential'}:
        setattr(svc, kind, SimpleNamespace(location_count=3))
    async def fetch(client, index):
        fetched.append(index)
        return GaiaEvent('recorded', str(index), kind, now,
                         latitude=index % 3, longitude=index % 3)
    async def play(event):
        played.append(event)
    svc._fetch_recording = fetch
    svc._play_live_event = play
    async def run():
        for _ in range(6):
            await svc.play_next_ambient_layers()
    asyncio.run(run())
    sites = [event.latitude for event in played if event.kind == kind]
    assert sites == ([0,1,2,0,1,2] if order == 'sequential' else [2,1,0,2,1,0])
    assert [event.event_id for event in played if event.kind == 'tide_turn'] == ['due']
    if fetched:
        assert fetched == ([0,1,2,3,4,5] if order == 'sequential' else [2,1,0,5,4,3])
