"""Tests for bounded renderer audio relay and browser-facing availability.

Synthetic loopback renderer packets exercise startup, fanout, backpressure,
malformed input, and shutdown without using the installation or audio devices.
"""

import asyncio
import struct

import pytest
from fastapi.testclient import TestClient

from gaiascapes_host.app import create_app
from gaiascapes_host.audio_stream import (
    FRAMES, QUEUE_BLOCKS, RendererAudioRelay, decode_audio_packet,
)
from gaiascapes_host.config import AppConfig
from gaiascapes_host.osc import encode_message


def audio_packet(token, sequence=0, samples=None):
    return encode_message('/gaia/audio', (
        token, sequence, 48000, *(samples or [0.25, -0.25] * FRAMES),
    ))


def test_audio_wire_format_and_validation():
    packet = audio_packet('session', 7)
    block = decode_audio_packet(packet, 'session')
    assert struct.unpack_from('<4sIIff', block) == (b'GAIA', 7, 48000, 0.25, -0.25)
    assert len(block) == 12 + FRAMES * 8
    for invalid in [b'', packet[:-1], audio_packet('stale'),
                    audio_packet('session', samples=[float('nan')] * (FRAMES * 2))]:
        with pytest.raises(ValueError):
            decode_audio_packet(invalid, 'session')


