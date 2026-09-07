"""Smoke-test an installed headless wheel outside the source import path.

CI runs this in a clean virtual environment without desktop or lightning
extras. The caller must provide a newly created, empty runtime directory.
"""

import importlib.util
from importlib.metadata import distribution, version
import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    """Verify installed assets, entry points, version, and offline HTTP routes."""
    data_dir = Path(os.environ['GAIA_SCAPE_DATA_DIR'])
    if not data_dir.is_dir() or any(data_dir.iterdir()):
        raise RuntimeError('Smoke test requires a new, empty GAIA_SCAPE_DATA_DIR')
    for dependency in ('webview', 'netCDF4', 'eumdac'):
        assert importlib.util.find_spec(dependency) is None, dependency

    from fastapi.testclient import TestClient
    from gaiascapes import __version__
    from gaiascapes_host.app import create_app
    from gaiascapes_host.config import AppConfig

    assert version('gaiascapes') == __version__.removeprefix('v')
    package = distribution('gaiascapes')
    assert package.metadata['License-Expression'] == 'BSD-2-Clause'
    license_files = package.metadata.get_all('License-File') or []
    assert {'LICENSE', 'THIRD_PARTY_NOTICES.md'} <= set(license_files)
    for notice in license_files:
        assert any(str(path).endswith('/licenses/' + notice) for path in package.files)

    AppConfig(enabled_sources=[], osc_enabled=False).save(data_dir / 'config.json')
    with TestClient(create_app(auto_capture=False)) as client:
        assert client.get('/healthz').json()['version'] == __version__
        assert client.get('/').status_code == 200
        assert client.get('/static/app.js').status_code == 200
        assert client.get('/api/events').json() == {'events': []}
        assert client.post('/api/capture').json()['disabled'] is True
    launcher = Path(sys.executable).parent / 'gaiascapes-server'
    subprocess.run([str(launcher), '--help'], cwd=data_dir, check=True, capture_output=True)
    print(f'Headless wheel {__version__}: assets, entry point, and offline APIs passed')


if __name__ == '__main__':
    main()
