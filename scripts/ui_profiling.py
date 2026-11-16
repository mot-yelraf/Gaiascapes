"""Profile settings transitions and sustained browser playback in an isolated runtime.

This opt-in soak tool drives the real settings UI and records saved settings,
server cues, browser playback progress, and measured Web Audio output separately.
It never attaches to an existing installation. Credentials are loaded read-only
only when an explicit source file is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave


_STOP_REQUESTED = False
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_profile_settings import (CHECK_FIELDS, SELECT_FIELDS, SOURCE_FIELDS,
    apply_extra_controls, assert_settings, build_settings_plan, coverage_audit)
RECORDINGS = ('birdsong', 'frog_calls', 'whale_song', 'dolphin_calls',
              'feline_calls', 'canine_calls', 'elephant_calls', 'primate_calls')
SOURCE_CONTROLS = {
    'birdsong': 'sourceBirdsong', 'frog_calls': 'sourceFrogCalls',
    'whale_song': 'sourceWhaleSong', 'dolphin_calls': 'sourceDolphinCalls',
    'ocean_swell': 'sourceMarine', 'storm_potential': 'sourceStorm',
    **{kind: f'source_{kind}' for kind in RECORDINGS[4:]},
}
DISPLAY_CONTROLS = {
    'background_palette': 'backgroundPalette',
    'background_murmuration_palette': 'backgroundMurmurationPalette',
    'background_paint_shape': 'backgroundPaintShape',
    'background_events': 'backgroundEvents', 'map_projection': 'mapProjection',
    'map_center_longitude': 'mapCenterLongitude', 'sound_location_order': 'soundLocationOrder',
}
# Observe the actual output graph; the extra analyser branch is silenced, while
# the application's original connection and playback behavior remain intact.
AUDIO_METER = r'''
(() => {
 const connect = AudioNode.prototype.connect;
 const attached = new WeakSet();
 globalThis.__uiAudioMeters = [];
 globalThis.__uiLongTasks = {count: 0, milliseconds: 0};
 if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
  new PerformanceObserver(list => {for (const e of list.getEntries()) {
   globalThis.__uiLongTasks.count++; globalThis.__uiLongTasks.milliseconds += e.duration;
  }}).observe({type: 'longtask', buffered: true});
 }
 AudioNode.prototype.connect = function(destination, ...args) {
  const result = connect.call(this, destination, ...args);
  if (destination === this.context.destination && !attached.has(this)) {
   attached.add(this);
   const analyser = this.context.createAnalyser(); analyser.fftSize = 2048;
   const sink = this.context.createGain(); sink.gain.value = 0;
   connect.call(this, analyser); connect.call(analyser, sink); connect.call(sink, destination);
   globalThis.__uiAudioMeters.push({analyser, context: this.context, data: new Float32Array(2048)});
  }
  return result;
 };
})();
'''
BROWSER_SAMPLE = r'''() => {
 const meters = globalThis.__uiAudioMeters || [];
 let rms = 0;
 for (const meter of meters) {
  meter.analyser.getFloatTimeDomainData(meter.data);
  rms = Math.max(rms, Math.sqrt(meter.data.reduce((s, x) => s + x*x, 0) / meter.data.length));
 }
 const audio = recordingAudio;
 return {kind: recordingKind, position: audio?.currentTime || 0,
  sequence: audio?.rotationSequence || 0, paused: audio?.paused ?? true,
  gain: audio?.recordingOutputGain || 0, rms,
  active_players: activeRecordingAudio.size,
  contexts: meters.map(m => m.context.state),
  heap_bytes: performance.memory?.usedJSHeapSize || null,
  long_tasks: globalThis.__uiLongTasks,
  message: document.getElementById('message')?.textContent || ''};
}'''


def check_interrupted():
    """Raise only between browser operations so signal handling cannot strand one."""
    if _STOP_REQUESTED:
        raise KeyboardInterrupt


def write_json(path, value):
    """Replace a report atomically so interrupted runs retain readable results."""
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


class FixtureRecording:
    """Provide deterministic, non-silent WAV recordings through real media routes."""

    location_count = 3

    def __init__(self, data_dir, kind, duration, silent=False):
        self.kind = kind
        self.media_dir = data_dir / 'media' / kind
        self.media_dir.mkdir(parents=True, exist_ok=True)
        rate = 16000
        frequency = 220 + RECORDINGS.index(kind) * 55
        with wave.open(str(self.media_dir / 'profile.wav'), 'wb') as output:
            output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            samples = (int((0 if silent else 6000) * math.sin(2 * math.pi * frequency * i / rate))
                       for i in range(int(rate * duration)))
            output.writeframes(b''.join(struct.pack('<h', value) for value in samples))

    def event_at(self, index):
        """Return a new location visit while retaining the selected recording kind."""
        from gaiascapes.events import GaiaEvent
        prefix = 'birdsong' if self.kind == 'birdsong' else self.kind.replace('_', '-')
        return GaiaEvent('ui_profiling', f'{self.kind}-{index}-{time.time_ns()}', self.kind,
                         time.time(), latitude=15 + index % 3, longitude=-30,
                         strength=.6, traits={
                             'place': f'Profiling location {index % 3 + 1}',
                             'title': f'{self.kind} fixture tone',
                             'media_url': f'/{prefix}-media/profile.wav',
                         })


def profile_event(kind):
    """Construct a labeled probe without impersonating an observed Earth event."""
    from gaiascapes.events import GaiaEvent
    return GaiaEvent('ui_profiling', f'probe-{kind}-{time.time_ns()}', kind, time.time(),
                     latitude=12, longitude=-30, strength=.6,
                     traits={'magnitude': 3, 'place': 'UI profiling probe'})


def prepare_real_recordings(service):
    """Allow a fresh profiling runtime to populate its own Commons audio cache."""
    from gaiascapes_host.commons_birdsong import CommonsBirdsongClient

    if isinstance(service.birdsong, CommonsBirdsongClient):
        service.birdsong.allow_downloads = True


class FixtureProvider:
    """Keep provider polling and source toggles real while supplying local events."""

    last_raw_flash_count = 1
    last_granule_count = 1
    last_error = ''

    def __init__(self, source, kind):
        self.source, self.kind = source, kind

    def fetch(self):
        """Produce a fresh labeled event through the normal capture pipeline."""
        event = profile_event(self.kind)
        event.provider = self.source
        return (event,)

    def status(self):
        """Expose the optional metadata used by lightning source health."""
        return {'configured': True, 'granule_count': 1, 'raw_flash_count': 1}

    def set_credentials(self, *_values):
        """Accept seeded fixture credentials without contacting a provider."""


class FixtureGeoIp:
    """Supply deterministic approximate location without external IP lookups."""

    def resolve(self):
        """Return the profiler's fictional host position."""
        return {'name': 'UI profiling host', 'latitude': 39.0, 'longitude': -105.0,
                'timezone': 'America/Denver', 'provider': 'ui_profiling'}


