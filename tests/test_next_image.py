"""Verify image stepping never emits audio and Play uses the staged recording.

Fake archive retrieval keeps these checks independent of media and Wikipedia.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gaiascapes.events import GaiaEvent
from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig


@pytest.mark.parametrize("mode", ["continuous", "capture"])
def test_next_stages_recording_and_resume_plays_it_once(tmp_path, mode):
    AppConfig(live_mode=mode, osc_enabled=False, system_location_enabled=False,
              event_instruments={'event_1':'none','event_2':'none','event_3':'none','background':'birdsong'}).save(tmp_path/'config.json')
    app = create_app(tmp_path, auto_capture=False)
    svc = app.state.service
    svc.birdsong = SimpleNamespace(location_count=3)
    fetched, played = [], []
    async def fetch(client, index):
        fetched.append(index)
        return GaiaEvent('archive', str(index), 'birdsong', 1,
                         traits={'scientific_name':'Geococcyx californianus'})
    async def play(event):
        played.append(event.event_id)
    svc._fetch_recording = fetch
    svc._play_live_event = play
    client = TestClient(app)
    for index in (0,1):
        response = client.post('/api/recordings/next-image')
        assert response.status_code == 200
        assert response.json()['event']['event_id'] == str(index)
        assert not svc.playback.enabled
        assert not svc._emitted_cues
        assert not played
    assert fetched == [0,1]
    assert asyncio.run(svc.status())['cues']['latest_background_event']['event_id'] == '1'
    asyncio.run(svc.play_next_ambient_layers())
    assert fetched == [0,1]
    assert played == ['1']
    asyncio.run(svc.play_next_ambient_layers())
    assert fetched == [0,1,2]
    assert played == ['1','2']


def test_next_rejects_nonrecorded_background(tmp_path):
    AppConfig(live_mode='continuous', osc_enabled=False,
              event_instruments={'event_1':'none','event_2':'none','event_3':'none','background':'ocean_swell'}).save(tmp_path/'config.json')
    response = TestClient(create_app(tmp_path, auto_capture=False)).post('/api/recordings/next-image')
    assert response.status_code == 422
    assert 'animal recording background' in response.json()['detail']


@pytest.mark.parametrize("mode", ["continuous", "capture"])
def test_next_with_play_emits_the_selected_recording_once(tmp_path, mode):
    config_path = tmp_path / "config.json"
    AppConfig(live_mode=mode, osc_enabled=False, system_location_enabled=False,
              canine_calls_enabled=True, event_instruments={
                  "event_1": "none", "event_2": "none", "event_3": "none", "background": "canine_calls",
              }).save(config_path)
    app = create_app(tmp_path, auto_capture=False)
    with TestClient(app) as client:
        after = 0
        for expected_cursor in (1, 2):
            response = client.post("/api/recordings/next-image?play=true")
            assert response.status_code == 200, response.text
            event = response.json()["event"]
            cues = client.get("/api/cues", params={"after": after}).json()["cues"]
            cue, = cues
            assert cue["event"] == event
            assert cue["recording_rotation"]
            assert app.state.service._ambient_cursors["canine_calls"] == expected_cursor
            assert client.get("/api/status").json()["live"]["running"]
            after = cue["sequence"]
        assert AppConfig.load(config_path).live_mode == "continuous"
