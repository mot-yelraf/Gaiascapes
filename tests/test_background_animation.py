"""Check persistent background paint without installed state or live playback.

Run the browser module with a controlled DOM to verify round boundaries,
local preferences, and positioning as the map resizes.
"""

from test_browser_recovery import run_node


def test_paint_rounds_preferences_and_perimeter_positioning():
    """Retain nineteen locations, reset on the twentieth, and restore Burst."""
    run_node(r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const inputs = ['burst', 'paint'].map(value => ({value, addEventListener(type, fn) {this.change = fn;}}));
const waves = [];
let saved = null, resize, bounds = {left: 100, top: 200, width: 800, height: 400};
const scope = vm.createContext({
 document: {
  documentElement: {dataset: {}},
  querySelectorAll: selector => selector.startsWith('input') ? inputs : waves.filter(w => !w.removed),
  querySelector: () => null,
  body: {classList: {remove() {}}},
  getElementById: id => id === 'displaySettingsData'
   ? {textContent: JSON.stringify({background_animation: saved})}
   : id === "worldMap" ? {getBoundingClientRect: () => bounds} : null,
 },
 window: {innerWidth: 1200, innerHeight: 900,
  addEventListener: (type, fn) => {resize = fn;},
  localStorage: {getItem: () => saved, setItem: (key, value) => {
   assert.equal(key, 'background_animation'); saved = value;
  }},
 },
});
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(source, scope);
function wave() {
 const result = {dataset: {}, style: {setProperty(key, value) {this[key] = value;}, getPropertyValue(key) {return this[key] || "";}},
  classList: {add(value) {result.paintClass = value;}}, remove() {this.removed = true;}};
 waves.push(result);
 return result;
}
const event = {latitude: 0, longitude: 180};
assert.equal(inputs[0].checked, true);
assert.equal(scope.backgroundAnimation.retain(wave(), event), false);
inputs[1].change();
assert.equal(saved, null); // Previewing does not save settings.
assert.equal(inputs[1].checked, true);
const firstRound = Array.from({length: 19}, () => {
 const next = wave(); assert.equal(scope.backgroundAnimation.retain(next, event), true); return next;
});
assert.ok(firstRound.every(w => !w.removed));
assert.equal(firstRound[0].paintClass, 'event-wave--paint');
assert.equal(firstRound[0].style['--wave-x'], '924px');
assert.equal(firstRound[0].style['--wave-y'], '400px');
bounds = {left: 50, top: 100, width: 400, height: 200};
resize();
assert.equal(firstRound[0].style['--wave-x'], '462px');
assert.equal(firstRound[0].style['--wave-y'], '200px');
const twentieth = wave();
scope.backgroundAnimation.retain(twentieth, {latitude: 90, longitude: 0});
assert.ok(firstRound.every(w => w.removed));
assert.ok(!twentieth.removed);
assert.equal(twentieth.style['--wave-y'], '94px');
inputs[0].change();
assert.equal(twentieth.removed, true);
assert.equal(saved, null);
assert.equal(scope.backgroundAnimation.retain(wave(), event), false);
saved = 'paint';
vm.runInContext(source, scope);
assert.equal(inputs[1].checked, true); // Restore installation settings from the page.
scope.window.localStorage.getItem = () => {throw new Error('Storage disabled');};
vm.runInContext(source, scope);
assert.equal(inputs[1].checked, true); // Browser storage is never needed.
''', 'background-animation.js')


def test_paint_palette_and_shape_changes_restyle_existing_locations():
    """Apply saved choices, vary colors, and restyle paint without losing a round."""
    run_node(r'''
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const storage = new Map([
 ['background_animation', 'paint'],
 ['background_palette', 'aurora'],
 ['background_paint_shape', 'watercolor'],
]);
const inputs = ['burst', 'paint'].map(value => ({value, addEventListener(type, fn) {this.change = fn;}}));
const controls = Object.fromEntries(['backgroundPalette', 'backgroundPaintShape', 'backgroundEvents'].map(id =>
 [id, {addEventListener(type, fn) {this.change = fn;}}]));
const scope = vm.createContext({
 document: {
  documentElement: {dataset: {}},
  querySelectorAll: selector => selector.startsWith('input') ? inputs : [],
  querySelector: () => null, body: {classList: {remove() {}}},
  getElementById: id => id === 'displaySettingsData' ? {textContent: JSON.stringify(Object.fromEntries(storage))} : controls[id] || null,
 },
 window: {innerWidth: 1000, innerHeight: 800, addEventListener() {},
  localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
 },
});
const source = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(source, scope);
assert.equal(controls.backgroundPalette.value, 'aurora');
assert.equal(controls.backgroundPaintShape.value, 'watercolor');
assert.equal(controls.backgroundEvents.value, 'both');
assert.equal(scope.backgroundAnimation.visible('event'), true);
assert.equal(scope.backgroundAnimation.visible('background'), true);
controls.backgroundEvents.value = 'events';
controls.backgroundEvents.change();
assert.equal(scope.document.documentElement.dataset.animationEvents, 'events');
assert.equal(scope.backgroundAnimation.visible('event'), true);
assert.equal(scope.backgroundAnimation.visible('background'), false);
assert.equal(storage.get('background_events'), undefined);
function wave() {
 return {dataset: {}, classList: {add() {}}, remove() {this.removed = true;},
  style: {'--wave-color': '#123456', '--wave-inner': '#abcdef',
   setProperty(key, value) {this[key] = value;}, getPropertyValue(key) {return this[key];}},
 };
}
const waves = Array.from({length: 19}, (_, index) => {
 const next = wave();
 scope.backgroundAnimation.retain(next, {longitude: index * 10 - 90, latitude: 30});
 return next;
});
assert.equal(new Set(waves.map(w => w.style['--wave-color'])).size, 19);
assert.ok(waves.every(w => w.dataset.paintShape === 'watercolor'));
const aurora = waves[0].style['--wave-color'];
controls.backgroundPalette.value = 'wildflower';
controls.backgroundPalette.change();
assert.notEqual(waves[0].style['--wave-color'], aurora);
assert.equal(storage.get('background_palette'), 'aurora'); // Unsaved previews leave persisted settings alone.
controls.backgroundPaintShape.value = 'ribbon';
controls.backgroundPaintShape.change();
assert.ok(waves.every(w => w.dataset.paintShape === 'ribbon' && !w.removed));
assert.equal(storage.get('background_paint_shape'), 'watercolor');
controls.backgroundPalette.value = 'natural';
controls.backgroundPalette.change();
assert.equal(waves[0].style['--wave-color'], '#123456');
assert.equal(waves[0].style['--wave-inner'], '#abcdef');
const twentieth = wave();
scope.backgroundAnimation.retain(twentieth, {});
assert.ok(waves.every(w => w.removed)); // Changing choices did not reset the round counter.
assert.equal(twentieth.dataset.paintShape, 'ribbon');
controls.backgroundEvents.value = 'background';
controls.backgroundEvents.change();
assert.equal(scope.backgroundAnimation.visible('event'), false);
assert.equal(scope.backgroundAnimation.visible('background'), true);
inputs[0].change();
assert.equal(scope.document.documentElement.dataset.backgroundAnimation, 'burst');
assert.equal(scope.backgroundAnimation.visible('event'), true);
assert.equal(scope.backgroundAnimation.visible('background'), true);
controls.backgroundEvents.value = 'events';
controls.backgroundEvents.change();
assert.equal(scope.backgroundAnimation.visible('event'), true);
assert.equal(scope.backgroundAnimation.visible('background'), true);
controls.backgroundEvents.value = 'background';
controls.backgroundEvents.change();
controls.backgroundPalette.value = 'pastel';
controls.backgroundPalette.change();
const burst = wave();
assert.equal(scope.backgroundAnimation.retain(burst, {}), false);
assert.equal(burst.style['--wave-color'], '#123456');
assert.equal(burst.dataset.paintShape, undefined); // Shapes apply only to retained paint.
inputs[1].change();
controls.backgroundPalette.value = 'random';
controls.backgroundPaintShape.value = 'random';
controls.backgroundPalette.change();
let randomValues = [0.3, 0.5, 0.8, 0.9];
scope.Math = Object.create(Math);
scope.Math.random = () => randomValues.shift();
const randomFirst = wave();
scope.backgroundAnimation.retain(randomFirst, {});
assert.equal(randomFirst.dataset.paintPalette, 'aurora');
assert.equal(randomFirst.dataset.paintShape, 'watercolor');
const randomSecond = wave();
scope.backgroundAnimation.retain(randomSecond, {});
assert.equal(randomSecond.dataset.paintPalette, 'pastel');
assert.equal(randomSecond.dataset.paintShape, 'ribbon');
controls.backgroundPaintShape.change();
assert.equal(randomFirst.dataset.paintPalette, 'aurora');
assert.equal(randomFirst.dataset.paintShape, 'watercolor');
assert.equal(randomSecond.dataset.paintPalette, 'pastel');
assert.equal(randomValues.length, 0); // Existing layers never reroll when choices change.
storage.set('background_palette', 'random');
storage.set('background_paint_shape', 'random');
storage.set('background_events', 'background');
vm.runInContext(source, scope);
assert.equal(controls.backgroundPalette.value, 'random');
assert.equal(controls.backgroundPaintShape.value, 'random');
storage.set('background_palette', 'invalid');
storage.set('background_paint_shape', 'invalid');
vm.runInContext(source, scope);
assert.equal(controls.backgroundPalette.value, 'natural');
assert.equal(controls.backgroundPaintShape.value, 'bloom');
assert.equal(controls.backgroundEvents.value, 'background');
assert.equal(scope.backgroundAnimation.visible('event'), false);
storage.set('background_events', 'invalid');
vm.runInContext(source, scope);
assert.equal(controls.backgroundEvents.value, 'both');
assert.equal(scope.backgroundAnimation.visible('event'), true);
assert.equal(scope.backgroundAnimation.visible('background'), true);
''', 'background-animation.js')