def serve(args):
    """Start a private server whose diagnostics require this run's random token."""
    import uvicorn
    from fastapi import Header, HTTPException
    from gaiascapes_host.app import create_app
    from gaiascapes_host.config import AppConfig

    data_dir = Path(os.environ['GAIA_SCAPE_DATA_DIR']).resolve()
    token = os.environ['UI_PROFILING_TOKEN']
    marker = data_dir / '.ui-profiling'
    if (not marker.is_file() or marker.read_text() != token
            or (data_dir / 'config.json').exists()):
        raise RuntimeError('Profiler server requires its own new, marked runtime directory')
    config = AppConfig(enabled_sources=(['usgs', 'open_meteo_marine', 'open_meteo_storm', 'noaa_glm']
                                        if args.mode == 'real' else []), osc_enabled=False, system_location_enabled=False,
                       announcements_enabled=False, live_mode='capture',
                       continuous_interval_seconds=args.interval_seconds,
                       event_instruments={'event_1': 'none', 'event_2': 'none',
                                          'event_3': 'none', 'background': 'none'})
    config.xeno_canto_api_key = ('ui-profiling-fixture' if args.mode == 'fixture'
                                else os.environ.get('UI_PROFILING_XENO_CANTO_API_KEY', ''))
    for field in ('eumetsat_consumer_key', 'eumetsat_consumer_secret'):
        setattr(config, field, 'ui-profiling-fixture' if args.mode == 'fixture' else os.environ.get('UI_PROFILING_' + field.upper(), ''))
    config.save(data_dir / 'config.json')
    clients = {}
    if args.mode == 'fixture':
        clients = {name: FixtureProvider(source, kind) for name, source, kind in (
            ('usgs_client', 'usgs', 'earthquake'), ('marine_client', 'open_meteo_marine', 'ocean_swell'),
            ('storm_client', 'open_meteo_storm', 'storm_potential'), ('glm_client', 'noaa_glm', 'lightning_flash'),
            ('mtg_li_client', 'eumetsat_mtg_li', 'lightning_flash'))}
        clients['geoip_resolver'] = FixtureGeoIp()
    app = create_app(data_dir, auto_capture=True, **clients)
    service = app.state.service
    if args.mode == 'real':
        prepare_real_recordings(service)
    if args.mode == 'fixture':
        for kind in RECORDINGS:
            setattr(service, kind, FixtureRecording(
                data_dir, kind, args.recording_seconds, silent=kind == args.fixture_silent_kind))
        original_lifespan = app.router.lifespan_context

        async def feed():
            while True:
                await asyncio.to_thread(service.store.add_events,
                                        [profile_event(kind) for kind in ('ocean_swell', 'storm_potential')])
                await asyncio.sleep(5)

        @asynccontextmanager
        async def lifespan(application):
            async with original_lifespan(application):
                task = asyncio.create_task(feed())
                try:
                    yield
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        app.router.lifespan_context = lifespan

    original_apply = service._apply_config

    def apply_profile_config(candidate):
        changed = original_apply(candidate)
        if args.mode == 'fixture':
            for kind in RECORDINGS:
                if not isinstance(getattr(service, kind), FixtureRecording):
                    setattr(service, kind, FixtureRecording(data_dir, kind, args.recording_seconds,
                            silent=kind == args.fixture_silent_kind))
        else:
            prepare_real_recordings(service)
        return changed

    service._apply_config = apply_profile_config

    def authorize(value):
        if not secrets.compare_digest(value or '', token):
            raise HTTPException(403, 'Wrong profiling session')

    @app.get('/__ui_profiling__/snapshot')
    async def snapshot(x_ui_profiling_token: str = Header(default='')):
        authorize(x_ui_profiling_token)
        return {'status': await service.status(), 'cues': list(service._emitted_cues),
                'mode': args.mode, 'data_dir': str(data_dir)}

    @app.post('/__ui_profiling__/probe')
    async def probe(x_ui_profiling_token: str = Header(default='')):
        authorize(x_ui_profiling_token)
        for kind in ('earthquake', 'lightning_flash', 'tide_turn'):
            await service._play_live_event(profile_event(kind))
        return {'probe': True, 'audio_verification': 'dispatch_only'}

    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False,
                timeout_graceful_shutdown=4)


