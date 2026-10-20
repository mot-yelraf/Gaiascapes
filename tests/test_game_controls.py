"""Verify game controls remain synchronized during playback and answer updates.

A small DOM harness exercises asynchronous clicks without starting a renderer.
"""

from test_browser_recovery import run_node


def test_playback_pending_state_and_cross_view_concealment():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const buttons=['play','pause','next'].map(action=>({disabled:false,attrs:{},handlers:{},dataset:{playbackAction:action},
 setAttribute(k,v){this.attrs[k]=v},addEventListener(k,v){this.handlers[k]=v}}));
const [playButton,pauseButton,nextButton]=buttons;
const status={textContent:''},details={};
const selectors=['background','event','earthquake','background','event','earthquake'].map((kind,i)=>{
 details[i]={hidden:false};
 return {inputs:[{value:'reveal',checked:true},{value:'hide',checked:false}],dataset:{statusVisibility:kind},handlers:{},
 querySelectorAll(){return this.inputs},
 addEventListener(k,v){this.handlers[k]=v},getAttribute(){return i},
 closest(){return {removeAttribute(){}}}};
});
let starts=0,stops=0,release;
const scope=vm.createContext({document:{
 getElementById:id=>id==='playbackControlStatus'?status:details[id],
 querySelectorAll:query=>query==='[data-playback-action]'?buttons:selectors},
 updateStatus:()=>{},
 startPlayback:async()=>{starts++;await new Promise(resolve=>release=resolve);scope.gaiascapesControls.setPlaying(true)},
 stopPlayback:async()=>{stops++;scope.gaiascapesControls.setPlaying(false)},
});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),scope);
(async()=>{
 scope.gaiascapesControls.setPlaying(false);
 assert.equal(pauseButton.attrs['aria-pressed'],'true');
 const click=playButton.handlers.click();
 assert.equal(playButton.disabled,true);
 await playButton.handlers.click();
 assert.equal(starts,1);
 scope.gaiascapesControls.setPlaying(false); // Polling cannot unlock pending operation.
 assert.equal(playButton.disabled,true);
 release();await click;
 assert.equal(playButton.disabled,false);
 assert.equal(playButton.attrs['aria-pressed'],'true');
 await pauseButton.handlers.click();assert.equal(stops,1);
 assert.equal(pauseButton.attrs['aria-pressed'],'true');
 selectors[0].handlers.change({target:{value:'hide'}});
 assert.equal(details[0].hidden,true);assert.equal(details[3].hidden,true);
 assert.equal(selectors[3].inputs[1].checked,true);assert.equal(selectors[3].inputs[0].checked,false);assert.equal(details[1].hidden,false);
 selectors[3].handlers.change({target:{value:'reveal'}});
 assert.equal(details[0].hidden,false);assert.equal(selectors[0].inputs[0].checked,true);assert.equal(selectors[0].inputs[1].checked,false);
})().catch(error=>{console.error(error);process.exitCode=1});
''', 'game-controls.js')
