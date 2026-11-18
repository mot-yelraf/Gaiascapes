"""Profile a packaged Mac's Settings and animations through an isolated SSH run.

The remote app supplies Python and native WebKit. A separate fixture server,
browser storage, and data directory are created under /tmp; the running user
installation is never used as a test target.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import pickle
import plistlib
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import urllib.request


PANES = ('sources', 'instruments', 'locations', 'theme', 'history')
NAVIGATION_STATE = r'''(name) => {
 const dialog = document.getElementById('settingsDialog');
 const button = name ? dialog.querySelector(`[data-settings-pane="${name}"]`)
                     : document.querySelector('[data-open-settings]');
 const r = button.getBoundingClientRect();
 const x = r.left + r.width / 2, y = r.top + r.height / 2;
 const hit = document.elementFromPoint(x, y);
 return {open: dialog.open, x, y, width: innerWidth, height: innerHeight,
  hit: hit ? {tag:hit.tagName, id:hit.id, classes:hit.className,
             text:hit.textContent.trim().slice(0,100)} : null,
  panes: Array.from(dialog.querySelectorAll('[data-pane]'), p => ({
    name:p.dataset.pane, hidden:p.hidden, display:getComputedStyle(p).display})),
  selected: Array.from(dialog.querySelectorAll('[data-settings-pane].is-active'),
                       b => b.dataset.settingsPane),
  errors: globalThis.__profileNavigationErrors || [],
  pointerEvents: globalThis.__profilePointerEvents || []};
}'''


def pane_is_active(state, name):
    """Require the selected tab and its sole visible panel to agree."""
    visible = [pane['name'] for pane in state['panes']
               if not pane['hidden'] and pane['display'] != 'none']
    return state['open'] and state['selected'] == [name] and visible == [name]


def animation_probe(javascript):
    """Render silent synthetic cues and verify gradients and animation progress."""
    javascript('''(()=>{
      const dialog=document.getElementById('settingsDialog');
      if(dialog.open) dialog.close();
      document.body.classList.remove('modal-open');
      const filter=document.getElementById('backgroundEvents');
      filter.value='both';filter.dispatchEvent(new Event('change'));
      return true;})()''')
    cases = []
    snapshot = '''(()=>Array.from(document.querySelectorAll('.event-wave'),wave=>{
      const s=getComputedStyle(wave),r=wave.getBoundingClientRect();
      return {role:wave.dataset.cueRole,paint:wave.classList.contains('event-wave--paint'),
        background:s.backgroundImage,display:s.display,opacity:Number(s.opacity),
        width:r.width,height:r.height,transform:s.transform,
        animation:s.animationName};}))()'''
    for shape in ('burst', 'bloom', 'watercolor', 'ribbon'):
        javascript('''(shape=>{
          const change=mode=>{
            const input=document.querySelector(`input[name="backgroundAnimation"][value="${mode}"]`);
            input.checked=true;input.dispatchEvent(new Event('change'));
          };
          change('burst');
          document.querySelectorAll('.event-wave').forEach(wave=>wave.remove());
          const select=document.getElementById('backgroundPaintShape');
          select.value=shape==='burst'?'bloom':shape;
          select.dispatchEvent(new Event('change'));
          if(shape!=='burst') change('paint');
          for(const [kind,role] of [['ocean_swell','background'],['earthquake','event']])
            animateCapturedEvent({kind,latitude:15,longitude:30,strength:3,traits:{}},'',role,3.6,1);
          return true;})(%s)''' % json.dumps(shape))
        time.sleep(.2)
        before = javascript(snapshot)
        time.sleep(.3 if shape == 'burst' else 1.1)
        after = javascript(snapshot)
        visible = (len(after) == 2 and all(wave['display'] != 'none'
                   and wave['background'] != 'none' and wave['opacity'] > 0
                   and wave['width'] > 0 and wave['height'] > 0 for wave in after))
        progressing = (len(before) == len(after) == 2 and any(
            first['transform'] != last['transform'] or first['opacity'] != last['opacity']
            for first, last in zip(before, after)))
        retained = shape == 'burst' or any(wave['role'] == 'background' and wave['paint'] for wave in after)
        cases.append({'shape': shape, 'before': before, 'after': after,
                      'passed': visible and progressing and retained})
    javascript('''(()=>{
      const input=document.querySelector('input[name="backgroundAnimation"][value="murmuration"]');
      input.checked=true;input.dispatchEvent(new Event('change'));return true;})()''')
    time.sleep(.4)
    canvas = javascript('''(()=>{
      const c=document.querySelector('.murmuration-canvas');
      if(!c) return {paintedPixels:0};
      const pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let painted=0;for(let i=3;i<pixels.length;i+=4) if(pixels[i]) painted++;
      return {width:c.width,height:c.height,paintedPixels:painted};})()''')
    cases.append({'shape': 'murmuration', 'canvas': canvas, 'passed': canvas['paintedPixels'] > 0})
    return cases


def verify_runtime_identity(identity, data):
    """Reject production endpoints while accepting macOS temporary-path aliases."""
    if identity.get('mode') != 'fixture' or Path(identity.get('data_dir', '')).resolve() != data.resolve():
        raise RuntimeError('Refusing to test an unowned runtime')


def birdsong_decode_probe(javascript, filenames):
    """Decode each staged MP3 with an offline context that cannot emit sound."""
    javascript('''(files=>{
      globalThis.__birdsongDecode={done:false,results:[]};
      const Decoder=globalThis.OfflineAudioContext||globalThis.webkitOfflineAudioContext;
      const context=new Decoder(1,1,44100);
      (async()=>{
        for(const file of files) {
          try {
            const response=await fetch('/birdsong-media/'+encodeURIComponent(file));
            if(!response.ok) throw new Error('HTTP '+response.status);
            const buffer=await context.decodeAudioData(await response.arrayBuffer());
            if(!buffer.length||!Number.isFinite(buffer.duration)) throw new Error('No decoded samples');
            __birdsongDecode.results.push({file,passed:true,duration:buffer.duration,
              channels:buffer.numberOfChannels,sampleRate:buffer.sampleRate});
          } catch(error) {__birdsongDecode.results.push({file,passed:false,error:String(error)});}
        }
        __birdsongDecode.done=true;
      })();return true;})(%s)''' % json.dumps(filenames))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = javascript('globalThis.__birdsongDecode')
        if state['done']:
            return state
        time.sleep(.25)
    raise RuntimeError('Offline birdsong decoding timed out')


def prepare_native_launch(spec, helper):
    """Create a private LaunchServices wrapper without changing login settings."""
    root = Path(spec['root']).resolve()
    if not root.name.startswith('gaiascapes-ui-profile.') or not root.is_dir():
        raise RuntimeError('Remote launch requires its own temporary workspace')
    source = ('import runpy; ns=runpy.run_path(' + repr(str(root / 'scripts/ui_profile_remote.py'))
              + "); ns['native_navigation_probe'](" + repr(spec) + ')')
    payload = root / 'native-input.pickle'
    payload.write_bytes(pickle.dumps(('function', 'builtins', 'exec', (source,), {})))
    app = root / 'UIProfiler.app/Contents'
    executable = app / 'MacOS/UIProfiler'
    executable.parent.mkdir(parents=True)
    (app / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable': 'UIProfiler', 'CFBundleName': 'Gaiascapes UI Profiler',
        'CFBundleIdentifier': 'earth.gaiascape.UIProfiler.' + spec['token'][:16],
        'CFBundlePackageType': 'APPL', 'NSHighResolutionCapable': True,
    }))
    executable.write_text('#!/bin/sh\nexec env GAIA_SCAPE_DATA_DIR='
        + shlex.quote(str(root / 'runtime/data')) + ' TMPDIR=' + shlex.quote(str(root))
        + ' ' + shlex.quote(helper) + ' --worker < ' + shlex.quote(str(payload))
        + ' > ' + shlex.quote(str(root / 'native-result.bin'))
        + ' 2> ' + shlex.quote(str(root / 'native.log')) + '\n')
    executable.chmod(0o700)


def fingerprint(path):
    """Read a configuration fingerprint without including its contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def process_identity(pid):
    """Distinguish a profiler-owned process from any later reuse of its PID."""
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=,command='],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def stop_owned_processes(root, token):
    """Stop only processes recorded by this private profiling session."""
    record = root / 'owned-processes.json'
    if not record.is_file():
        return
    ownership = json.loads(record.read_text())
    if ownership['token'] != token:
        raise RuntimeError('Remote profiling ownership token does not match')
    for item in reversed(ownership['processes']):
        pid = item['pid']
        if pid <= 1 or pid == os.getpid() or process_identity(pid) != item['identity']:
            continue
        try:
            if item['group']:
                os.killpg(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def native_navigation_probe(spec):
    """Exercise real WebKit pointer events against a fresh fixture runtime."""
    import AppKit
    import Foundation
    import WebKit
    from PyObjCTools import AppHelper

    root = Path(spec['root']).resolve()
    token = spec['token']
    if not root.name.startswith('gaiascapes-ui-profile.') or not root.is_dir():
        raise RuntimeError('Remote profiler requires its own temporary workspace')
    os.umask(0o077)
    data = root / 'runtime/data'
    data.mkdir(parents=True)
    (data / '.ui-profiling').write_text(token)
    if spec.get('birdsong_files'):
        media = data / 'media/birdsong'
        media.mkdir(parents=True)
        for name in spec['birdsong_files']:
            shutil.copy2(root / 'approved-birdsong' / name, media / name)
    installed = Path.home() / 'Gaiascapes/data/config.json'
    before = fingerprint(installed)
    ownership = {'token': token, 'processes': [
        {'pid': os.getpid(), 'identity': process_identity(os.getpid()), 'group': False}]}
    ownership_file = root / 'owned-processes.json'
    ownership_file.write_text(json.dumps(ownership))
    report = {'scope': 'remote native WebKit Settings navigation',
              'mode': 'fixture', 'data_dir': str(data), 'steps': [],
              'started_at': time.time(), 'verification_complete': False,
              'full_settings_coverage': False}
    if spec.get('check_animations'):
        report['scope'] = 'remote native WebKit Settings navigation and silent animation rendering'
    if spec.get('birdsong_files'):
        report['scope'] += ' with offline birdsong decoding'
    if spec.get('candidate_script'):
        report['candidate_script_sha256'] = fingerprint(root / 'candidate-app.js')
    if spec.get('candidate_stylesheet'):
        report['candidate_stylesheet_sha256'] = fingerprint(root / 'candidate-app.css')

    def checkpoint(stage):
        report['stage'] = stage
        (root / 'report.json').write_text(json.dumps(report, indent=2))

    checkpoint('starting-server')
    environment = os.environ.copy()
    for key in ('GAIA_SCAPE_HTTP_HOST', 'GAIA_SCAPE_HTTP_PORT',
                'GAIA_SCAPE_OSC_HOST', 'GAIA_SCAPE_OSC_PORT'):
        environment.pop(key, None)
    environment.update(GAIA_SCAPE_DATA_DIR=str(data), UI_PROFILING_TOKEN=token,
                       TMPDIR=str(root))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    report['base_url'] = base_url
    server_arguments = ['--serve', '--mode', 'fixture', '--port', str(port)]
    if spec.get('candidate_script'):
        server_arguments += ['--navigation-script', str(root / 'candidate-app.js')]
    if spec.get('candidate_stylesheet'):
        server_arguments += ['--navigation-stylesheet', str(root / 'candidate-app.css')]
    server_script = ("import runpy; ns=runpy.run_path(" + repr(str(root / 'scripts/ui_profiling.py')) + "); "
                     "args=ns['parser']().parse_args(" + repr(server_arguments) + "); ns['serve'](args)")
    payload = pickle.dumps(('function', 'builtins', 'exec', (server_script,), {}))
    server = None
    with (root / 'server.log').open('wb') as log:
        try:
            server = subprocess.Popen([sys.executable, '--worker'], env=environment,
                                      stdin=subprocess.PIPE, stdout=log, stderr=log,
                                      start_new_session=True)
            ownership['processes'].append({'pid': server.pid,
                'identity': process_identity(server.pid), 'group': True})
            ownership_file.write_text(json.dumps(ownership))
            server.stdin.write(payload)
            server.stdin.close()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            ready = False
            for _ in range(100):
                if server.poll() is not None:
                    break
                try:
                    request = urllib.request.Request(base_url + '/__ui_profiling__/snapshot',
                        headers={'X-UI-Profiling-Token': token})
                    with opener.open(request, timeout=1) as response:
                        identity = json.load(response)
                    verify_runtime_identity(identity, data)
                    ready = True
                    break
                except OSError:
                    time.sleep(.2)
            if not ready:
                raise RuntimeError('Remote fixture server did not become ready; see server.log')
            checkpoint('server-ready')
            report['app_version'] = opener.open(base_url + '/healthz', timeout=5).read().decode()
            application = AppKit.NSApplication.sharedApplication()
            application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                ((100, 100), (1100, 800)),
                AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable |
                AppKit.NSWindowStyleMaskResizable,
                AppKit.NSBackingStoreBuffered, False)
            window.setReleasedWhenClosed_(False)
            window.setTitle_('Gaiascapes isolated UI profiler')
            configuration = WebKit.WKWebViewConfiguration.alloc().init()
            configuration.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
            view = WebKit.WKWebView.alloc().initWithFrame_configuration_(
                ((0, 0), (1100, 800)), configuration)
            window.setContentView_(view)
            view.loadRequest_(Foundation.NSURLRequest.requestWithURL_(
                Foundation.NSURL.URLWithString_(base_url)))
            window.makeKeyAndOrderFront_(None)
            application.activateIgnoringOtherApps_(True)
            application.finishLaunching()
            finished = threading.Event()

            def javascript(script):
                done = threading.Event()
                result = []
                failure = []

                def complete(value, error):
                    try:
                        if error is not None:
                            failure.append(str(error))
                        else:
                            result.append(json.loads(str(value)))
                    except Exception as exc:
                        failure.append(str(exc))
                    finally:
                        done.set()

                def dispatch():
                    try:
                        view.evaluateJavaScript_completionHandler_(
                            'JSON.stringify(' + script + ')', complete)
                    except Exception as exc:
                        failure.append(str(exc))
                        done.set()
                AppHelper.callAfter(dispatch)
                if not done.wait(10):
                    raise RuntimeError('Native WebKit JavaScript evaluation timed out')
                if failure:
                    raise RuntimeError(failure[0])
                return result[0]

            def evaluate(function, argument):
                return javascript('(' + function + ')(' + json.dumps(argument) + ')')

            def click(state):
                done = threading.Event()
                failure = []

                def send():
                    try:
                        native = window
                        point = view.convertPoint_toView_((state['x'], state['y']), None)
                        for event_type in (AppKit.NSLeftMouseDown, AppKit.NSLeftMouseUp):
                            event = AppKit.NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
                                event_type, point, 0,
                                time.monotonic(), native.windowNumber(), None, 1, 1, 1.0)
                            if event_type == AppKit.NSLeftMouseDown:
                                view.mouseDown_(event)
                            else:
                                view.mouseUp_(event)
                    except Exception as exc:
                        failure.append(str(exc))
                    finally:
                        done.set()
                AppHelper.callAfter(send)
                if not done.wait(10):
                    raise RuntimeError('Native pointer event timed out')
                if failure:
                    raise RuntimeError(failure[0])

            def checks():
                try:
                    checkpoint('waiting-for-document')
                    deadline = time.monotonic() + 15
                    while not javascript("document.readyState === 'complete' && !!document.getElementById('settingsDialog')"):
                        if time.monotonic() >= deadline:
                            raise RuntimeError('Remote document did not finish loading')
                        time.sleep(.1)
                    javascript('''(()=>{globalThis.__profileNavigationErrors=[];
                      globalThis.__profilePointerEvents=[];
                      for(const type of ['mousedown','mouseup','click']) addEventListener(type,e=>
                        __profilePointerEvents.push({type,x:e.clientX,y:e.clientY,
                          target:e.target.id||e.target.tagName}),true);
                      addEventListener('error',e=>__profileNavigationErrors.push(e.message));
                      addEventListener('unhandledrejection',e=>__profileNavigationErrors.push(String(e.reason)));
                      return true;})()''')
                    report['graphics'] = javascript('''(()=>{
                      const result={colorMix:CSS.supports('color','color-mix(in srgb, red 50%, transparent)'),
                        reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches,
                        shapes:[]};
                      for(const shape of ['burst','bloom','watercolor','ribbon']) {
                        const wave=document.createElement('span');
                        wave.className='event-wave'+(shape==='burst'?'':' event-wave--paint');
                        wave.dataset.paintShape=shape;
                        wave.style.setProperty('--wave-color','#269eaa');
                        wave.style.setProperty('--wave-inner','#7954bf');
                        document.getElementById('eventPulseLayer').append(wave);
                        const style=getComputedStyle(wave);
                        result.shapes.push({shape,background:style.backgroundImage,
                          display:style.display,width:style.width,height:style.height,
                          animation:style.animationName});
                        wave.remove();
                      }
                      return result;})()''')
                    report['audio_codecs'] = javascript('''(()=>{
                      const audio=document.createElement('audio');
                      return Object.fromEntries(['audio/mpeg','audio/ogg; codecs="vorbis"',
                        'audio/ogg; codecs="opus"','audio/wav'].map(type=>[type,audio.canPlayType(type)]));
                      })()''')
                    report['opening_button'] = evaluate(NAVIGATION_STATE, None)
                    click(report['opening_button'])
                    deadline = time.monotonic() + 3
                    while not evaluate(NAVIGATION_STATE, 'sources')['open']:
                        if time.monotonic() >= deadline:
                            report['opening_failure'] = evaluate(NAVIGATION_STATE, 'sources')
                            raise RuntimeError('Native Settings button did not open its dialog')
                        time.sleep(.1)
                    for name in PANES:
                        before_click = evaluate(NAVIGATION_STATE, name)
                        click(before_click)
                        after = evaluate(NAVIGATION_STATE, name)
                        deadline = time.monotonic() + 2
                        while not pane_is_active(after, name) and time.monotonic() < deadline:
                            time.sleep(.1)
                            after = evaluate(NAVIGATION_STATE, name)
                        step = {'pane': name, 'before': before_click, 'after': after,
                                'passed': pane_is_active(after, name)}
                        if not step['passed']:
                            javascript("(()=>{document.querySelector('[data-settings-pane="
                                + json.dumps(name) + "]').click();return true;})()")
                            step['programmatic_click'] = evaluate(NAVIGATION_STATE, name)
                        report['steps'].append(step)
                        checkpoint('navigation/' + name)
                    report['verification_complete'] = (len(report['steps']) == len(PANES)
                        and all(step['passed'] and not step['after']['errors'] for step in report['steps']))
                    report['browser'] = javascript('navigator.userAgent')
                    if spec.get('check_animations'):
                        report['animation_checks'] = animation_probe(javascript)
                        report['verification_complete'] = (report['verification_complete']
                            and all(case['passed'] for case in report['animation_checks']))
                    if spec.get('birdsong_files'):
                        report['birdsong_decode'] = birdsong_decode_probe(javascript, spec['birdsong_files'])
                        decoded = report['birdsong_decode']['results']
                        report['verification_complete'] = (report['verification_complete']
                            and len(decoded) == len(spec['birdsong_files'])
                            and all(case['passed'] for case in decoded))
                except Exception:
                    report['verification_complete'] = False
                    report['error'] = traceback.format_exc()
                finally:
                    checkpoint('closing-native-window')
                    finished.set()

            checkpoint('starting-native-window')
            threading.Thread(target=checks, daemon=True).start()
            while not finished.is_set():
                event = application.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    AppKit.NSEventMaskAny, Foundation.NSDate.dateWithTimeIntervalSinceNow_(.1),
                    Foundation.NSDefaultRunLoopMode, True)
                if event is not None:
                    application.sendEvent_(event)
            window.close()
        except Exception:
            report['verification_complete'] = False
            report['error'] = traceback.format_exc()
        finally:
            if server is not None and server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait()
            report['installed_config_unchanged'] = fingerprint(installed) == before
            if not report['installed_config_unchanged']:
                report['verification_complete'] = False
            report['finished_at'] = time.time()
            report['stage'] = 'finished'
            (root / 'report.json').write_text(json.dumps(report, indent=2))


