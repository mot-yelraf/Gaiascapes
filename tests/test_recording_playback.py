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
  performance, console,
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
  assert.equal(first.volume, .75);
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
  assert.ok(first.volume > 0);
  assert.ok(!first.paused);
  now += 4000; fade();
  assert.equal(first.paused, true);
  assert.equal(players[1].volume, .75);
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