def build_plan(inventory, has_frog_key):
    """Cover selectable values without requiring the full Cartesian product."""
    backgrounds = inventory['backgroundInstrument']
    # Returning to a recently used recording is a separate transition from
    # visiting it once, and is central to detecting stale retained recordings.
    backgrounds = [item for value in ('birdsong', 'feline_calls', 'birdsong')
                   for item in backgrounds if item['value'] == value] + backgrounds
    count = max(len(backgrounds), *(len(value) for value in inventory.values() if isinstance(value, list)))
    plan = []
    for index in range(count):
        background = backgrounds[index % len(backgrounds)]['value']
        step = {'background': background, 'controls': {}, 'radios': {}, 'voices': {},
                'volume': (25, 50, 75, 100)[index % 4], 'source_enabled': True}
        if background == 'frog_calls' and not has_frog_key:
            step['skip'] = 'Frog Calls requires UI_PROFILING_XENO_CANTO_API_KEY in real mode'
        for slot, control in (('event_1', 'event1Instrument'), ('event_2', 'event2Instrument'),
                              ('event_3', 'event3Instrument')):
            step['voices'][slot] = inventory[control][index % len(inventory[control])]['value']
        for key, control in DISPLAY_CONTROLS.items():
            step['controls'][key] = inventory[control][index % len(inventory[control])]['value']
        for name in ('theme', 'backgroundAnimation'):
            step['radios'][name] = inventory[name][index % len(inventory[name])]['value']
        step['units'] = inventory['displayUnits'][index % len(inventory['displayUnits'])]['value']
        plan.append(step)
    for kind in RECORDINGS:
        template = next((step for step in plan if step['background'] == kind), None)
        if template:
            plan.extend([{**template, 'source_enabled': False}, {**template, 'source_enabled': True},
                         {**template, 'source_enabled': True, 'volume': 0},
                         {**template, 'source_enabled': True, 'volume': 50}])
    return plan


def playback_active(expected, browser, cues, baseline, previous, retained_sequence=0):
    """Require fresh dispatch plus actual forward, non-silent recording playback."""
    fresh = [cue for cue in cues if (cue['sequence'] > baseline or cue['sequence'] == retained_sequence)
             and cue['instrument'] == expected and cue['output_channel'] == 'background']
    if expected == 'muted':
        return browser['rms'] < 1e-5 and browser.get('gain', 0) == 0
    if expected == 'none':
        return not browser['active_players'] and browser['rms'] < 1e-5
    if expected not in RECORDINGS:
        return bool(fresh)
    progressing = (previous is not None and browser['sequence'] == previous['sequence']
                   and browser['position'] > previous['position'] + .05)
    return (any(cue['sequence'] == browser['sequence'] for cue in fresh)
            and browser['kind'] == expected and not browser['paused'] and progressing
            and browser['gain'] > 0 and browser['rms'] > 1e-5)


