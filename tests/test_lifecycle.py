"""Regression coverage for provider, settings, and playback boundaries.

All observations and network delays are synthetic; each application uses its
own temporary installation and never sends audio to a production renderer.
"""

import asyncio
from copy import deepcopy
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from gaia_scape.events import GaiaEvent
from gaia_scape_host.app import create_app
from gaia_scape_host.config import AppConfig
from gaia_scape_host.open_meteo import OpenMeteoMarineClient


class Provider:
    def __init__(self, events=()):
        self.events = events

    def fetch(self):
        return self.events


def application(tmp_path, **clients):
    app = create_app(tmp_path, auto_capture=False, usgs_client=clients.pop('usgs_client', Provider()), **clients)
    app.state.service.renderer.enabled = False
    return app


def test_stop_blocks_new_cues_but_capture_continues(tmp_path):
    now = time.time()
    app = application(tmp_path,
        usgs_client=Provider((GaiaEvent('usgs', 'quake', 'earthquake', now),)),
        glm_client=Provider((GaiaEvent('noaa_glm', 'flash', 'lightning_flash', now),)),
    )
    with TestClient(app) as client:
        assert client.put('/api/live/mode', json={'mode': 'continuous'}).status_code == 200
        assert client.post('/api/live/stop').json()['running'] is False
        client.post('/api/capture')
        asyncio.run(app.state.service.capture_glm_once())
        assert app.state.service.store.count() == 2
        assert app.state.service._cue_sequence == 0
        assert not app.state.service.playback.tasks
        assert client.post('/api/live/start').json()['running'] is True


def test_stop_drains_inflight_renderer_call(tmp_path):
    app = application(tmp_path)
    service = app.state.service
    started, release = threading.Event(), threading.Event()

    def render(*args):
        started.set()
        assert release.wait(2)
        return True

    service.renderer.play = render

    async def exercise():
        service.playback.start()
        service.playback.schedule(service._play_live_event(
            GaiaEvent('usgs', 'inflight', 'earthquake', time.time())
        ), 'test-render')
        assert await asyncio.to_thread(started.wait, 2)
        stopping = asyncio.create_task(service.stop_continuous())
        try:
            await asyncio.sleep(.01)
            assert not stopping.done()
        finally:
            release.set()
            await stopping
        assert not service.playback.tasks
        assert not service.playback.enabled

    asyncio.run(exercise())


def test_recent_history_filters_hidden_rows_before_limit(tmp_path):
    app = application(tmp_path)
    now = time.time()
    app.state.service.store.add_events([
        GaiaEvent('noaa_glm', str(i), 'lightning_flash', now - 3000 + i / 10)
        for i in range(20000)
    ] + [GaiaEvent('usgs', 'newest', 'earthquake', now - 1)])
    history = asyncio.run(app.state.service.recent_events(hours=2, limit=1))
    assert [event['event_id'] for event in history] == ['newest']


def test_restart_filters_provider_before_selecting_lightning(tmp_path):
    app = application(tmp_path)
    now = time.time()
    app.state.service.store.add_events([
        GaiaEvent('eumetsat_mtg_li', str(i), 'lightning_flash', now - 1)
        for i in range(600)
    ] + [GaiaEvent('noaa_glm', 'noaa', 'lightning_flash', now - 2)])
    restarted = application(tmp_path)
    assert [event.event_id for event in restarted.state.service._last_glm_sonification_events] == ['noaa']


def test_mtg_restart_resumes_all_future_products_without_noaa_starvation(tmp_path):
    app = application(tmp_path)
    now = time.time()
    app.state.service.store.add_events([
        GaiaEvent('noaa_glm', str(i), 'lightning_flash', now - 600)
        for i in range(1100)
    ] + [
        GaiaEvent('eumetsat_mtg_li', product, 'lightning_flash', now - age, traits={'product': product})
        for product, age in [('earlier', 200), ('later', 100)]
    ])
    service = app.state.service
    scheduled = []
    service._start_mtg_sonification = lambda events: scheduled.append(events)
    asyncio.run(service._restore_mtg_schedule())
    assert {events[0].traits['product'] for events in scheduled} == {'earlier', 'later'}


def test_slow_provider_does_not_delay_persisting_or_sounding_earthquake(tmp_path):
    started, release = threading.Event(), threading.Event()

    class SlowProvider:
        def fetch(self):
            started.set()
            assert release.wait(2)
            return ()

    app = application(tmp_path,
        usgs_client=Provider((GaiaEvent('usgs', 'prompt', 'earthquake', time.time()),)),
        marine_client=SlowProvider(),
    )
    service = app.state.service
    service.config.enabled_sources = ['usgs', 'open_meteo_marine']
    service.config.live_mode = 'continuous'
    service.playback.start()
    played = threading.Event()
    service.renderer.play = lambda *args: played.set() or True

    async def exercise():
        capture = asyncio.create_task(service.capture_once())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            assert await asyncio.to_thread(played.wait, 1)
            assert service.store.count() == 1
            assert not capture.done()
        finally:
            release.set()
            await capture
            await service.stop()

    asyncio.run(exercise())


