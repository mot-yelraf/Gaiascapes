"""Protect remote UI profiling ownership and navigation evidence.

No test connects to SSH or opens a window. The native end-to-end probe uses its
own marked data directory and is explicitly invoked by the profiling CLI.
"""

import json
from pathlib import Path
import plistlib
import runpy
import signal
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
REMOTE = runpy.run_path(str(ROOT / 'scripts/ui_profile_remote.py'))
PROFILE = runpy.run_path(str(ROOT / 'scripts/ui_profiling.py'))


def test_navigation_requires_one_visible_panel_and_matching_selection():
    state = {'open': True, 'selected': ['theme'], 'panes': [
        {'name': 'sources', 'hidden': True, 'display': 'none'},
        {'name': 'theme', 'hidden': False, 'display': 'block'}]}
    active = REMOTE['pane_is_active']
    assert active(state, 'theme')
    assert not active(state, 'sources')
    assert not active({**state, 'open': False}, 'theme')
    assert not active({**state, 'selected': ['sources']}, 'theme')
    state['panes'][0].update(hidden=False, display='block')
    assert not active(state, 'theme')


def test_remote_identity_accepts_only_the_owned_fixture_directory(tmp_path):
    owned = tmp_path / 'owned/data'
    owned.mkdir(parents=True)
    alias = tmp_path / 'alias'
    alias.symlink_to(owned, target_is_directory=True)
    verify = REMOTE['verify_runtime_identity']
    verify({'mode': 'fixture', 'data_dir': str(alias)}, owned)
    for identity in ({'mode': 'real', 'data_dir': str(owned)},
                     {'mode': 'fixture', 'data_dir': str(tmp_path / 'installed/data')}):
        with pytest.raises(RuntimeError, match='unowned runtime'):
            verify(identity, owned)


def test_private_native_launcher_keeps_state_under_owned_workspace(tmp_path):
    root = tmp_path / 'gaiascapes-ui-profile.test'
    root.mkdir()
    spec = {'root': str(root), 'token': 'private-session-token'}
    REMOTE['prepare_native_launch'](spec, '/Applications/Test App.app/Contents/MacOS/gaiascapes-runtime')
    contents = root / 'UIProfiler.app/Contents'
    info = plistlib.loads((contents / 'Info.plist').read_bytes())
    assert info['CFBundleName'] == 'Gaiascapes UI Profiler'
    script = contents / 'MacOS/UIProfiler'
    assert script.stat().st_mode & 0o777 == 0o700
    assert str(root / 'runtime/data') in script.read_text()
    assert '--worker < ' in script.read_text()
    assert not (root / 'runtime/data/config.json').exists()
    with pytest.raises(RuntimeError, match='temporary workspace'):
        REMOTE['prepare_native_launch']({'root': str(tmp_path), 'token': 'other'}, '/app')


def test_remote_cleanup_rejects_wrong_token_and_reused_process_ids(tmp_path, monkeypatch):
    function = REMOTE['stop_owned_processes']
    ownership = {'token': 'session', 'processes': [
        {'pid': 999991, 'identity': 'original', 'group': False},
        {'pid': 999992, 'identity': 'owned', 'group': True}]}
    (tmp_path / 'owned-processes.json').write_text(json.dumps(ownership))
    calls = []
    monkeypatch.setitem(function.__globals__, 'process_identity', lambda pid: 'owned' if pid == 999992 else 'reused')
    monkeypatch.setattr(function.__globals__['os'], 'killpg', lambda *args: calls.append(args))
    monkeypatch.setattr(function.__globals__['os'], 'kill', lambda *args: pytest.fail('Unowned process terminated'))
    with pytest.raises(RuntimeError, match='token does not match'):
        function(tmp_path, 'wrong')
    assert calls == []
    function(tmp_path, 'session')
    assert calls == [(999992, signal.SIGTERM)]


@pytest.mark.parametrize('arguments', [
    ['--ssh-host', 'harvest'], ['--navigation-only'],
    ['--ssh-host', 'harvest', '--navigation-only', '--mode', 'real'],
    ['--ssh-host', 'harvest', '--navigation-only', '--mode', 'fixture', '--credentials-from', '/private/config'],
])
def test_remote_cli_rejects_unsupported_or_nonisolated_modes(arguments):
    with pytest.raises(SystemExit, match='Remote navigation requires'):
        PROFILE['main'](arguments)


def test_remote_cli_delegates_without_loading_local_browser(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'ui_profile_remote', SimpleNamespace(
        run_remote_navigation=lambda args: calls.append(args) or 0))
    assert PROFILE['main'](['--ssh-host', 'harvest', '--remote-app', '/Volumes/Test App.app',
                            '--navigation-only', '--mode', 'fixture']) == 0
    assert len(calls) == 1
    assert calls[0].remote_app == '/Volumes/Test App.app'


def test_candidate_assets_are_served_only_by_private_fixture(tmp_path, monkeypatch):
    import uvicorn
    from fastapi.testclient import TestClient

    data = tmp_path / 'runtime/data'
    data.mkdir(parents=True)
    (data / '.ui-profiling').write_text('test-token')
    candidate = tmp_path / 'candidate-app.js'
    candidate.write_text('globalThis.candidateScript = true;')
    stylesheet = tmp_path / 'candidate-app.css'
    stylesheet.write_text('.event-wave { background: red; }')
    packaged = ROOT / 'src/gaiascapes_host/static/app.js'
    original = packaged.read_bytes()
    packaged_css = ROOT / 'src/gaiascapes_host/static/app.css'
    original_css = packaged_css.read_bytes()
    monkeypatch.setenv('GAIA_SCAPE_DATA_DIR', str(data))
    monkeypatch.setenv('UI_PROFILING_TOKEN', 'test-token')
    applications = []
    monkeypatch.setattr(uvicorn, 'run', lambda app, **kwargs: applications.append(app))
    args = PROFILE['parser']().parse_args([
        '--serve', '--mode', 'fixture', '--recording-seconds', '.1',
        '--navigation-script', str(candidate), '--navigation-stylesheet', str(stylesheet)])
    PROFILE['serve'](args)
    with TestClient(applications[0]) as client:
        response = client.get('/static/app.js')
        assert response.status_code == 200
        assert response.text == candidate.read_text()
        response = client.get('/static/app.css')
        assert response.status_code == 200
        assert response.text == stylesheet.read_text()
    assert packaged.read_bytes() == original
    assert packaged_css.read_bytes() == original_css


def test_candidate_script_requires_an_isolated_navigation_mode():
    with pytest.raises(SystemExit, match='requires a remote navigation check'):
        PROFILE['main'](['--navigation-script', 'candidate.js'])


@pytest.mark.parametrize('arguments', [['--navigation-stylesheet', 'candidate.css'], ['--check-animations'],
                                       ['--check-birdsong-media', '/tmp/media-copies']])
def test_animation_diagnostics_require_an_isolated_navigation_mode(arguments):
    with pytest.raises(SystemExit, match='requires a remote navigation check'):
        PROFILE['main'](arguments)


@pytest.mark.parametrize('host, app', [('-oProxyCommand=bad', '/Applications/Test.app'),
                                      ('bad host', '/Applications/Test.app'), ('harvest', 'relative.app')])
def test_remote_runner_rejects_unsafe_host_or_relative_app_before_ssh(host, app):
    with pytest.raises(ValueError):
        REMOTE['run_remote_navigation'](SimpleNamespace(ssh_host=host, remote_app=app))
