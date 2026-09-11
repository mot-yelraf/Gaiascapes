"""Exercise browser recovery with deterministic network and timer failures.

The production JavaScript runs in Node with controlled transports, so tests
never connect to an installed server or alter playback settings.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


STATIC = Path(__file__).parents[1] / 'src/gaiascapes_host/static'


def run_node(script, filename):
    """Run a JavaScript recovery scenario against the production source."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for browser recovery tests')
    result = subprocess.run([node, '-e', script, str(STATIC / filename)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_hung_cue_request_times_out_and_polling_recovers():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
let calls=0, nextId=0;
const timers=new Map();
const scope=vm.createContext({AbortController,console:{warn(){}},
 setTimeout:(fn,ms)=>{const id=++nextId;timers.set(id,{fn,ms});return id},
 clearTimeout:id=>timers.delete(id),
 fetch:async(url,options)=>{
   calls++;
   if(calls===1) return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('aborted'))));
   return {ok:true,json:async()=>({cues:[],latest_sequence:0})};
 },
});
vm.runInContext('let cuePollInFlight=false;let cuePollController=null;let wakeRecoveryInFlight=false;let observedCueSequence=null;'+
 source.slice(source.indexOf('async function request('),source.indexOf('\nfunction when('))+
 source.slice(source.indexOf('async function updateEmittedCues()'),source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 const first=vm.runInContext('updateEmittedCues()',scope);
 await vm.runInContext('updateEmittedCues()',scope);
 assert.equal(calls,1);
 [...timers.values()].find(t=>t.ms===35000).fn();
 await first;
 assert.equal(vm.runInContext('cuePollInFlight',scope),false);
 assert.ok([...timers.values()].some(t=>t.ms===1000));
 await vm.runInContext('updateEmittedCues()',scope);
 assert.equal(calls,2);
 assert.equal(vm.runInContext('observedCueSequence',scope),0);
})().catch(e=>{console.error(e);process.exitCode=1});
''', 'app.js')


def test_live_audio_reconnects_after_failure_and_stall_but_respects_stop():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let calls=0,nextId=0;
const timers=new Map(),states=[];
const scope=vm.createContext({AbortController,Uint8Array,DataView,
 setTimeout:(fn,ms)=>{const id=++nextId;timers.set(id,{fn,ms});return id},
 clearTimeout:id=>timers.delete(id),
 fetch:async()=>{
   if(++calls===1) throw new Error('host restarting');
   return {ok:true,body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel:async()=>{}})}};
 },
});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';globalThis.Player=LiveAudioPlayer',scope);
const player=new scope.Player((state,detail)=>states.push(state));
player.context={state:'running',close:async()=>{}};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await assert.rejects(player.start(),/restarting/);
 assert.equal(states.at(-1),'reconnecting');
 assert.ok(player.context);
 const retry=[...timers.values()].find(t=>t.ms===1000).fn;
 retry();await flush();
 assert.equal(calls,2);assert.equal(states.at(-1),'listening');
 [...timers.values()].find(t=>t.ms===10000).fn();await flush();
 assert.equal(states.at(-1),'reconnecting');
 const stalledRetry=[...timers.values()].find(t=>t.ms===2000).fn;
 player.stop();stalledRetry();await flush();
 assert.equal(calls,2);assert.equal(player.context,null);
})().catch(e=>{console.error(e);process.exitCode=1});
''', 'live-audio.js')