def test_polling_owns_independent_idempotent_tasks(tmp_path):
    app = application(tmp_path)
    app.state.config.enabled_sources = []

    async def exercise():
        service = app.state.service
        await service.start_polling()
        tasks = dict(service.polling.tasks)
        await service.start_polling()
        assert service.polling.tasks == tasks
        assert len(tasks) == 5
        await service.stop()
        assert all(task.done() for task in tasks.values())
        assert not service.polling.running()

    asyncio.run(exercise())


def test_failed_settings_save_leaves_config_clients_and_history_unchanged(tmp_path, monkeypatch):
    app = application(tmp_path)
    config = app.state.config
    locations = deepcopy(config.ocean_swell_locations)
    locations[0]['name'] = 'Replacement'
    app.state.service.store.add_events((GaiaEvent(
        'open_meteo_marine', 'retained', 'ocean_swell', time.time(),
        traits={'place': config.ocean_swell_locations[0]['name']},
    ),))
    original = (tmp_path / 'config.json').read_bytes()
    original_client = app.state.service.marine

    def failed_save(*args):
        raise OSError('disk unavailable')

    monkeypatch.setattr(AppConfig, 'save', failed_save)
    with TestClient(app) as client:
        response = client.put('/api/settings/locations', json={
            'ocean_swell_locations': locations,
            'storm_outlook_locations': config.storm_outlook_locations,
        })
        assert response.status_code == 503
        assert client.put('/api/live/mode', json={'mode': 'continuous'}).status_code == 503
    assert config.live_mode == 'capture'
    assert app.state.service.marine is original_client
    assert config.ocean_swell_locations != locations
    assert app.state.service.store.count() == 1
    assert (tmp_path / 'config.json').read_bytes() == original


def test_location_edit_discards_inflight_old_forecast(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    parsed_locations = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, maximum):
            started.set()
            assert release.wait(2)
            return b'{}'

    monkeypatch.setattr('urllib.request.urlopen', lambda *args, **kwargs: Response())
    app = application(tmp_path)
    service = app.state.service
    service.config.enabled_sources = ['open_meteo_marine']
    original = service.marine

    def parse(document, locations):
        parsed_locations.append(locations)
        return (GaiaEvent('open_meteo_marine', 'obsolete', 'ocean_swell', time.time()),)

    original.parser = parse
    old_locations = original.locations
    locations = deepcopy(service.config.ocean_swell_locations)
    locations[0]['name'] = 'New location'

    async def exercise():
        capture = asyncio.create_task(service.capture_once())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await service.update_settings({'ocean_swell_locations': locations}, tmp_path / 'config.json')
        finally:
            release.set()
            await capture
        assert service.store.count() == 0
        assert service.marine is not original
        assert parsed_locations == [old_locations]
        assert json.loads((tmp_path / 'config.json').read_text())['ocean_swell_locations'] == locations

    asyncio.run(exercise())


def test_audio_transport_failure_does_not_mark_capture_offline(tmp_path):
    app = application(tmp_path, usgs_client=Provider((
        GaiaEvent('usgs', 'quake', 'earthquake', time.time()),
    )))
    service = app.state.service
    service.config.enabled_sources = ['usgs']
    service.config.live_mode = 'continuous'
    service.playback.start()

    def failed_transport(*args):
        raise OSError('audio transport unavailable')

    service.renderer.play = failed_transport
    result = asyncio.run(service.capture_once())
    assert result['inserted'] == 1
    assert service._source_recovery['usgs'].state == 'online'
    assert 'Playback failed' in service.continuous_last_error


def test_concurrent_settings_updates_preserve_both_changes_and_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('GAIA_SCAPE_HTTP_PORT', '18868')
    monkeypatch.setenv('GAIA_SCAPE_OSC_PORT', '18869')
    app = application(tmp_path)
    service = app.state.service

    async def exercise():
        await asyncio.gather(
            service.update_settings({'units': 'imperial'}, tmp_path / 'config.json'),
            service.update_settings({'app_view': 'map'}, tmp_path / 'config.json'),
        )

    asyncio.run(exercise())
    persisted = json.loads((tmp_path / 'config.json').read_text())
    assert persisted['units'] == 'imperial'
    assert persisted['app_view'] == 'map'
    assert (persisted['http_port'], persisted['osc_port']) == (8768, 57130)
    assert (service.config.http_port, service.config.osc_port) == (18868, 18869)


def test_start_waits_for_concurrent_stop_to_finish(tmp_path):
    app = application(tmp_path)
    service = app.state.service
    entered, release = threading.Event(), threading.Event()

    def stop_layer(*args):
        entered.set()
        assert release.wait(2)
        return False

    service.renderer.stop_layer = stop_layer

    async def exercise():
        await service.start_continuous()
        stopping = asyncio.create_task(service.stop_continuous())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            starting = asyncio.create_task(service.start_continuous())
            await asyncio.sleep(.01)
            assert not starting.done()
        finally:
            release.set()
            await stopping
        await starting
        assert service.playback.enabled
        assert service._continuous_task in service.playback.tasks
        await service.stop()

    asyncio.run(exercise())