class Profiler:
    """Drive user controls, observe transitions, and persist failure evidence."""

    def __init__(self, page, base_url, token, output, args):
        self.page, self.base_url, self.output, self.args = page, base_url, output, args
        self.headers = {'X-UI-Profiling-Token': token}
        self.errors = []
        self.announcements = []
        self.report = {'mode': args.mode, 'started_at': time.time(), 'steps': [],
                       'scope': 'recording audio signal; generated voices dispatch only',
                       'parameters': {name: getattr(args, name) for name in
                                      ('minutes', 'dwell_seconds', 'activation_timeout', 'silence_timeout',
                                       'sample_seconds', 'interval_seconds', 'recording_seconds',
                                       'start_step', 'max_steps', 'fixture_silent_kind', 'runs', 'setting_dwell_seconds')},
                       'coverage': {}, 'excluded_controls': ['credential editing']}
        page.on('pageerror', lambda error: self.record_error('pageerror', str(error)))
        page.on('console', lambda message: self.record_error('console', message.text)
                if message.type in ('error', 'warning') else None)
        page.on('response', self.observe_announcement)
        page.on('response', lambda response: self.record_error('http', f'{response.status} {response.url}')
                if response.status >= 400 else None)

    def observe_announcement(self, response):
        """Record actual speech responses and fallback engines without request bodies."""
        if '/api/announcements/' in response.url:
            self.announcements.append({'at': time.time(), 'status': response.status,
                'engine': response.headers.get('x-announcement-engine', ''),
                'fallback': response.headers.get('x-announcement-fallback', ''),
                'bytes': int(response.headers.get('content-length', '0'))})

    def record_error(self, kind, message):
        """Retain timestamped failures without dumping request bodies or credentials."""
        self.errors.append({'at': time.time(), 'kind': kind, 'message': message[:2000]})

    def api(self, path, method='get'):
        """Read only this run's server; never attach to a production URL."""
        response = getattr(self.page.request, method)(self.base_url + path, headers=self.headers)
        if not response.ok:
            raise RuntimeError(f'{method.upper()} {path}: HTTP {response.status}')
        return response.json()

    def inventory(self):
        """Discover selectable values directly from the rendered controls."""
        return self.page.evaluate('''() => {
          const result = {};
          document.querySelectorAll('#settingsForm select[id]').forEach(select => {
            result[select.id] = Array.from(select.options, o => ({value:o.value, label:o.textContent}));
          });
          for (const name of ['theme', 'backgroundAnimation']) result[name] =
            Array.from(document.querySelectorAll(`input[name="${name}"]`), o => ({value:o.value}));
          result._controls = {};
          document.querySelectorAll('#settingsForm select[id], #settingsForm input[id]').forEach(e => {
            if (['password', 'radio'].includes(e.type)) return;
            result._controls[e.id] = {type: e.tagName === 'SELECT' ? 'select' : e.type,
              pane: e.closest('.settings-pane').dataset.pane, checked: e.checked,
              min: e.min, max: e.max, values: e.options ? Array.from(e.options, o => o.value) : []};
          });
          result._locations = JSON.parse(document.getElementById('forecastLocationData').textContent).current;
          return result;
        }''')

    def pane(self, name):
        """Open a settings tab using its visible UI controls."""
        if not self.page.locator('#settingsDialog').evaluate('(e) => e.open'):
            self.page.locator('[data-open-settings]').click()
        self.page.locator(f'[data-settings-pane="{name}"]').click()

    def sound(self, control, value):
        """Choose the visible sound card, including its scrolling behavior."""
        options = self.page.locator(f'#{control} option').evaluate_all(
            '(options) => options.map(o => ({value:o.value, label:o.textContent}))')
        label = next(item['label'] for item in options if item['value'] == value)
        picker = self.page.locator(f'[data-sound-picker][data-select="{control}"]')
        picker.get_by_role('radio', name=label, exact=True).click()
        self.page.wait_for_timeout(200)
        if self.page.locator(f'#{control}').input_value() != value:
            raise RuntimeError(f'{control}: visible card did not select {value}')

    def save(self):
        """Submit the actual settings form and require all three saves to succeed."""
        self.save_baseline = self.api('/__ui_profiling__/snapshot')['status']['cues']['latest_sequence']
        before_save = self.page.evaluate(BROWSER_SAMPLE)
        self.retained_sequence = (before_save['sequence'] if not before_save['paused']
                                  and before_save['kind'] == self.page.locator('#backgroundInstrument').input_value() else 0)
        with self.page.expect_response(lambda response: response.url.endswith('/api/settings/audio')
                                       and response.request.method == 'PUT') as pending:
            self.page.locator('#settingsForm button[type="submit"]').click()
        if not pending.value.ok:
            raise RuntimeError(f'Settings save failed: HTTP {pending.value.status}: {pending.value.text()}')
        self.page.wait_for_function('''() => {
          const b = document.querySelector('#settingsForm button[type="submit"]');
          return !b.disabled && b.textContent === 'Save settings';
        }''')

    def apply(self, step):
        """Change sounds, gains, and display options before saving as a user would."""
        self.pane('sources')
        for control, metadata in self.inventory_data['_controls'].items():
            if metadata['type'] == 'checkbox' and metadata['pane'] == 'sources':
                self.page.locator(f'#{control}').set_checked(False if control == 'announcementsEnabled' else metadata['checked'])
        self.page.locator('#sourceBirdsong').check()
        self.page.locator('#birdsongProvider').select_option('wikimedia_commons')
        self.page.locator('#announcementSynthesizer').select_option('auto')
        control = SOURCE_CONTROLS.get(step['background'])
        if control:
            self.page.locator(f'#{control}').set_checked(step['source_enabled'])
        self.pane('theme')
        for name, value in step['radios'].items():
            self.page.locator(f'input[name="{name}"][value="{value}"]').check()
        for key, control in DISPLAY_CONTROLS.items():
            if key == 'sound_location_order':
                continue
            self.page.locator(f'#{control}').select_option(step['controls'][key])
        self.pane('locations')
        self.page.locator('#soundLocationOrder').select_option(step['controls']['sound_location_order'])
        self.pane('instruments')
        self.page.locator('#systemLocationEnabled').uncheck()
        self.page.locator('#announcementVoice').select_option('en-us')
        self.page.locator('#announcementVariant').select_option('default')
        self.page.locator('#announcementVolume').fill('70')
        self.page.locator('#announcementVolume').dispatch_event('input')
        self.sound('backgroundInstrument', step['background'])
        for slot, control in (('event_1', 'event1Instrument'), ('event_2', 'event2Instrument'),
                              ('event_3', 'event3Instrument')):
            self.sound(control, step['voices'][slot])
        self.sound('displayUnits', step['units'])
        for control in ('backgroundVolume', 'event1Volume', 'event2Volume', 'event3Volume'):
            self.page.locator(f'#{control}').fill(str(step['volume']))
            self.page.locator(f'#{control}').dispatch_event('input')
        extra_expected = apply_extra_controls(self, step)
        self.save()
        config = self.api('/api/config')
        expected = {**step['controls'], 'theme': step['radios']['theme'],
                    'background_animation': step['radios']['backgroundAnimation'], 'units': step['units']}
        fields = {**expected,
                  **{f'event_instruments.{slot}': value for slot, value in
                     {**step['voices'], 'background': step['background']}.items()},
                  **{f'instrument_volumes.{slot}': step['volume'] / 100
                     for slot in ('background', 'event_1', 'event_2', 'event_3')},
                  **extra_expected}
        assert_settings(config, fields)
        if any(control.endswith('LightningSampleRate') for control in step.get('extra', {})):
            values = self.page.locator('[data-lightning-sample-rate]').evaluate_all('(e) => e.map(x => Number(x.value))')
            if values != [config['lightning_sample_rate']] * 3:
                raise RuntimeError('Lightning sliders did not synchronize')
        if step.get('extra', {}).get('systemLocationEnabled'):
            if self.api('/api/system-location').get('location') is None:
                raise RuntimeError('Host location enabled but no approximate location became active')
        for key, value in {**expected, **step['voices'], 'background': step['background'],
                           'volume': step['volume'], f"source_{step['background']}": step['source_enabled']}.items():
            self.report['coverage'].setdefault(key, [])
            if value not in self.report['coverage'][key]:
                self.report['coverage'][key].append(value)
        self.page.locator('#settingsDialog [data-close-settings]').first.click()
        return {'verified_fields': fields, **{key: config[key] for key in (*expected, 'event_instruments', 'instrument_volumes')}}

    def perform_after_save(self, step):
        """Exercise preview/listening controls and start a fresh announcement visit."""
        action = step.get('action', {})
        if step.get('restart_recording'):
            for button, endpoint in (('pauseButton', '/api/live/stop'), ('playButton', '/api/live/start')):
                with self.page.expect_response(lambda r, endpoint=endpoint: r.url.endswith(endpoint)) as response:
                    self.page.locator('#' + button).click()
                if not response.value.ok:
                    raise RuntimeError(f'{endpoint} failed while preparing announcement check')
        if action.get('kind') == 'preview':
            self.pane('instruments')
            control = action['slot'] + 'Instrument'
            with self.page.expect_response(lambda r: r.url.endswith('/api/instruments/preview')) as response:
                self.page.locator(f'.preview-instrument-button[data-select="{control}"]').click()
            if not response.value.ok:
                raise RuntimeError(f'Preview failed: HTTP {response.value.status}')
            payload = response.value.json()
            expected = step['background'] if action['slot'] == 'background' else step['voices'][f'event_{action["slot"][-1]}']
            if payload['instrument'] != expected:
                raise RuntimeError('Preview used a different sound than the selected card')
            self.page.locator('#settingsDialog [data-close-settings]').first.click()
        if action.get('kind') == 'listen':
            self.pane('instruments')
            button = self.page.locator('#listenButton')
            if (button.get_attribute('aria-pressed') == 'true') != action['enabled']:
                button.click()
            self.page.wait_for_timeout(500)
            if (button.get_attribute('aria-pressed') == 'true') != action['enabled']:
                raise RuntimeError('Device listening control did not change state')
            if action['enabled']:
                cues = self.api('/__ui_profiling__/snapshot')['cues']
                self.retained_sequence = max((cue['sequence'] for cue in cues
                    if cue['instrument'] == step['background'] and cue.get('recording_rotation')), default=0)
            self.page.locator('#settingsDialog [data-close-settings]').first.click()

    def check_source_state(self, step, snapshot, saved_at):
        """Wait for newly enabled providers to attempt an update and surface failures."""
        for control, enabled in step.get('extra', {}).items():
            if control not in SOURCE_FIELDS:
                continue
            source = SOURCE_FIELDS[control]
            health = snapshot['status']['sources']['health'][source]
            if health['enabled'] != enabled:
                return False
            if enabled:
                if health.get('last_failure_at', 0) and health['last_failure_at'] >= saved_at:
                    raise RuntimeError(f'{source} activation failed: {health.get("last_error", "provider error")}')
                if not health.get('last_success_at') or health['last_success_at'] < saved_at:
                    return False
        return True

    def run_step(self, step, number):
        """Allow activation time, then observe sustained playback throughout the dwell."""
        check_interrupted()
        result = {'number': number, 'selection': step, 'started_at': time.time(), 'samples': []}
        self.report['active_step'] = result
        write_json(self.output / 'status.json', {'number': number, 'case_id': step['case_id'], 'stage': 'applying'})
        if step.get('skip'):
            return {**result, 'outcome': 'blocked', 'reason': step['skip']}
        error_start = len(self.errors)
        try:
            result['saved_settings'] = self.apply(step)
            announcement_start = len(self.announcements)
            self.perform_after_save(step)
            baseline = self.save_baseline
            saved_at = time.monotonic()
            result['saved_at'] = time.time()
            deadline = saved_at + self.args.activation_timeout
            active_at = None
            last_active = None
            previous = None
            voice_seen = set()
            while True:
                check_interrupted()
                now = time.monotonic()
                snapshot = self.api('/__ui_profiling__/snapshot')
                browser = self.page.evaluate(BROWSER_SAMPLE)
                expected_sound = step['background'] if step['source_enabled'] else 'none'
                if step.get('action', {}).get('kind') == 'listen' and not step['action']['enabled']:
                    expected_sound = 'none'
                if step['volume'] == 0:
                    expected_sound = 'muted'
                active = playback_active(expected_sound, browser, snapshot['cues'], baseline, previous,
                                         retained_sequence=self.retained_sequence)
                for cue in snapshot['cues']:
                    slot = cue.get('output_channel')
                    if (cue['sequence'] > baseline and slot in step['voices']
                            and cue['emitted_at'] > result['saved_at'] + 1
                            and step['voices'][slot] != cue['instrument']):
                        raise RuntimeError(f'Stale event voice {cue["instrument"]} on {slot}')
                    if cue['sequence'] > baseline and step['voices'].get(slot) == cue['instrument']:
                        voice_seen.add(slot)
                if step.get('action', {}).get('kind') == 'preview' and step['background'] in RECORDINGS:
                    active = (browser['kind'] == step['background'] and not browser['paused']
                              and browser['rms'] > 1e-5 and previous is not None
                              and browser['position'] > previous['position'] + .05)
                active = active and self.check_source_state(step, snapshot, result['saved_at'])
                sample = {'elapsed': round(now - saved_at, 3), 'browser': browser,
                          'active': active, 'live': snapshot['status']['live'],
                          'recordings': snapshot['status']['sources']['recordings'],
                          'source_health': snapshot['status']['sources']['health'],
                          'sources_enabled': snapshot['status']['sources']['enabled'],
                          'latest_sequence': snapshot['status']['cues']['latest_sequence']}
                result['samples'].append(sample)
                result['last_cues'] = snapshot['cues'][-30:]
                if active:
                    last_active = now
                    if active_at is None:
                        active_at = now
                        result['activation_seconds'] = round(now - saved_at, 3)
                        result['activation_delayed'] = now - saved_at > self.args.interval_seconds * 2 + 5
                if active_at is None and now >= deadline:
                    raise RuntimeError('activation_timeout: saved selection never became active')
                if active_at is not None and last_active is not None and now - last_active > self.args.silence_timeout:
                    raise RuntimeError('playback_stalled: selected sound stopped progressing or became silent')
                dwell = (self.args.setting_dwell_seconds if step.get('short_check') else self.args.dwell_seconds)
                if step.get('action', {}).get('kind') == 'preview':
                    dwell = 2
                if active_at is not None and now - active_at >= dwell:
                    expected_slots = {slot for slot, value in step['voices'].items()
                                      if value != 'none' and step['volume'] > 0}
                    if not expected_slots <= voice_seen:
                        raise RuntimeError(f'No selected event cue for {sorted(expected_slots - voice_seen)}')
                    break
                previous = browser
                self.api('/__ui_profiling__/probe', 'post')
                self.page.wait_for_timeout(self.args.sample_seconds * 1000)
                write_json(self.output / 'status.json', {'number': number, 'case_id': step['case_id'],
                    'stage': 'observing', 'activation_seconds': result.get('activation_seconds'),
                    'sample_count': len(result['samples']), 'latest_sample': sample})
            if any(error['kind'] == 'pageerror' for error in self.errors[error_start:]):
                raise RuntimeError('Uncaught browser error during the settings transition')
            speech = self.announcements[announcement_start:]
            if step.get('verify_announcement') is True and not any(
                    response['status'] == 200 and response['engine'] and response['bytes'] > 44 for response in speech):
                raise RuntimeError('Selected announcement settings produced no rendered speech')
            if step.get('verify_announcement') is False and speech:
                raise RuntimeError('Disabled or muted announcements still requested speech')
            result['announcement_responses'] = speech
            result['outcome'] = 'passed'
            result['audio_evidence'] = ('signal_and_clock' if expected_sound in RECORDINGS
                                        else 'intentional_silence' if expected_sound in ('none', 'muted')
                                        else 'dispatch_only')
            result['event_slots_dispatched'] = sorted(voice_seen)
        except Exception as exc:
            result.update(outcome='failed', reason=str(exc))
            try:
                self.page.screenshot(path=str(self.output / f'failure-{number:04d}.png'), full_page=True)
            except Exception as screenshot_error:
                result['screenshot_error'] = str(screenshot_error)
        result['errors'] = self.errors[error_start:]
        result['finished_at'] = time.time()
        return result


