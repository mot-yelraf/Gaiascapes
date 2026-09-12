"""Verify optional speech rendering and saved announcement settings.

Fake subprocesses provide WAV output without requiring eSpeak NG, an audio
device, or access to the installed runtime during automated tests.
"""

import io
from pathlib import Path
import subprocess
import wave

from fastapi.testclient import TestClient
import pytest

from gaiascapes_host import announcements
from gaiascapes_host.announcements import ANNOUNCEMENT_VOICES, AnnouncementRenderer, recording_announcement
from gaiascapes_host.app import create_app
from gaiascapes_host.config import AppConfig


@pytest.fixture(autouse=True)
def isolate_native_backend(monkeypatch):
    monkeypatch.setattr(announcements, "say_quark_paths", lambda: None)
    monkeypatch.setattr("gaiascapes_host.app.say_quark_paths", lambda: None)


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b'\0\0' * 2205)
    return stream.getvalue()


@pytest.mark.parametrize('place', ['35.1, -106.6', '35.1° N, 106.6° W',
                                   'lat: 35.1; lon: -106.6', 'Unknown location', ''])
def test_coordinates_are_not_announced(place):
    assert recording_announcement({'kind': 'birdsong', 'traits': {
        'title': 'Greater Roadrunner · song', 'place': place,
    }}) == 'Greater Roadrunner'


def test_names_from_recording_providers():
    assert recording_announcement({'kind': 'birdsong', 'traits': {
        'title': 'Acanthis flammea - Common Redpoll XC552770.mp3', 'place': 'Churchill, Canada',
    }}) == 'Common Redpoll. Churchill, Canada'
    assert recording_announcement({'kind': 'frog_calls', 'traits': {
        'scientific_name': 'Rana temporaria', 'place': 'Wales',
    }}) == 'Rana temporaria. Wales'
    assert recording_announcement({'kind': 'whale_song', 'traits': {
        'title': 'Humpback whale song', 'place': 'Hawaii',
    }}) == 'Humpback whale. Hawaii'
    assert recording_announcement({'kind': 'dolphin_calls', 'traits': {
        'title': 'Bottlenose dolphin whistles and clicks',
    }}) == 'Bottlenose dolphin'
    assert recording_announcement({'kind': 'earthquake'}) == ''
    assert recording_announcement({'kind': 'birdsong', 'traits': {
        'title': 'Redpoll', 'place': 'Ness',
    }}) == 'Redpoll. Ness'


def test_render_is_bounded_cached_and_uses_stdin(tmp_path, monkeypatch):
    monkeypatch.setattr(announcements, 'espeak_executable', lambda: '/fake/espeak-ng')
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[args.index('-w') + 1]).write_bytes(wav_bytes())
        return subprocess.CompletedProcess(args, 0, b'', b'')

    monkeypatch.setattr(announcements.subprocess, 'run', run)
    renderer = AnnouncementRenderer(tmp_path)
    text = 'Greater roadrunner. New Mexico; $(not-a-command)'
    assert renderer.render(text, 'uk') == wav_bytes()
    assert renderer.render(text, 'uk') == wav_bytes()
    assert len(calls) == 1
    for variant, suffix in [('male', '+m2'), ('female', '+f2')]:
        renderer.render(text, 'uk', variant)
        renderer.render(text, 'uk', variant)
        args = calls[-1][0]
        assert args[args.index('-v') + 1] == 'uk' + suffix
    assert len(calls) == 3
    args, options = calls[0]
    assert text not in args
    assert options['input'] == text.encode('utf-8')
    assert options['timeout'] == 15
    assert args[-1] == '--stdin'
    assert not list((tmp_path / 'announcements').iterdir())
    with pytest.raises(ValueError):
        renderer.render(text, '../invalid')
    with pytest.raises(ValueError):
        renderer.render('x' * 401, 'en-us')
    for index in range(33):
        renderer.render(f'Bird {index}', 'en-us')
    assert len(renderer._cache) == 32