def run_remote_navigation(args):
    """Stage a private remote probe, retrieve evidence, and reap owned processes."""
    if args.ssh_host.startswith('-') or any(c.isspace() for c in args.ssh_host):
        raise ValueError('SSH host must be a single hostname or configured alias')
    app = Path(args.remote_app)
    if not app.is_absolute() or app.suffix != '.app':
        raise ValueError('--remote-app must be an absolute macOS application path')
    candidate = getattr(args, 'navigation_script', None)
    if candidate:
        candidate = candidate.expanduser().resolve(strict=True)
        if not candidate.is_file():
            raise ValueError('--navigation-script must name a JavaScript file')
    stylesheet = getattr(args, 'navigation_stylesheet', None)
    if stylesheet:
        stylesheet = stylesheet.expanduser().resolve(strict=True)
        if not stylesheet.is_file():
            raise ValueError('--navigation-stylesheet must name a CSS file')
    audio_directory = getattr(args, 'check_birdsong_media', None)
    audio_files = sorted(audio_directory.expanduser().resolve(strict=True).glob('*.mp3')) if audio_directory else []
    if audio_directory and (not audio_files or len(audio_files) > 128
                            or any(not path.is_file() for path in audio_files)):
        raise ValueError('--check-birdsong-media requires 1 to 128 MP3 copies')
    output = args.output.expanduser().resolve() if args.output else Path(
        tempfile.mkdtemp(prefix='gaiascapes-remote-ui-'))
    if args.output:
        output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.ssh_host]
    root_text = subprocess.check_output(ssh + ['mktemp -d /tmp/gaiascapes-ui-profile.XXXXXX'], text=True).strip()
    root = Path(root_text)
    if root.parent != Path('/tmp') or not root.name.startswith('gaiascapes-ui-profile.'):
        raise RuntimeError('SSH did not return an owned temporary workspace')
    token = secrets.token_hex(24)
    spec = {'root': str(root), 'token': token, 'candidate_script': bool(candidate),
            'candidate_stylesheet': bool(stylesheet),
            'birdsong_files': [path.name for path in audio_files],
            'check_animations': getattr(args, 'check_animations', False)}
    staging = io.BytesIO()
    with tarfile.open(fileobj=staging, mode='w') as archive:
        for name in ('ui_profiling.py', 'ui_profile_settings.py', 'ui_profile_remote.py'):
            archive.add(Path(__file__).with_name(name), arcname='scripts/' + name)
        if candidate:
            archive.add(candidate, arcname='candidate-app.js')
        if stylesheet:
            archive.add(stylesheet, arcname='candidate-app.css')
        for audio_file in audio_files:
            archive.add(audio_file, arcname='approved-birdsong/' + audio_file.name)
    subprocess.run(ssh + ['tar -xf - -C ' + shlex.quote(str(root))],
                   input=staging.getvalue(), check=True, timeout=30)
    helper = str(app / 'Contents/MacOS/gaiascapes-runtime')
    command = ('env GAIA_SCAPE_DATA_DIR=' + shlex.quote(str(root / 'runtime/data'))
               + ' TMPDIR=' + shlex.quote(str(root)) + ' ' + shlex.quote(helper) + ' --worker')
    entry = str(root / 'scripts/ui_profile_remote.py')
    source = ('import runpy; ns=runpy.run_path(' + repr(entry)
              + "); ns['prepare_native_launch'](" + repr(spec) + ', ' + repr(helper) + ')')
    payload = pickle.dumps(('function', 'builtins', 'exec', (source,), {}))
    print(f'Remote native Settings profile: {args.ssh_host}; private workspace {root}; report {output}', flush=True)
    failure = None
    evidence_errors = []
    try:
        subprocess.run(ssh + [command], input=payload, stdout=subprocess.DEVNULL,
                       check=True, timeout=30)
        with (output / 'remote.log').open('wb') as log:
            subprocess.run(ssh + ['open -n -W ' + shlex.quote(str(root / 'UIProfiler.app'))],
                           stdout=subprocess.DEVNULL,
                           stderr=log, timeout=150, check=True)
    except (Exception, KeyboardInterrupt) as exc:
        failure = exc
    finally:
        cleanup = ('import runpy; ns=runpy.run_path(' + repr(entry) +
                   "); ns['stop_owned_processes'](ns['Path'](" + repr(str(root)) + '), ' + repr(token) + ')')
        try:
            subprocess.run(ssh + [command], input=pickle.dumps(
                ('function', 'builtins', 'exec', (cleanup,), {})), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=30, check=True)
        except Exception as exc:
            evidence_errors.append('Remote process cleanup failed: ' + str(exc))
        for name in ('report.json', 'server.log', 'native.log'):
            try:
                evidence = subprocess.run(ssh + ['cat ' + shlex.quote(str(root / name))],
                                          capture_output=True, timeout=30, check=True)
                (output / name).write_bytes(evidence.stdout)
            except Exception as exc:
                evidence_errors.append('Could not retrieve ' + name + ': ' + str(exc))
    report_path = output / 'report.json'
    report = json.loads(report_path.read_text()) if report_path.is_file() else {'verification_complete': False}
    if failure is not None or evidence_errors:
        report.update(verification_complete=False, controller_error=str(failure) if failure else None,
                      evidence_errors=evidence_errors)
        report_path.write_text(json.dumps(report, indent=2))
    print('Remote navigation:', 'passed' if report['verification_complete'] else 'failed', flush=True)
    if isinstance(failure, KeyboardInterrupt):
        return 130
    return 0 if report['verification_complete'] else 1