def test_relay_fanout_backpressure_and_last_listener_cleanup():
    async def run():
        class Renderer(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport
                self.stopped = asyncio.Event()

            def datagram_received(self, packet, addr):
                if packet.startswith(b'/gaia/audio/stop\0'):
                    self.stopped.set()
                elif packet.startswith(b'/gaia/audio/start\0'):
                    token = packet[24:].split(b'\0', 1)[0].decode()
                    self.transport.sendto(audio_packet(token), addr)

        loop = asyncio.get_running_loop()
        transport, renderer = await loop.create_datagram_endpoint(
            Renderer, local_addr=('127.0.0.1', 0))
        relay = RendererAudioRelay(AppConfig(osc_port=transport.get_extra_info('sockname')[1]))
        try:
            first_queue, first = await relay.subscribe()
            second_task = asyncio.create_task(relay.subscribe())
            await asyncio.sleep(0)
            relay.datagram_received(audio_packet(relay.token, 1), ('127.0.0.1', 123))
            second_queue, second = await second_task
            assert first[:4] == second[:4] == b'GAIA'
            for sequence in range(2, QUEUE_BLOCKS + 20):
                relay.datagram_received(audio_packet(relay.token, sequence), ('127.0.0.1', 123))
            assert first_queue.qsize() == second_queue.qsize() == QUEUE_BLOCKS
            assert first_queue.get_nowait() == second_queue.get_nowait()
            size = second_queue.qsize()
            relay.datagram_received(audio_packet('wrong', 1000), ('127.0.0.1', 123))
            relay.datagram_received(audio_packet(relay.token, 1000), ('192.0.2.1', 123))
            relay.datagram_received(audio_packet(relay.token, 1), ('127.0.0.1', 123))
            assert second_queue.qsize() == size
            await relay.unsubscribe(first_queue)
            assert relay.transport is not None
            await relay.unsubscribe(second_queue)
            await asyncio.wait_for(renderer.stopped.wait(), 1)
            assert relay.transport is None and relay.heartbeat is None
        finally:
            await relay.close()
            transport.close()
    asyncio.run(run())


def test_unavailable_renderer_cleans_up_and_keeps_app_working(tmp_path, monkeypatch):
    monkeypatch.setattr('gaiascapes_host.audio_stream.AUDIO_TIMEOUT', 0.02)
    app = create_app(tmp_path, auto_capture=False)
    with TestClient(app) as client:
        # An unbound ephemeral destination cannot reach an installed renderer.
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            app.state.config.osc_port = sock.getsockname()[1]
            response = client.get('/api/audio/stream')
        assert response.status_code == 503
        assert 'No host audio received' in response.json()['detail']
        assert app.state.audio_relay.transport is None
        assert not app.state.audio_relay.listeners
        app.state.config.osc_enabled = False
        assert client.get('/api/audio/status').json()['enabled'] is False
        assert client.get('/api/audio/stream').status_code == 503
        assert client.get('/healthz').status_code == 200
        assert 'Listen on this device' in client.get('/').text


def test_cancelled_start_and_shutdown_release_resources(monkeypatch):
    async def run():
        relay = RendererAudioRelay(AppConfig(osc_enabled=False))
        with pytest.raises(RuntimeError):
            await relay.subscribe()
        relay.config.osc_enabled = True
        relay.config.osc_host = '192.0.2.1'
        with pytest.raises(RuntimeError):
            await relay.subscribe()
        relay.config.osc_host = '127.0.0.1'
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink:
            sink.bind(('127.0.0.1', 0))
            relay.config.osc_port = sink.getsockname()[1]
            pending = asyncio.create_task(relay.subscribe())
            while not relay.listeners:
                await asyncio.sleep(0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert not relay.listeners and relay.transport is None
        await relay.close()
    asyncio.run(run())


def test_browser_pcm_framing_scheduling_and_mute():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed to exercise browser PCM playback')
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes=[];
class AudioContext {
  constructor() { this.currentTime=0; this.state='running'; this.destination={}; }
  async resume() {}
  async close() { this.state='closed'; }
  createBuffer(channels, frames, rate) {
    const data=Array.from({length:channels},()=>new Float32Array(frames));
    return {duration:frames/rate, getChannelData:i=>data[i]};
  }
  createBufferSource() {
    const source={connect(){},disconnect(){},start(time){this.time=time;},stop(){this.stopped=true;}};
    nodes.push(source); return source;
  }
}
const scope=vm.createContext({window:{AudioContext},AbortController,Uint8Array,DataView,setTimeout,clearTimeout});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),scope);
const Player=vm.runInContext('LiveAudioPlayer',scope);
function packet(sequence, value=.2) {
  const bytes=new Uint8Array(4108), view=new DataView(bytes.buffer);
  view.setUint32(0,0x47414941);view.setUint32(4,sequence,true);view.setUint32(8,48000,true);
  for(let i=0;i<1024;i++)view.setFloat32(12+i*4,i%2?-value:value,true);
  return bytes;
}
(async()=>{
  const player=new Player(()=>{});
  await player.unlock();
  player.nextTime=0;player.sequence=null;
  const bytes=packet(0);
  const controller=new AbortController();
  const fragments=[bytes.slice(0,9),bytes.slice(9,100),bytes.slice(100)];
  let cancelled=false;
  await assert.rejects(player.read({
    async read(){return fragments.length?{value:fragments.shift(),done:false}:{done:true};},
    async cancel(){cancelled=true;}
  },controller),/disconnected/);
  assert.ok(cancelled);
  assert.equal(nodes.length,1);
  assert.equal(nodes[0].time,.15);
  assert.ok(Math.abs(nodes[0].buffer.getChannelData(1)[0]+.2)<1e-6);
  player.schedule(new DataView(packet(0).buffer)); // A duplicate cannot play twice.
  assert.equal(nodes.length,1);
  player.schedule(new DataView(packet(2).buffer)); // Preserve a lost block's time.
  assert.ok(Math.abs(nodes[1].time-(.15+1024/48000))<1e-8);
  for(let i=3;i<2000;i++)player.schedule(new DataView(packet(i).buffer));
  assert.ok(player.sources.size<60); // Bound queued audio despite a stalled clock.
  player.context.currentTime=1;
  assert.throws(()=>player.schedule(new DataView(packet(2001,NaN).buffer)),/sample/);
  player.stop();
  assert.equal(player.sources.size,0);
  assert.equal(player.context,null);
  assert.ok(nodes.every(node=>node.stopped));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    source = Path(__file__).parents[1] / 'src/gaiascapes_host/static/live-audio.js'
    result = subprocess.run([node, '-e', script, str(source)], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_device_listening_requests_media_session_before_unlocking_audio():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed to exercise browser audio activation')
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const listen = source.slice(source.indexOf('async function listenOnDevice()'),
                            source.indexOf('listenButton.addEventListener("click"'));
(async () => {
  for (const supported of [true, false]) {
    let unlocked = 0, started = false, muted = false;
    const navigator = supported ? {audioSession: {type: 'auto'}} : {};
    function unlock() {
      if (supported) assert.equal(navigator.audioSession.type, 'playback');
      unlocked++;
      return Promise.resolve();
    }
    const scope = vm.createContext({
      navigator, listeningAttempt: 0, deviceListening: false, deviceMuted: true,
      listenButton: {setAttribute() {}},
      listenStatus: {classList: {remove() {}, add() {}}},
      recordingNormalizer: {resume: unlock},
      liveAudioPlayer: {unlock, async start() { started = true; }},
      async request(url) { return url.endsWith('status') ? {enabled: true} : {cues: []}; },
      RECORDED_BACKGROUNDS: [], muteDevice() { muted = true; },
    });
    vm.runInContext(listen, scope);
    const listening = vm.runInContext('listenOnDevice()', scope);
    assert.equal(unlocked, 2, 'Both contexts must unlock during the original tap');
    await listening;
    assert.equal(started, true);
    assert.equal(muted, false);
    assert.equal(scope.deviceListening, true);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    source = Path(__file__).parents[1] / 'src/gaiascapes_host/static/app.js'
    result = subprocess.run([node, '-e', script, str(source)], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr
