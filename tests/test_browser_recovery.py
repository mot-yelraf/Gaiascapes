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
vm.runInContext('let cuePollInFlight=false;let observedCueSequence=null;'+
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