def protected_configs():
    """Fingerprint known installation settings without importing or exposing secrets."""
    directories = {Path.home() / 'Gaiascapes' / 'data', ROOT / 'data'}
    if os.environ.get('GAIA_SCAPE_DATA_DIR'):
        directories.add(Path(os.environ['GAIA_SCAPE_DATA_DIR']).expanduser().resolve())
    return {str(directory.resolve() / 'config.json'): (hashlib.sha256(
        (directory / 'config.json').read_bytes()).hexdigest()
        if (directory / 'config.json').is_file() else None) for directory in directories}


def validate_output(path, protected):
    """Reject artifacts under an installed runtime, including nonexistent subfolders."""
    for config_path in protected:
        data_dir = Path(config_path).parent
        if path == data_dir or data_dir in path.parents:
            raise ValueError('Profiling output must be outside installed runtime data')


def run_both(args, run_phase=None):
    """Run a local baseline and real-provider phase with separate runtime state."""
    run_phase = run_phase or main
    if args.output:
        output = args.output.expanduser().resolve()
        validate_output(output, protected_configs())
        output.mkdir(parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix='gaiascapes-ui-profile-'))
    summary = {'mode': 'both', 'runs': args.runs, 'minutes_limit': args.minutes,
               'started_at': time.time(), 'phases': []}
    print(f'Combined profile: {args.runs} complete runs; artifacts: {output}', flush=True)
    status = 0
    try:
        for run in range(1, args.runs + 1):
            for mode in ('fixture', 'real'):
                check_interrupted()
                phase_output = output / f'run-{run:02d}' / mode
                phase = {'run': run, 'mode': mode, 'report': str(phase_output / 'report.json'), 'outcome': 'running'}
                summary['phases'].append(phase)
                write_json(output / 'report.json', summary)
                arguments = ['--mode', mode, '--runs', '1', '--output', str(phase_output)]
                if args.minutes is not None:
                    arguments.extend(['--minutes', str(args.minutes / (2 * args.runs))])
                for name in ('dwell_seconds', 'setting_dwell_seconds', 'activation_timeout', 'silence_timeout',
                             'sample_seconds', 'interval_seconds', 'recording_seconds', 'start_step', 'max_steps'):
                    value = getattr(args, name)
                    if value is not None:
                        arguments.extend(['--' + name.replace('_', '-'), str(value)])
                for name in ('headed', 'trace_all'):
                    if getattr(args, name):
                        arguments.append('--' + name.replace('_', '-'))
                for pattern in args.case_filter:
                    arguments.extend(['--case-filter', pattern])
                if args.credentials_from is not None and mode == 'real':
                    arguments.extend(['--credentials-from', str(args.credentials_from)])
                if mode == 'fixture' and args.fixture_silent_kind:
                    arguments.extend(['--fixture-silent-kind', args.fixture_silent_kind])
                try:
                    code = run_phase(arguments)
                    phase.update(exit_code=code, outcome='passed' if code == 0 else 'failed')
                    if (phase_output / 'report.json').exists():
                        detail = json.loads((phase_output / 'report.json').read_text())
                        phase['coverage_audit'] = detail.get('coverage_audit')
                        phase['results'] = detail.get('outcomes')
                except Exception as exc:
                    code = 1
                    phase.update(exit_code=code, outcome='error', error=str(exc))
                write_json(output / 'report.json', summary)
                if code == 130:
                    phase['outcome'] = 'interrupted'
                    raise KeyboardInterrupt
                if code:
                    status = 1
    except KeyboardInterrupt:
        status = 130
        summary['interrupted'] = True
    finally:
        summary.update(finished_at=time.time(), exit_code=status)
        summary['verification_complete'] = len(summary['phases']) == args.runs * 2 and all(
            phase.get('coverage_audit', {}).get('verification_complete', False) for phase in summary['phases'])
        summary['completed_runs'] = sum(all(any(p['run'] == run and p['mode'] == mode
            and p.get('coverage_audit', {}).get('plan_complete', False) for p in summary['phases'])
            for mode in ('fixture', 'real')) for run in range(1, args.runs + 1))
        summary['verified_runs'] = sum(all(any(p['run'] == run and p['mode'] == mode
            and p.get('coverage_audit', {}).get('verification_complete', False) for p in summary['phases'])
            for mode in ('fixture', 'real')) for run in range(1, args.runs + 1))
        write_json(output / 'report.json', summary)
    return status


