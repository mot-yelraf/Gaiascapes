"""Exercise Windows installation and repair in a disposable installation.

CI invokes the real PowerShell installer with paths containing spaces and
checks shortcut targets, data preservation, and the installed offline web API.
All application state and shortcuts stay beneath the supplied temporary root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    """Install, repair, and verify a disposable Windows application."""
    root = Path(os.environ['GAIA_SCAPE_DATA_DIR'])
    if os.name != 'nt' or not root.is_dir() or any(root.iterdir()):
        raise RuntimeError('Requires Windows and a new, empty GAIA_SCAPE_DATA_DIR')
    source = Path(__file__).resolve().parents[1]
    runtime = root / 'installed app'
    shortcuts = root / 'desktop shortcuts'
    data_dir = runtime / 'data'
    data_dir.mkdir(parents=True)
    sentinel = data_dir / 'preserve-me.txt'
    sentinel.write_text('existing history', encoding='utf-8')
    config_path = data_dir / 'config.json'
    config = {'http_port': 8768, 'osc_port': 57130, 'enabled_sources': [], 'osc_enabled': False}
    config_path.write_text(json.dumps(config), encoding='utf-8')
    saved_config = config_path.read_bytes()
    environment = dict(os.environ, GAIA_SCAPE_DATA_DIR=str(data_dir),
                       GAIA_SCAPE_HTTP_PORT='18868', GAIA_SCAPE_OSC_PORT='19130')

    def powershell(script: Path, *args: str) -> None:
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(script), *args], env=environment, check=True)

    powershell(source / 'install.ps1', '-InstallDir', str(runtime), '-Mode', 'Headless',
               '-Python', sys.executable, '-ShortcutDirectory', str(shortcuts))
    assert config_path.read_bytes() == saved_config
    assert sentinel.read_text(encoding='utf-8') == 'existing history'
    assert (data_dir / 'install-mode').read_text() == 'headless'
    assert Path((data_dir / 'install-source').read_text()) == source

    # Use the installed copy without mode or destination arguments: repair
    # must preserve both and must not save process-local test port overrides.
    powershell(runtime / 'install.ps1', '-Python', sys.executable, '-NoShortcut')
    assert config_path.read_bytes() == saved_config
    assert sentinel.read_text(encoding='utf-8') == 'existing history'
    assert (data_dir / 'install-mode').read_text() == 'headless'

    shortcut_check = root / 'check-shortcuts.ps1'
    shortcut_check.write_text('''
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @('Gaiascapes', 'Gaiascapes Audio')) {
    $link = $shell.CreateShortcut((Join-Path $env:GAIA_TEST_SHORTCUTS "$name.lnk"))
    if ($link.WorkingDirectory -ne $env:GAIA_TEST_RUNTIME) { throw 'Wrong shortcut directory' }
    $launcher = Join-Path $env:GAIA_TEST_RUNTIME 'scripts\\run_gaiascapes.ps1'
    if (-not $link.Arguments.Contains('"' + $launcher + '"')) { throw 'Unquoted shortcut path' }
    $mode = if ($name -eq 'Gaiascapes') { 'Server' } else { 'Audio' }
    if (-not $link.Arguments.Contains('-Mode ' + $mode)) { throw 'Wrong shortcut mode' }
}
''', encoding='utf-8')
    environment.update(GAIA_TEST_SHORTCUTS=str(shortcuts), GAIA_TEST_RUNTIME=str(runtime))
    powershell(shortcut_check)
    powershell(runtime / 'scripts/run_gaiascapes.ps1', '-Mode', 'Server', '--help')
    assert config_path.read_bytes() == saved_config

    python = runtime / '.venv/Scripts/python.exe'
    subprocess.run([str(python), '-m', 'pip', 'install', 'httpx'], check=True)
    offline_check = root / 'check-installed.py'
    offline_check.write_text('''
from fastapi.testclient import TestClient
from gaiascapes_host.app import create_app
from gaiascapes_host.config import resolve_data_dir
from gaiascapes import __version__
import os
from pathlib import Path
assert resolve_data_dir() == Path(os.environ['GAIA_SCAPE_DATA_DIR']).resolve()
with TestClient(create_app(auto_capture=False)) as client:
    assert client.get('/healthz').json()['version'] == __version__
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/events').json() == {'events': []}
    assert client.post('/api/capture').json()['disabled'] is True
''', encoding='utf-8')
    environment.pop('GAIA_SCAPE_HTTP_PORT')
    environment.pop('GAIA_SCAPE_OSC_PORT')
    environment.pop('PYTHONPATH', None)
    subprocess.run([str(python), str(offline_check)], cwd=root, env=environment, check=True)
    saved = json.loads(config_path.read_text())
    assert saved['http_port'] == 8768 and saved['osc_port'] == 57130
    print('Windows installation, repair, shortcuts, and installed offline APIs passed')


if __name__ == '__main__':
    main()