def test_missing_engine_and_timeouts_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(announcements, 'espeak_executable', lambda: None)
    renderer = AnnouncementRenderer(tmp_path)
    with pytest.raises(RuntimeError, match='Install eSpeak NG'):
        renderer.render('Bird', 'en-us')
    monkeypatch.setattr(announcements, 'espeak_executable', lambda: '/fake/espeak-ng')

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired('espeak-ng', 15)

    monkeypatch.setattr(announcements.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='could not render'):
        renderer.render('Bird', 'en-us')
    assert not list((tmp_path / 'announcements').iterdir())


@pytest.mark.parametrize('changes', [dict(announcement_synthesizer='invalid'), dict(announcement_voice='invalid'), dict(announcement_variant='invalid'),
    dict(announcements_enabled='yes'), dict(announcement_volume=float('nan')),
    dict(announcement_volume=1.1)])
def test_invalid_settings_are_rejected(changes):
    with pytest.raises((TypeError, ValueError)):
        AppConfig(**changes).validate()


def test_settings_persist_and_speech_route_uses_retained_cues(tmp_path, monkeypatch):
    monkeypatch.setattr('gaiascapes_host.app.espeak_executable', lambda: '/fake/espeak-ng')
    spoken = []
    def render(self, text, voice, variant, synthesizer):
        spoken.append((text, voice, variant, synthesizer))
        return wav_bytes()
    monkeypatch.setattr(AnnouncementRenderer, 'render', render)
    app = create_app(tmp_path, auto_capture=False)
    client = TestClient(app)
    assert client.get('/api/announcements/1').status_code == 409
    response = client.put('/api/settings/audio', json={
        'announcements_enabled': True, 'announcement_voice': 'pt-br', 'announcement_variant': 'female', 'announcement_volume': .4, 'announcement_synthesizer': 'espeak-ng',
    })
    assert response.status_code == 200
    saved = AppConfig.load(tmp_path / 'config.json')
    assert saved.announcements_enabled and saved.announcement_voice == 'pt-br'
    assert saved.announcement_volume == .4
    assert saved.announcement_variant == "female"
    assert saved.announcement_synthesizer == "espeak-ng"
    assert saved.http_port == 8768 and saved.osc_port == 57130
    assert client.get('/api/announcements/1').status_code == 404
    app.state.service._emitted_cues.append({'sequence': 1, 'event': {
        'kind': 'birdsong', 'traits': {'title': 'Greater Roadrunner · song', 'place': 'New Mexico'},
    }})
    response = client.get('/api/announcements/1')
    assert response.status_code == 200 and response.content == wav_bytes()
    assert spoken == [('Greater Roadrunner. New Mexico', 'pt-br', 'female', 'espeak-ng')]
    assert response.headers['content-type'] == 'audio/wav'
    assert response.headers['cache-control'] == 'no-store'
    html = client.get('/').text
    assert html.index('id="listenButton"') < html.index('id="displayUnits"') < html.index('id="announcementTile"')
    assert html.index('id="backgroundSourcesHeading"') < html.index('id="announcementsEnabled"') < html.index('id="eventSourcesHeading"')
    assert html.count('id="announcementsEnabled"') == 1
    assert all(f'value="{voice}"' in html for voice in ANNOUNCEMENT_VOICES)
    monkeypatch.setattr('gaiascapes_host.app.espeak_executable', lambda: None)
    assert client.put('/api/settings/audio', json={'announcements_enabled': True}).status_code == 503
    assert client.put('/api/settings/audio', json={'announcements_enabled': False}).status_code == 200


def test_browser_cancels_stale_speech_and_respects_disable():
    from test_browser_recovery import run_node
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const status={textContent:''},requests=[],players=[];
const tile={dataset:{enabled:'true',voice:'en-us',volume:'0.7'}};
const scope=vm.createContext({document:{getElementById:id=>id==='announcementTile'?tile:status},
 AbortController,URL:{createObjectURL:()=> 'blob:speech',revokeObjectURL(){}},setTimeout,clearTimeout,
 fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),
 recordingNormalizer:{resume:async()=>{},prepare:async()=>{},createPlayer:()=>{
  const p={played:0,paused:0,pause(){this.paused++},play:async()=>{p.played++},
   removeAttribute(){},releaseNormalization(){},setRecordingOutputGain(value){this.gain=value},
   addEventListener(name,fn){this[name]=fn}};players.push(p);return p;
 }}});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),scope);