def test_host_audio_start_failure_preserves_recordings():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
let played=0,muted=0;
const scope=vm.createContext({navigator:{},listeningAttempt:0,deviceListening:false,deviceMuted:true,
 listenButton:{setAttribute(){}},listenStatus:{classList:{remove(){},add(){}}},
 recordingNormalizer:{resume:async()=>{}},liveAudioPlayer:{unlock:async()=>{},start:async()=>{throw new Error('renderer offline')}},
 request:async url=>url.endsWith('status')?{enabled:true}:{cues:[{sequence:1,event:{kind:'birdsong'}}]},
 RECORDED_BACKGROUNDS:['birdsong'],lastPlayedRecordingSequence:null,
 playRecordingCue:async()=>{played++},muteDevice:()=>{muted++},
});
vm.runInContext(source.slice(source.indexOf('async function listenOnDevice()'),source.indexOf('listenButton.addEventListener("click"')),scope);
(async()=>{
 await vm.runInContext('listenOnDevice()',scope);
 assert.equal(played,1);assert.equal(muted,0);assert.equal(scope.deviceListening,true);
 assert.match(scope.listenStatus.textContent,/reconnecting/);
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_delayed_cues_skip_obsolete_recordings_and_expired_map_pulses():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
const played=[],animated=[];
const now=Date.now()/1000;
const cue=(sequence,kind,age)=>({sequence,event:{kind},emitted_at:now-age,duration:3.6});
const payload={latest_sequence:4,cues:[cue(1,'birdsong',60),cue(2,'lightning_flash',50),
 cue(3,'birdsong',1),cue(4,'lightning_flash',0)]};
const scope=vm.createContext({
 cuePollInFlight:false,cuePollController:null,wakeRecoveryInFlight:false,AbortController,
 observedCueSequence:0,lastPlayedRecordingSequence:null,
 RECORDED_BACKGROUNDS:['birdsong'],deviceMuted:false,deviceListening:false,localRecordingPlayback:true,
 request:async()=>payload,playRecordingCue:c=>{played.push(c.sequence);scope.lastPlayedRecordingSequence=c.sequence;},
 animateCapturedEvent:e=>animated.push(e.kind),cueRole:c=>c.event.kind==='birdsong'?'background':'event',
 updateBackgroundStatus(){},updateLastEventStatus(){},updateLastEarthquakeStatus(){},
 updateEvents:async()=>{},setTimeout(){},console,
});
vm.runInContext(source.slice(source.indexOf('async function updateEmittedCues()'),
 source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 await vm.runInContext('updateEmittedCues()',scope);
 assert.deepEqual(played,[3]);
 assert.deepEqual(animated,['birdsong','lightning_flash']);
 assert.equal(scope.observedCueSequence,4);
 await vm.runInContext('updateEmittedCues()',scope);
 assert.deepEqual(played,[3]); // A repeated response cannot restart a recording.
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_start_unlocks_recording_context_before_network_request():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8'),order=[];
let click;
const scope=vm.createContext({
 byId:id=>id==='startButton'?{addEventListener:(name,fn)=>{click=fn}}:
   {value:id==='backgroundInstrument'?'birdsong':'continuous'},
 deviceMuted:false,localRecordingPlayback:true,deviceListening:false,RECORDED_BACKGROUNDS:['birdsong'],
 recordingNormalizer:{resume:async()=>{order.push('resume')}},
 request:async()=>{order.push('request')},message(){},updateStatus:async()=>{},
});
vm.runInContext(source.slice(source.indexOf('byId("startButton").addEventListener'),
 source.indexOf('byId("stopButton").addEventListener')),scope);
(async()=>{
 const pending=click();
 assert.deepEqual(order,['resume']); // Unlock inside the original user gesture.
 await pending;
 assert.deepEqual(order,['resume','request']);
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_wake_resumes_once_preserves_recording_and_respects_mute():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
let release,resumes=0,streams=0,polls=0,status=0,history=0;
const controller=new AbortController();
const scope=vm.createContext({
 document:{hidden:false},wakeRecoveryInFlight:false,observedCueSequence:900,
 cuePollController:controller,deviceMuted:false,localRecordingPlayback:true,deviceListening:true,
 pendingRecordingAudio:null,recordingAudio:{ended:false,currentTime:40},lastPlayedRecordingSequence:42,
 recordingNormalizer:{recover:()=>{resumes++;return new Promise(resolve=>{release=resolve})}},
 liveAudioPlayer:{recover:async()=>{streams++}},message:()=>{throw new Error('Unexpected error')},
 updateEmittedCues:()=>{polls++},updateStatus:()=>{status++},updateEvents:()=>{history++},
});
vm.runInContext(source.slice(source.indexOf('async function recoverAfterWake()'),
 source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 const recovery=vm.runInContext('recoverAfterWake()',scope);
 assert.ok(controller.signal.aborted);
 assert.equal(scope.observedCueSequence,null);
 await vm.runInContext('recoverAfterWake()',scope); // Concurrent focus/pageshow/timer events coalesce.
 assert.equal(resumes,1);assert.equal(streams,1);assert.equal(polls,0);
 release();await recovery;
 assert.equal(scope.lastPlayedRecordingSequence,42);
 assert.equal(scope.recordingAudio.currentTime,40);
 assert.equal(polls,1);assert.equal(status,1);assert.equal(history,1);
 scope.deviceMuted=true;
 await vm.runInContext('recoverAfterWake()',scope);
 assert.equal(resumes,1);assert.equal(streams,1);assert.equal(polls,2);
 scope.document.hidden=true;
 await vm.runInContext('recoverAfterWake()',scope);
 assert.equal(polls,2);
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_wake_discards_pre_sleep_poll_response():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
let release,queries=[];
const scope=vm.createContext({
 AbortController,console,setTimeout(){},cuePollInFlight:false,cuePollController:null,
 wakeRecoveryInFlight:false,observedCueSequence:900,document:{hidden:false},deviceMuted:true,
 request:async path=>{queries.push(path);if(queries.length===1)return new Promise(r=>{release=r});
   return {cues:[],latest_sequence:12}},
 updateStatus(){},updateEvents(){},
});
vm.runInContext(source.slice(source.indexOf('async function updateEmittedCues()'),
 source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 const oldPoll=vm.runInContext('updateEmittedCues()',scope);
 await vm.runInContext('recoverAfterWake()',scope);
 release({cues:[{event:{kind:'birdsong'}}],latest_sequence:901});
 await oldPoll;
 assert.equal(scope.observedCueSequence,null); // Aborted response must not overwrite the reset cursor.
 await vm.runInContext('updateEmittedCues()',scope);
 assert.deepEqual(queries,['/api/cues?after=900','/api/cues']);
 assert.equal(scope.observedCueSequence,12); // A restarted host can have a lower sequence.
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_wake_audio_failure_does_not_prevent_ui_recovery():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8'),messages=[];
let polls=0;
const load=new AbortController();
const scope=vm.createContext({
 document:{hidden:false},wakeRecoveryInFlight:false,observedCueSequence:42,cuePollController:null,
 deviceMuted:false,localRecordingPlayback:true,deviceListening:false,
 pendingRecordingAudio:{},recordingLoadController:load,recordingAudio:null,lastPlayedRecordingSequence:42,
 recordingNormalizer:{recover:async()=>{throw new Error('Select Start to retry')}},
 message:text=>messages.push(text),updateEmittedCues:()=>{polls++},updateStatus(){},updateEvents(){},
});
vm.runInContext(source.slice(source.indexOf('async function recoverAfterWake()'),
 source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 await vm.runInContext('recoverAfterWake()',scope);
 assert.ok(load.signal.reason.recordingWake);
 assert.equal(scope.lastPlayedRecordingSequence,null);
 assert.equal(scope.wakeRecoveryInFlight,false);
 assert.equal(polls,1);assert.match(messages[0],/Select Start/);
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_wake_during_history_refresh_does_not_restore_old_cursor():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8');
let release;
const scope=vm.createContext({
 AbortController,console,setTimeout(){},cuePollInFlight:false,cuePollController:null,
 wakeRecoveryInFlight:false,observedCueSequence:900,document:{hidden:false},deviceMuted:true,
 RECORDED_BACKGROUNDS:[],request:async()=>({cues:[{event:{kind:'earthquake'}}],latest_sequence:901}),
 cueRole:()=> 'event',animateCapturedEvent(){},updateLastEventStatus(){},updateLastEarthquakeStatus(){},
 updateStatus(){},updateEvents:()=>new Promise(resolve=>{release=resolve}),
});
vm.runInContext(source.slice(source.indexOf('async function updateEmittedCues()'),
 source.indexOf('\nasync function updateEvents()')),scope);
(async()=>{
 const pending=vm.runInContext('updateEmittedCues()',scope);
 await new Promise(resolve=>setImmediate(resolve));
 const finishHistory=release;
 await vm.runInContext('recoverAfterWake()',scope);
 finishHistory();await pending;
 assert.equal(scope.observedCueSequence,null);
})().catch(e=>{console.error(e);process.exitCode=1});
''','app.js')


def test_display_sleep_timer_gap_and_visibility_trigger_recovery():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[1],'utf8'),events={};
let now=0,tick,recoveries=0;
const scope=vm.createContext({
 window:{addEventListener:(name,fn)=>{events[name]=fn}},
 document:{hidden:false,addEventListener:(name,fn)=>{events[name]=fn}},
 Date:{now:()=>now},setInterval:fn=>{tick=fn},recoverAfterWake:()=>{recoveries++},
});
vm.runInContext(source.slice(source.indexOf('window.addEventListener("pageshow"'),
 source.indexOf('byId("startButton").addEventListener')),scope);
now=5000;tick();assert.equal(recoveries,0);
now=65000;tick();assert.equal(recoveries,1);
now=70000;tick();assert.equal(recoveries,1);
events.focus();events.pageshow();events.visibilitychange();assert.equal(recoveries,4);
scope.document.hidden=true;events.visibilitychange();assert.equal(recoveries,4);
''','app.js')


def test_live_audio_wake_discards_buffers_and_respects_stop_during_resume():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const scope=vm.createContext({clearTimeout,setTimeout});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';globalThis.Player=LiveAudioPlayer',scope);
const player=new scope.Player(()=>{});
let release,starts=0,stops=0;
player.context={state:'suspended',resume:()=>new Promise(resolve=>{release=resolve}),
 suspend:async()=>{player.context.state='suspended'},close:async()=>{}};
player.wanted=true;
player.sources.add({stop(){stops++},disconnect(){}});
player.start=async()=>{starts++};
(async()=>{
 const first=player.recover();
 assert.equal(stops,1);assert.equal(player.sources.size,0);
 player.context.state='running';release();await first;assert.equal(starts,1);
 const second=player.recover();
 await new Promise(resolve=>setImmediate(resolve));
 player.stop();release();await second;
 assert.equal(starts,1);assert.equal(player.wanted,false);
})().catch(e=>{console.error(e);process.exitCode=1});
''','live-audio.js')


def test_recording_resume_timeout_is_bounded_and_retryable():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let clock,timeout;
const scope=vm.createContext({
 window:{AudioContext:class {
   constructor(){clock=this;this.state='suspended'}
   createWaveShaper(){return {connect(){}}}
   resume(){return new Promise(()=>{})}
 }},
 setTimeout:(fn,ms)=>{assert.equal(ms,5000);timeout=fn;return 1},clearTimeout(){},
});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8')+';globalThis.normalizer=recordingNormalizer',scope);
(async()=>{
 const pending=scope.normalizer.resume();timeout();
 await assert.rejects(pending,/select Start or Preview/);
 clock.resume=async()=>{clock.state='running'};
 await scope.normalizer.recover();
 assert.equal(clock.state,'running');
})().catch(e=>{console.error(e);process.exitCode=1});
''','recording-audio.js')
