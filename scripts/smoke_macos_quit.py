"""Verify native macOS Quit reaps a packaged app's owned server and audio tree.

The app runs with private data and a silent stand-in renderer with a real child
process. Only pywebview's event-loop entry is replaced: the packaged launcher,
desktop cleanup, and macOS termination notification all run normally. No sound
hardware, installed settings, or installed processes are used as test targets.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import plistlib
import shlex
import signal
import socket
import subprocess
import tempfile
import time


PROBE = r'''
import json,os,subprocess,threading,time
from pathlib import Path
import webview
from AppKit import NSApplication,NSApplicationActivationPolicyAccessory,NSApplicationWillTerminateNotification
from Foundation import NSNotificationCenter
from PyObjCTools import AppHelper
from gaiascapes_host import bundled
from gaiascapes_host.config import AppConfig
root=Path(__PROBE_ROOT__)
data=root/'data'
data.mkdir()
for key in list(os.environ):
    if key.startswith('GAIA_SCAPE_'):
        os.environ.pop(key)
AppConfig(enabled_sources=[],system_location_enabled=False).save(data/'config.json')
os.environ.update(GAIA_SCAPE_DATA_DIR=str(data),GAIA_SCAPE_INSTALL_BIRDSONG='no',
                  GAIA_SCAPE_HTTP_HOST='127.0.0.1',GAIA_SCAPE_HTTP_PORT=str(__PROBE_PORT__),
                  GAIA_SCAPE_OSC_HOST='127.0.0.1',GAIA_SCAPE_OSC_PORT=str(__PROBE_OSC_PORT__),
                  GAIA_SCAPE_SCLANG=str(root/'renderer'))
def native_loop(*args,**kwargs):
    app=NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    app.finishLaunching()
    processes=[]
    for line in subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True).splitlines():
        fields=line.strip().split(None,2)
        if (len(fields)==3 and int(fields[1])==os.getpid()
                and (str(root/'renderer') in fields[2]
                     or ('gaiascapes-runtime' in fields[2] and '--server' in fields[2]))):
            processes.append({'pid':int(fields[0]),'command':fields[2]})
    audio_pids=[int(value) for value in (data/'renderer-pids').read_text().split()]
    for pid in audio_pids:
        if pid not in [item['pid'] for item in processes]:
            command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip()
            processes.append({'pid':pid,'command':command})
    for process in processes:
        process['identity']=subprocess.check_output(
            ['ps','-p',str(process['pid']),'-o','lstart=,command='],text=True).strip()
    (root/'owned.json').write_text(json.dumps(processes))
    center=NSNotificationCenter.defaultCenter()
    observer=center.addObserverForName_object_queue_usingBlock_(
        NSApplicationWillTerminateNotification,None,None,
        lambda notice:(root/'native-notification').write_text('received'))
    def quit_native():
        (root/'quit-requested').write_text('NSApplication.terminate')
        app.terminate_(None)
    threading.Timer(.5,lambda:AppHelper.callAfter(quit_native)).start()
    app.run()
webview.start=native_loop
bundled.main([])
'''


def process_identity(pid):
    """Read start time and command to avoid terminating a reused process ID."""
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=,command='],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    """Launch a disposable native Quit probe and report any surviving helpers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    helper = bundle / 'Contents/MacOS/gaiascapes-runtime'
    if not helper.is_file():
        parser.error('Bundle must contain gaiascapes-runtime')
    root = Path(tempfile.mkdtemp(prefix='gaiascapes-quit-smoke.')).resolve()
    os.chmod(root, 0o700)
    installed = Path.home() / 'Gaiascapes/data/config.json'
    before = hashlib.sha256(installed.read_bytes()).hexdigest() if installed.is_file() else None
    renderer = root / 'renderer'
    renderer.write_text('#!/bin/sh\n/bin/sleep 600 &\nchild=$!\n'
                        'printf "%s %s\\n" "$$" "$child" > "$GAIA_SCAPE_DATA_DIR/renderer-pids"\nwait "$child"\n')
    renderer.chmod(0o700)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', 0))
        osc_port = probe.getsockname()[1]
    source = (PROBE.replace('__PROBE_ROOT__', repr(str(root)))
              .replace('__PROBE_PORT__', repr(port)).replace('__PROBE_OSC_PORT__', repr(osc_port)))
    payload = root / 'input.pickle'
    payload.write_bytes(pickle.dumps(('function', 'builtins', 'exec',
                                     (source, {'__name__': '__quit_probe__'}), {})))
    contents = root / 'QuitProbe.app/Contents'
    executable = contents / 'MacOS/QuitProbe'
    executable.parent.mkdir(parents=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable': 'QuitProbe', 'CFBundleName': 'Gaiascapes Quit Probe',
        'CFBundleIdentifier': 'earth.gaiascape.quitprobe.' + root.name.rsplit('.', 1)[-1],
        'CFBundlePackageType': 'APPL',
    }))
    executable.write_text('#!/bin/sh\nexec env GAIA_SCAPE_DATA_DIR=' + shlex.quote(str(root / 'data'))
        + ' GAIA_SCAPE_INSTALL_BIRDSONG=no TMPDIR=' + shlex.quote(str(root)) + ' '
        + shlex.quote(str(helper)) + ' --worker < ' + shlex.quote(str(payload))
        + ' > ' + shlex.quote(str(root / 'result.bin'))
        + ' 2> ' + shlex.quote(str(root / 'native.log')) + '\n')
    executable.chmod(0o700)
    report = {'workspace': str(root), 'scope': 'native Quit with silent renderer process tree',
              'passed': False}
    owned = []
    try:
        subprocess.run(['open', '-n', '-W', str(contents.parent)], check=True, timeout=90)
        owned = json.loads((root / 'owned.json').read_text())
        # Allow launchd to reap exited grandchildren before checking for survivors.
        for _ in range(30):
            remaining = [item for item in owned if process_identity(item['pid']) == item['identity']]
            if not remaining:
                break
            time.sleep(.1)
        report.update(native_notification=(root / 'native-notification').is_file(),
                      quit_requested=(root / 'quit-requested').is_file(),
                      owned_process_count=len(owned), survivors=remaining)
        assert len(owned) == 3, 'Expected an owned server, renderer, and renderer child'
        config = json.loads((root / 'data/config.json').read_text())
        assert config['http_port'] == 8769 and config['osc_port'] == 57130, config
        report['passed'] = report['native_notification'] and report['quit_requested'] and not remaining
    finally:
        # Reap only the recorded probe processes, including an old buggy build's survivors.
        if not owned and (root / 'owned.json').is_file():
            owned = json.loads((root / 'owned.json').read_text())
        for item in owned:
            if process_identity(item['pid']) == item['identity']:
                try:
                    os.kill(item['pid'], signal.SIGTERM)
                except ProcessLookupError:
                    pass
        after = hashlib.sha256(installed.read_bytes()).hexdigest() if installed.is_file() else None
        report['installed_config_unchanged'] = before == after
        report['passed'] = report['passed'] and report['installed_config_unchanged']
        (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
