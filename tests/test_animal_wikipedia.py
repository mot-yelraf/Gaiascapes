"""Check recording article selection and stale Wikipedia response handling.

The browser module runs with a controlled DOM and network, without contacting
Wikipedia or using an installed application's state.
"""

from test_browser_recovery import run_node


def test_animal_article_tracks_species_hemisphere_and_playback():
    run_node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();
function element(id) {
 if (!elements.has(id)) elements.set(id,{hidden:false,dataset:{},textContent:'',open:false,
   classList:{toggle(){}},setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]},
   addEventListener(k,fn){this["on"+k]=fn},closest(){return element('main')},
   showModal(){this.open=true},close(){this.open=false}});
 return elements.get(id);
}
const pending=[];
const scope=vm.createContext({document:{getElementById:element},AbortController,URLSearchParams,
 setTimeout,clearTimeout,fetch:(url,options)=>new Promise(resolve=>pending.push({url,resolve}))});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),scope);
const api=scope.animalWikipedia;
const event=(kind,title,longitude)=>({kind,longitude,traits:{title}});
assert.equal(api.subject(event('birdsong','Acanthis flammea - Common Redpoll XC552770.mp3',-93)),'Acanthis flammea');
assert.equal(api.subject({kind:'frog_calls',traits:{scientific_name:'Rana temporaria'}}),'Rana temporaria');
assert.equal(api.subject(event('whale_song','Blue and fin whale calls',-10)),'Cetacean vocalization');
assert.equal(api.subject(event('dolphin_calls','Indo-Pacific bottlenose dolphin whistle',110)),'Indo-Pacific bottlenose dolphin');
assert.equal(api.subject(event('dolphin_calls','Dolphin vocalizations',-10)),'Dolphin');
assert.equal(api.subject(event('earthquake','',10)),'');
const respond=(request,title,image='https://upload.wikimedia.org/example.jpg')=>request.resolve({ok:true,json:async()=>({query:{pages:[{
 title,extract:'Article text',thumbnail:{source:image},pageimage:'Example.jpg'}]}})});
(async()=>{
 const west=api.update(event('whale_song','Humpback whale song',-150));
 assert.equal(element('animalWikipedia').dataset.hemisphere,'west');
 const east=api.update(event('dolphin_calls','Dolphin vocalizations',30));
 respond(pending[1],'Dolphin');await east;
 respond(pending[0],'Humpback whale');await west;
 assert.equal(element('animalArticleTitle').textContent,'Dolphin');
 assert.equal(element('animalImage').hidden,false);
 assert.equal(element('animalImage').src,'https://upload.wikimedia.org/example.jpg');
 assert.equal(element('animalWikipedia').dataset.hemisphere,'east');
 element('animalImageButton').onclick();assert.equal(element('animalArticle').open,true);
 element('animalArticle').onclick({target:{closest:()=>null}});
 assert.equal(element('animalArticle').open,false);
 await api.update(event('dolphin_calls','Dolphin vocalizations',-20));
 assert.equal(pending.length,2);assert.equal(element('animalWikipedia').dataset.hemisphere,'west');
 await api.update(null);assert.equal(element('animalWikipedia').hidden,true);
 const unavailable=api.update(event('frog_calls','Unknown',0));
 pending[2].resolve({ok:false,status:503});await unavailable;
 assert.match(element('animalCaption').textContent,/unavailable/);
 assert.equal(element('animalImageButton').disabled,true);
 const roadrunner=api.update({kind:'birdsong',longitude:-106,traits:{scientific_name:'Geococcyx californianus'}});
 assert.equal(new URL(pending[3].url).searchParams.get('titles'),'Geococcyx californianus');
 const thumbnail='https://thumb.wikimedia.org/wikipedia/commons/thumb/9/93/Greater_Roadrunner_Tingley_Beach.jpg/960px-Greater_Roadrunner_Tingley_Beach.jpg?utm_source=en.wikipedia.org&utm_campaign=api&utm_content=thumbnail';
 respond(pending[3],'Greater roadrunner',thumbnail);await roadrunner;
 assert.equal(element('animalImage').hidden,false);
 assert.equal(element('animalImage').src,thumbnail);
 assert.equal(element('animalCaption').textContent,'Greater roadrunner · Wikipedia');
 element('animalImageButton').onclick();assert.equal(element('animalArticle').open,true);
 assert.equal(element('animalArticleTitle').textContent,'Greater roadrunner');
 for (const image of ['https://thumb.wikimedia.org.example.com/photo.jpg','http://thumb.wikimedia.org/photo.jpg',undefined]) {
  await api.update(null);
  const bird=api.update({kind:'birdsong',traits:{scientific_name:'Test bird '+pending.length}});
  respond(pending.at(-1),'Test bird',image === undefined ? '' : image);await bird;
  assert.equal(element('animalImage').hidden,true);
 }
})().catch(e=>{console.error(e);process.exitCode=1});
''', 'animal-wikipedia.js')
