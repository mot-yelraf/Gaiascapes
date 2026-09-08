"""Regression checks for browser audio while a recording is loading.

Run the actual player functions with a deferred Audio.play promise so preview
protection and cancellation can be checked without a browser or audio device.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_recording_map_ring_tracks_audio_time_and_duration():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the map animation")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/app.js"
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const elements = [];
let frame;
const audio = {duration: NaN, currentTime: 0, fullRecording: true, ended: false};
const activeRecordingAudio = new Set([audio]);
const context = vm.createContext({
  audio, activeRecordingAudio,
  byId: () => ({append() {}}),
  eventColors: () => ({primary: '#123456'}),
  projectCoordinates: () => ({x: 1, y: 2}),
  mapMarkerTitle: () => 'Whale song',
  updateMapBackgroundLocation() {},
  createSvgElement: (tag, attributes) => {
    const element = {tag, attributes, append() {}, remove() {this.removed = true;},
      style: {setProperty(name, value) {this[name] = value;}}};
    elements.push(element);
    return element;
  },
  requestAnimationFrame: callback => {frame = callback;},
  setTimeout: () => {throw new Error('Recording ring must use playback time');},
});
vm.runInContext(source.slice(source.indexOf('function animateMapEvent('),
  source.indexOf('\nfunction applyLiveMode(')), context);
vm.runInContext("animateMapEvent({kind: 'whale_song', traits: {}}, '', 'background', 24.5, audio)", context);
const [group, pulse] = elements;
assert.equal(pulse.style.visibility, 'hidden');
audio.duration = 120;
frame();
assert.equal(pulse.style['--map-pulse-duration'], '120s');
assert.equal(pulse.style.animationPlayState, 'paused');
audio.currentTime = 60;
frame();
assert.equal(pulse.style.animationDelay, '-60s');
frame(); // Buffering leaves the ring at the same point.
assert.equal(pulse.style.animationDelay, '-60s');
assert.ok(!group.removed); // Still visible beyond the scheduled 24.5-second cue.
audio.currentTime = 119;
frame();
assert.equal(pulse.style.animationDelay, '-119s');
audio.ended = true;
frame();
assert.equal(group.removed, true);
audio.ended = false;
audio.fullRecording = false;
audio.currentTime = 4;
vm.runInContext("animateMapEvent({traits: {}}, '', 'background', 8, audio)", context);
const previewGroup = elements[4], previewPulse = elements[5];
assert.equal(previewPulse.style['--map-pulse-duration'], '8s');
assert.equal(previewPulse.style.animationDelay, '-4s');
activeRecordingAudio.delete(audio);
frame();
assert.equal(previewGroup.removed, true);
'''
    result = subprocess.run([node, "-e", script, str(source)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["birdsong", "frog_calls", "whale_song", "dolphin_calls"])
def test_recording_preview_is_protected_and_cancellable_while_loading(kind):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the browser player")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/app.js"
    script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const kind = process.argv[2];
let finishLoading;
let audio;
const context = vm.createContext({
  document: {getElementById: () => null},
  performance, console, AbortController,
  recordingNormalizer: {resume: async () => {}, prepare: async () => {}},
  setInterval: () => 1, clearInterval: () => {},
  setTimeout: () => 1, clearTimeout: () => {},
  Audio: class {
    constructor() { audio = this; this.paused = false; }
    play() { return new Promise(resolve => { finishLoading = resolve; }); }
    pause() { this.paused = true; }
    removeAttribute(name) { this.removedAttribute = name; }
  },
});
vm.runInContext(source.slice(0, source.indexOf("\nlet mapProjection =")), context);
context.cue = {duration: 8, volume: .4, event: {kind, traits: {media_url: "/test.wav"}}};
(async () => {
  const pending = vm.runInContext("playRecordingCue(cue)", context);
  assert.equal(vm.runInContext("recordingKind", context), kind);
  assert.ok(vm.runInContext("recordingPreviewUntil > Date.now()", context));
  vm.runInContext("applyRecordingVolume(0)", context);
  assert.equal(audio.recordingVolume, 0);
  assert.equal(audio.volume, 0);
  vm.runInContext("applyRecordingVolume(.2)", context);
  assert.equal(audio.recordingVolume, .2);
  assert.equal(audio.volume, 0); // Remain silent until prepared and faded in.
  await new Promise(resolve => setImmediate(resolve));
  vm.runInContext("stopRecordingPlayback()", context);
  finishLoading();
  await pending;
  assert.equal(audio.paused, true);
  assert.equal(audio.removedAttribute, "src");
  assert.equal(vm.runInContext("recordingAudio", context), null);
  assert.equal(vm.runInContext("activeRecordingAudio.size", context), 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(
        [node, "-e", script, str(source), kind],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_request_reports_server_failures_without_json_parse_errors():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise browser requests")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/app.js"
    script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const context = vm.createContext({fetch: async () => context.response});
vm.runInContext(source.slice(source.indexOf("async function request("), source.indexOf("\nfunction when(")), context);
(async () => {
  context.response = {ok: false, status: 500, json: async () => {
    throw new SyntaxError("The string did not match the expected pattern.");
  }};
  await assert.rejects(vm.runInContext('request("/api/instruments/preview")', context), /HTTP 500/);
  context.response = {ok: false, status: 503, json: async () => ({detail: "No frog recordings in this region"})};
  await assert.rejects(vm.runInContext('request("/api/instruments/preview")', context), /No frog recordings in this region/);
  context.response = {ok: true, status: 200, json: async () => ({played: true})};
  assert.equal((await vm.runInContext('request("/api/instruments/preview")', context)).played, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_background_strip_shows_recording_lookup_failure_and_loading():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the status strip")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/app.js"
    script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const context = vm.createContext({
  byId: () => ({value: "frog_calls"}),
  updateBackgroundSoundsTitle: () => {},
  updateSoundLocation: (location) => {context.location = location;},
  updateBackgroundCharacteristics: (event, text) => {context.event = event; context.text = text;},
  instrumentLabel: () => "Frog Calls",
});
vm.runInContext(source.slice(source.indexOf("function updateBackgroundStatus("), source.indexOf("\nfunction eventKindLabel(")), context);
context.previous = {kind: "birdsong", traits: {place: "Old bird location"}};
vm.runInContext('updateBackgroundStatus(previous, {frog_calls: {state: "unavailable", error: "No frog recordings in Test Wetland"}})', context);
assert.equal(context.text, "No frog recordings in Test Wetland");
assert.equal(context.location, null);
vm.runInContext('updateBackgroundStatus(previous, {frog_calls: {state: "loading", error: ""}})', context);
assert.match(context.text, /Looking for Frog Calls recordings/);
context.frog = {kind: "frog_calls", latitude: 1, longitude: 2, traits: {place: "New wetland"}};
vm.runInContext('updateBackgroundStatus(frog, {frog_calls: {state: "ready", error: ""}})', context);
assert.equal(context.event, context.frog);
assert.equal(context.location.name, "New wetland");
'''
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('kind', ['birdsong', 'frog_calls', 'whale_song', 'dolphin_calls'])
@pytest.mark.parametrize('duration', [1, 74])
def test_recording_advances_only_at_its_audio_transition(kind, duration):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is needed to exercise the browser player')
    source = Path(__file__).parents[1] / 'src/gaiascapes_host/static/app.js'
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const duration = Number(process.argv[3]);
const players = [], requests = [];
const countdowns = Array.from({length: 2}, () => ({
  dataset: {mediaUrl: '/test.wav'}, setAttribute() {},
}));
let now = 0, fade;
const context = vm.createContext({
  document: {getElementById: () => null, querySelectorAll: () => countdowns}, console,
  AbortController,
  recordingNormalizer: {resume: async () => {}, prepare: async () => {}},
  performance: {now: () => now},
  setInterval: fn => { fade = fn; return 1; }, clearInterval: () => {},
  setTimeout: () => 1, clearTimeout: () => {},
  request: async (url, options) => { requests.push(JSON.parse(options.body)); },
  Audio: class {
    constructor() {
      this.duration = duration; this.currentTime = 0; this.ended = false;
      this.listeners = {}; players.push(this);
    }
    async play() {}
    pause() { this.paused = true; }
    removeAttribute() {}
    addEventListener(name, fn) { this.listeners[name] = fn; }
  },
});
vm.runInContext(source.slice(0, source.indexOf('\nlet mapProjection =')), context);
context.cue = {sequence: 42, recording_rotation: true, duration: 24.5, volume: 1,
  event: {kind: process.argv[2], traits: {media_url: '/test.wav'}}};
(async () => {
  await vm.runInContext('playRecordingCue(cue)', context);
  const first = players[0];
  assert.equal(first.loop, false);
  vm.runInContext('updateRecordingCountdown()', context);
  for (const countdown of countdowns) {
    assert.equal(countdown.hidden, false);
    assert.equal(countdown.textContent, duration === 74 ? '−1:14' : '−0:01');
  }
  first.currentTime = .6;
  vm.runInContext('updateRecordingCountdown()', context);
  assert.equal(countdowns[0].textContent, duration === 74 ? '−1:14' : '−0:01');
  first.duration = NaN;
  vm.runInContext('updateRecordingCountdown()', context);
  assert.equal(countdowns[0].hidden, true);
  first.duration = duration;
  now = Math.min(3000, duration * 100); fade();
  assert.equal(first.recordingOutputGain, .75);
  vm.runInContext('applyRecordingVolume(0)', context);
  assert.equal(first.recordingOutputGain, 0);
  assert.ok(!first.paused);
  vm.runInContext('applyRecordingVolume(.2)', context);
  assert.ok(Math.abs(first.recordingOutputGain - .03) < 1e-9);
  vm.runInContext('applyRecordingVolume(1)', context);
  first.currentTime = duration === 74 ? 23 : .5;
  await first.listeners.timeupdate();
  assert.equal(requests.length, 0);
  const overlap = Math.min(3, duration * .1);
  first.currentTime = duration - overlap / 2;
  await first.listeners.timeupdate();
  await first.listeners.timeupdate();
  assert.deepEqual(requests, [{sequence: 42}]);
  await vm.runInContext('playRecordingCue({...cue, sequence: 43})', context);
  now += overlap * 250; fade();
  assert.ok(first.recordingOutputGain > 0);
  assert.ok(!first.paused);
  vm.runInContext('applyRecordingVolume(0)', context);
  assert.equal(first.recordingOutputGain, 0);
  assert.equal(players[1].recordingOutputGain, 0);
  now += 10; fade(); // Crossfade must not undo a saved mute.
  assert.equal(first.recordingOutputGain, 0);
  assert.equal(players[1].recordingOutputGain, 0);
  vm.runInContext('applyRecordingVolume(.4)', context);
  assert.ok(first.recordingOutputGain > 0);
  assert.ok(players[1].recordingOutputGain > 0);
  vm.runInContext('applyRecordingVolume(1)', context);
  now += 4000; fade();
  assert.equal(first.paused, true);
  assert.equal(players[1].recordingOutputGain, .75);
  players[1].currentTime = duration === 74 ? 15 : .5;
  vm.runInContext('updateRecordingCountdown()', context);
  assert.equal(countdowns[0].textContent, duration === 74 ? '−0:59' : '−0:01');
  countdowns[0].dataset.mediaUrl = '/different.wav';
  vm.runInContext('updateRecordingCountdown()', context);
  assert.equal(countdowns[0].hidden, true);
  assert.equal(countdowns[1].hidden, false);
  vm.runInContext('stopRecordingPlayback(); updateRecordingCountdown()', context);
  assert.equal(countdowns[1].hidden, true);
  assert.equal(countdowns[1].textContent, '');
  await vm.runInContext('playRecordingCue({...cue, duration: 8})', context);
  vm.runInContext('updateRecordingCountdown()', context);
  assert.equal(countdowns[1].hidden, true);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, '-e', script, str(source), kind, str(duration)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_recording_normalization_gain_and_audio_graph():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise recording normalization")
    source = Path(__file__).parents[1] / "src/gaiascapes_host/static/recording-audio.js"
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function buffer(amplitude, silence = 0, stereo = false) {
  const samples = Float32Array.from({length: 4000 + silence}, (_, i) =>
    i < silence ? 0 : amplitude * Math.sin(2 * Math.PI * i / 40));
  return {length: samples.length, sampleRate: 1000, numberOfChannels: stereo ? 2 : 1,
    getChannelData: () => samples};
}
const nodes = [];
function node() {
  const result = {connect(to) {this.to = to;}, disconnect() {this.disconnected = true;},
    gain: {}, threshold: {}, knee: {}, ratio: {}, attack: {}, release: {}};
  nodes.push(result);
  return result;
}
let fetches = 0, fail = false;
const context = vm.createContext({
  window: {AudioContext: class {
    constructor() {this.state = 'running'; this.destination = {};}
    async resume() {}
    createDynamicsCompressor() {throw new Error("Automatic makeup gain must not amplify recordings");}
    createWaveShaper() {return node();}
    createGain() {return node();}
    createMediaElementSource() {return node();}
    async decodeAudioData() {return buffer(.8);}
  }},
  fetch: async () => {fetches++; return {ok: !fail, status: 500, arrayBuffer: async () => new ArrayBuffer(0)};},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const normalizer = vm.runInContext('recordingNormalizer', context);
const gain = normalizer.measureGain;
const loud = gain(buffer(.8)), quiet = gain(buffer(.1));
assert.ok(Math.abs(loud * .8 - quiet * .1) < 1e-6);
assert.ok(loud < 1);
assert.equal(gain(buffer(0)), 1);
assert.equal(gain(buffer(.001)), 1); // Do not amplify near-silent noise.
assert.equal(gain(buffer(.01)), 1); // Quiet recordings must never be boosted.
assert.ok(Math.abs(loud * .8 / Math.sqrt(2) - 10 ** (-30 / 20)) < 1e-6);
for (const amplitude of [.001, .01, .03, .1, .5, 1]) {
  for (const silence of [0, 8000]) {
    const level = gain(buffer(amplitude, silence));
    assert.ok(level > 0 && level <= 1);
  }
}
assert.ok(Math.abs(gain(buffer(.8, 8000)) - loud) < 1e-6);
assert.ok(Math.abs(gain(buffer(.8, 0, true)) - loud) < 1e-6);
const transient = buffer(.02);
transient.getChannelData()[2000] = 1;
assert.ok(gain(transient) <= .85);
const invalid = buffer(.2); invalid.getChannelData()[0] = NaN;
assert.throws(() => gain(invalid), /invalid audio/);
(async () => {
  await normalizer.resume();
  const audio = {};
  await normalizer.prepare(audio, '/a.wav', new AbortController().signal);
  assert.equal(fetches, 1);
  assert.equal(nodes[2].gain.value, loud);
  assert.equal(nodes[1].to, nodes[2]);
  assert.equal(nodes[2].to, nodes[3]);
  assert.equal(nodes[3].to, nodes[0]);
  assert.equal(audio.volume, 1);
  assert.equal(nodes[3].gain.value, 0); // Nothing audible until the player fades in.
  // Exercise the real slider/fade function against the real gain graph.
  vm.runInContext(fs.readFileSync(process.argv[1].replace('recording-audio.js', 'app.js'), 'utf8')
    .split('function setRecordingFade(audio, fraction) {')[1]
    .split('function applyRecordingVolume(')[0]
    .replace(/^/, 'function setRecordingFade(audio, fraction) {'), context);
  const fade = vm.runInContext('setRecordingFade', context);
  for (const [slider, expected] of [[0, 0], [.1, .0075], [.5, .1875], [.9, .6075], [1, .75]]) {
    audio.recordingVolume = slider;
    fade(audio, 1);
    assert.ok(Math.abs(nodes[3].gain.value - expected) < 1e-12);
    assert.equal(audio.volume, 1); // Attenuation comes entirely from Web Audio.
    fade(audio, .5);
    assert.ok(Math.abs(nodes[3].gain.value - expected / 2) < 1e-12);
  }
  assert.ok(Math.max(...nodes[0].curve) <= .951);
  for (let i = 0; i < nodes[0].curve.length; i++) {
    assert.ok(Math.abs(nodes[0].curve[i]) <= Math.abs(i / 2048 - 1) + 1e-7);
  }
  audio.releaseNormalization();
  assert.ok(nodes[1].disconnected && nodes[2].disconnected && nodes[3].disconnected);
  await normalizer.prepare({}, '/a.wav', new AbortController().signal);
  assert.equal(fetches, 1);
  const cancelled = new AbortController(); cancelled.abort();
  await assert.rejects(normalizer.prepare({}, '/a.wav', cancelled.signal), {name: 'AbortError'});
  fail = true;
  await assert.rejects(normalizer.prepare({}, '/bad.wav', new AbortController().signal), /HTTP 500/);
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", script, str(source)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