def parser():
    """Describe the profiling duration, evidence thresholds, and isolated modes."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--mode', choices=('both', 'fixture', 'real'), default='both')
    result.add_argument('--minutes', type=float, help='Optional time cap for an explicitly incomplete exploratory run')
    result.add_argument('--runs', type=int, default=3, help='Complete coverage passes (default: 3)')
    result.add_argument('--setting-dwell-seconds', type=float, default=5)
    result.add_argument('--credentials-from', type=Path, help='Read existing credentials without editing them or the source file')
    result.add_argument('--case-filter', action='append', default=[], help='Diagnostic case prefix; makes coverage incomplete')
    result.add_argument('--dwell-seconds', type=float, default=45)
    result.add_argument('--activation-timeout', type=float, default=120)
    result.add_argument('--silence-timeout', type=float, default=15)
    result.add_argument('--sample-seconds', type=float, default=2)
    result.add_argument('--interval-seconds', type=float, default=23)
    result.add_argument('--recording-seconds', type=float, default=32)
    result.add_argument('--fixture-silent-kind', choices=RECORDINGS,
                        help='Inject a silent WAV for a fixture-mode negative control')
    result.add_argument('--max-steps', type=int)
    result.add_argument('--start-step', type=int, default=1, help='Start at this 1-based plan entry')
    result.add_argument('--trace-all', action='store_true', help='Keep successful traces too (larger artifacts)')
    result.add_argument('--output', type=Path)
    result.add_argument('--headed', action='store_true')
    result.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    result.add_argument('--port', type=int, default=0, help=argparse.SUPPRESS)
    return result


def main(argv=None):
    """Run a bounded soak, retaining artifacts and reaping all owned processes."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = False
    args = parser().parse_args(argv)
    for name in ('minutes', 'setting_dwell_seconds', 'dwell_seconds', 'activation_timeout', 'silence_timeout',
                 'sample_seconds', 'interval_seconds', 'recording_seconds'):
        if getattr(args, name) is not None and (not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0):
            raise SystemExit(f'--{name.replace("_", "-")} must be finite and positive')
    if args.interval_seconds < 10:
        raise SystemExit('--interval-seconds must be at least 10 to preserve full-recording playback')
    if args.fixture_silent_kind and args.mode == 'real':
        raise SystemExit('--fixture-silent-kind is only supported in fixture mode')
    if args.runs < 1:
        raise SystemExit('--runs must be positive')
    if args.start_step < 1:
        raise SystemExit('--start-step must be positive')
    if args.max_steps is not None and args.max_steps < 1:
        raise SystemExit('--max-steps must be positive')
    if args.serve and args.mode == 'both':
        raise SystemExit('--serve requires a single fixture or real phase')
    os.umask(0o077)
    if args.serve:
        serve(args)
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit('Install profiling tools: python -m pip install playwright; python -m playwright install chromium')
    def interrupt(_signum, _frame):
        global _STOP_REQUESTED
        _STOP_REQUESTED = True

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    if args.mode == 'both':
        return run_both(args)
    fingerprints = protected_configs()
    if args.output:
        output = args.output.expanduser().resolve()
        validate_output(output, fingerprints)
        output.mkdir(parents=True, exist_ok=False)
    else:
        output = Path(tempfile.mkdtemp(prefix='gaiascapes-ui-profile-'))
    data_dir = output / 'runtime' / 'data'
    data_dir.mkdir(parents=True)
    token = secrets.token_hex(24)
    (data_dir / '.ui-profiling').write_text(token)
    environment = os.environ.copy()
    # Clear inherited test overrides rather than allowing settings saves to
    # materialize them into the profiler's runtime configuration.
    for key in ('GAIA_SCAPE_HTTP_HOST', 'GAIA_SCAPE_HTTP_PORT', 'GAIA_SCAPE_OSC_HOST', 'GAIA_SCAPE_OSC_PORT'):
        environment.pop(key, None)
    if args.credentials_from is not None and args.mode == 'real':
        credential_path = args.credentials_from.expanduser().resolve()
        if credential_path.is_dir():
            credential_path /= 'data/config.json'
        credentials = json.loads(credential_path.read_text())
        for field in ('xeno_canto_api_key', 'eumetsat_consumer_key', 'eumetsat_consumer_secret'):
            if credentials.get(field):
                environment['UI_PROFILING_' + field.upper()] = credentials[field]
        fingerprints[str(credential_path)] = hashlib.sha256(credential_path.read_bytes()).hexdigest()
    environment['GAIA_SCAPE_DATA_DIR'] = str(data_dir)
    environment['UI_PROFILING_TOKEN'] = token
    environment['PYTHONPATH'] = str(ROOT / 'src')
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    command = [sys.executable, str(Path(__file__).resolve()), '--serve', '--mode', args.mode,
               '--port', str(port), '--interval-seconds', str(args.interval_seconds),
               '--recording-seconds', str(args.recording_seconds)]
    if args.fixture_silent_kind:
        command += ['--fixture-silent-kind', args.fixture_silent_kind]
    print(f'Profiling {args.mode}: {args.runs} complete pass(es); artifacts: {output}', flush=True)
    browser = None
    profiler = None
    with (output / 'server.log').open('w') as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(120):
                check_interrupted()
                if process.poll() is not None:
                    raise RuntimeError(f'Profiler server exited; see {output / "server.log"}')
                try:
                    with opener.open(base_url + '/healthz', timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(.25)
            else:
                raise RuntimeError('Isolated server did not become ready')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not args.headed, env=environment,
                    args=['--autoplay-policy=no-user-gesture-required'])
                context = browser.new_context(viewport={'width': 1500, 'height': 1000})
                context.add_init_script(AUDIO_METER)
                context.tracing.start(screenshots=True, snapshots=True)
                page = context.new_page()
                page.set_default_timeout(15000)
                profiler = Profiler(page, base_url, token, output, args)
                page.goto(base_url)
                identity = profiler.api('/__ui_profiling__/snapshot')
                if identity['data_dir'] != str(data_dir):
                    raise RuntimeError('Server does not belong to this profiling run')
                inventory = profiler.inventory()
                profiler.inventory_data = inventory
                write_json(output / 'inventory.json', inventory)
                has_key = args.mode == 'fixture' or bool(environment.get('UI_PROFILING_XENO_CANTO_API_KEY'))
                full_plan = build_settings_plan(inventory, build_plan(inventory, has_key))
                for case in full_plan:
                    if args.mode == 'real' and case.get('extra', {}).get('birdsongProvider') == 'xeno_canto' and not has_key:
                        case['skip'] = 'Xeno-canto credentials unavailable'
                    if args.mode == 'real' and case.get('extra', {}).get('sourceMtgLi') and not all(
                            environment.get('UI_PROFILING_' + field) for field in ('EUMETSAT_CONSUMER_KEY', 'EUMETSAT_CONSUMER_SECRET')):
                        case['skip'] = 'EUMETSAT credentials unavailable'
                plan = [case for case in full_plan if not args.case_filter or any(
                    case['case_id'].startswith(pattern) for pattern in args.case_filter)]
                if not plan:
                    raise RuntimeError('No cases matched the requested filter')
                write_json(output / 'plan.json', full_plan)
                minimum = sum(args.setting_dwell_seconds if case.get('short_check') else args.dwell_seconds for case in plan)
                print(f'{len(full_plan)} required cases per pass; minimum observation {minimum / 60:.1f} minutes plus activation time.', flush=True)
                write_json(output / 'report.json', profiler.report)
                page.locator('#playButton').click()
                deadline = time.monotonic() + args.minutes * 60 if args.minutes is not None else math.inf
                number = 0
                try:
                    while number < len(plan) * args.runs and time.monotonic() < deadline and (args.max_steps is None or number < args.max_steps):
                        check_interrupted()
                        step = plan[(args.start_step - 1 + number) % len(plan)]
                        number += 1
                        result = profiler.run_step(step, number)
                        result['pass_number'] = (number - 1) // len(plan) + 1
                        evidence = f'step-{number:04d}.json'
                        write_json(output / evidence, result)
                        compact = {key: value for key, value in result.items()
                                   if key not in ('samples', 'last_cues', 'errors', 'saved_settings')}
                        compact.update(evidence_file=evidence, sample_count=len(result.get('samples', [])),
                                       error_count=len(result.get('errors', [])))
                        profiler.report['steps'].append(compact)
                        profiler.report.pop('active_step', None)
                        write_json(output / 'report.json', profiler.report)
                        print(f'{number}: {step["case_id"]}: {result["outcome"]}'
                              f' ({result.get("reason", str(result.get("activation_seconds", "-")) + "s to activate")})', flush=True)
                        if result['outcome'] == 'failed' or args.trace_all:
                            context.tracing.stop(path=str(output / f'trace-{number:04d}.zip'))
                        else:
                            context.tracing.stop()
                        context.tracing.start(screenshots=True, snapshots=True)
                finally:
                    profiler.report['finished_at'] = time.time()
                    write_json(output / 'browser-errors.json', profiler.errors)
                    profiler.report['error_count'] = len(profiler.errors)
                    profiler.report['errors_file'] = 'browser-errors.json'
                    profiler.report['outcomes'] = {name: sum(s['outcome'] == name for s in profiler.report['steps'])
                                                   for name in ('passed', 'failed', 'skipped', 'blocked')}
                    profiler.report['interrupted'] = _STOP_REQUESTED
                    profiler.report['coverage_audit'] = coverage_audit(full_plan, profiler.report['steps'])
                    profiler.report['passes'] = [coverage_audit(full_plan, [row for row in profiler.report['steps']
                        if row.get('pass_number') == run]) for run in range(1, args.runs + 1)]
                    profiler.report['verification_complete'] = all(p['verification_complete'] for p in profiler.report['passes'])
                    write_json(output / 'report.json', profiler.report)
                    write_json(output / 'status.json', {'stage': 'interrupted' if _STOP_REQUESTED else 'finished',
                        'outcomes': profiler.report['outcomes'], 'verification_complete': profiler.report['verification_complete']})
                    context.tracing.stop(path=str(output / 'trace-final.zip'))
                    browser.close()
                    browser = None
        except KeyboardInterrupt:
            print('Profiling interrupted; partial report retained.', flush=True)
            return 130
        finally:
            if browser is not None and browser.is_connected():
                browser.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            isolated_config = data_dir / 'config.json'
            if isolated_config.exists():
                document = json.loads(isolated_config.read_text())
                for field in ('xeno_canto_api_key', 'eumetsat_consumer_key', 'eumetsat_consumer_secret'):
                    document[field] = ''
                write_json(isolated_config, document)
            for path, digest in fingerprints.items():
                current = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
                if current != digest:
                    if profiler is not None:
                        profiler.report.setdefault('external_configuration_changes', []).append(path)
                        write_json(output / 'report.json', profiler.report)
                    print(f'Notice: external configuration changed during the run: {path}', flush=True)
    return 1 if profiler is None or any(step['outcome'] in ('failed', 'blocked') for step in profiler.report['steps']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