const api=scope.recordingAnnouncements;
const respond=request=>request.resolve({ok:true,blob:async()=>({})});
(async()=>{
 const old=api.play({sequence:1});
 const next=api.play({sequence:2});
 assert.equal(requests[0].options.signal.aborted,true);
 respond(requests[1]);
 await new Promise(resolve=>setImmediate(resolve));
 let finished=false;next.then(()=>{finished=true});
 assert.equal(finished,false);
 players[0].ended();await next;
 respond(requests[0]);await old;
 assert.equal(players.length,1);assert.equal(players[0].played,1);
 assert.ok(Math.abs(players[0].gain-.7**2*.75)<.00001);
 await api.play({sequence:2});assert.equal(requests.length,2);
 api.stop();assert.ok(players[0].paused>0);
 api.configure({announcements_enabled:false,announcement_volume:1});
 await api.play({sequence:3});assert.equal(requests.length,2);
 api.configure({announcements_enabled:true,announcement_volume:1});
 const failure=api.play({sequence:4});
 requests[2].resolve({ok:false,json:async()=>({detail:'eSpeak NG missing'})});await failure;
 assert.match(status.textContent,/eSpeak NG missing/);
})().catch(e=>{console.error(e);process.exitCode=1});
''', 'announcements.js')


def test_recording_waits_for_speech_without_changing_disabled_playback():
    from test_browser_recovery import run_node
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const players=[],order=[];
let enabled=false,finishSpeech;
const scope=vm.createContext({document:{getElementById:()=>null,querySelectorAll:()=>[]},console,
 AbortController,performance:{now:()=>0},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},
 recordingAnnouncements:{enabled:()=>enabled,stop(){finishSpeech?.();finishSpeech=null},
  play:()=>new Promise(resolve=>{order.push('speech');finishSpeech=resolve})},
 recordingNormalizer:{resume:async()=>{},prepare:async()=>{},createPlayer:()=>{
  const p={duration:60,currentTime:0,recordingFade:1,play:async()=>order.push('animal'),
   pause(){this.paused=true},removeAttribute(){},releaseNormalization(){},addEventListener(){}};
  players.push(p);return p;
 }}});
vm.runInContext(source.slice(0,source.indexOf('\nlet mapProjection =')),scope);
scope.cue={sequence:1,duration:8,volume:1,event:{kind:'birdsong',traits:{media_url:'/bird.wav'}}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await vm.runInContext('playRecordingCue(cue)',scope);
 assert.deepEqual(order,['animal']);
 enabled=true;order.length=0;
 const announced=vm.runInContext('playRecordingCue({...cue,sequence:2})',scope);
 await flush();
 assert.equal(players[0].paused,true);
 assert.deepEqual(order,['speech']);
 assert.equal(players[1].startOffset,0);
 assert.ok(vm.runInContext('recordingPreviewUntil > Date.now()',scope));
 finishSpeech();await announced;
 assert.deepEqual(order,['speech','animal']);
 order.length=0;
 const cancelled=vm.runInContext('playRecordingCue({...cue,sequence:3})',scope);
 await flush();assert.deepEqual(order,['speech']);
 vm.runInContext('stopRecordingPlayback()',scope);
 await cancelled;await flush();
 assert.deepEqual(order,['speech']);
 assert.equal(players[2].paused,true);
 enabled=false;order.length=0;
 await vm.runInContext('playRecordingCue({...cue,sequence:4})',scope);
 assert.deepEqual(order,['animal']);
})().catch(e=>{console.error(e);process.exitCode=1});
''', 'app.js')
