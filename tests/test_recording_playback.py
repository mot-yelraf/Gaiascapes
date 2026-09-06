"""Regression checks for browser audio while a recording is loading.

Run the actual player functions with a deferred Audio.play promise so preview
protection and cancellation can be checked without a browser or audio device.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("kind", ["birdsong", "frog_calls", "whale_song", "dolphin_calls"])
def test_recording_preview_is_protected_and_cancellable_while_loading(kind):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to exercise the browser player")
    source = Path(__file__).parents[1] / "src/gaia_scape_host/static/app.js"
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
    source = Path(__file__).parents[1] / "src/gaia_scape_host/static/app.js"
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
    source = Path(__file__).parents[1] / "src/gaia_scape_host/static/app.js"
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
