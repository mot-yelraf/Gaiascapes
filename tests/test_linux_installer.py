"""Verify Linux renderer installation without changing system packages.

Controlled shell functions simulate package tools, privileges, and executable
availability. All installer scenarios run against temporary test data.
"""

import os
from pathlib import Path
import shlex
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX installer")
HELPER = Path("scripts/linux_dependencies.sh").resolve()


@pytest.mark.parametrize("scenario", [
    "present", "install", "root", "skip", "no_apt", "no_sudo",
    "update_failed", "install_failed", "not_detected", "partial", "missing_pw_jack",
])
def test_linux_supercollider_installation(tmp_path, scenario):
    result = subprocess.run(
        ["bash", "-c", f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
scenario={scenario}
GAIA_SCAPE_INSTALL_SUPERCOLLIDER={'no' if scenario == 'skip' else 'yes'}
installed={'yes' if scenario in {'present', 'missing_pw_jack'} else 'no'}
command() {{
  if [[ "$1" == -v ]]; then
    case "$2" in
      sclang) [[ "$installed" == yes || "$scenario" == partial ]]; return ;;
      scsynth) [[ "$installed" == yes ]]; return ;;
      pw-jack) [[ "$installed" == yes && "$scenario" != missing_pw_jack || "$scenario" == fixed_pw_jack ]]; return ;;
      apt-get) [[ "$scenario" != no_apt ]]; return ;;
      sudo) [[ "$scenario" != no_sudo ]]; return ;;
    esac
  fi
  builtin command "$@"
}}
id() {{ if [[ "$scenario" == root ]]; then echo 0; else echo 1000; fi; }}
sudo() {{ echo "SUDO:$*"; "$@"; }}
apt-get() {{
  echo "APT:$*"
  if [[ "$1" == update ]]; then [[ "$scenario" != update_failed ]]; return; fi
  [[ "$scenario" != install_failed ]] || return 1
  if [[ "$scenario" != not_detected ]]; then installed=yes; fi
  if [[ "$scenario" == missing_pw_jack ]]; then scenario=fixed_pw_jack; fi
}}
ensure_linux_supercollider
echo CONTINUING
'''],
        env={**os.environ, "GAIA_SCAPE_DATA_DIR": str(tmp_path / "data")},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CONTINUING" in result.stdout
    attempted = scenario in {"install", "root", "update_failed", "install_failed", "not_detected", "partial", "missing_pw_jack"}
    assert ("APT:update" in result.stdout) == attempted
    assert ("APT:install -y supercollider-language supercollider-server pipewire-jack" in result.stdout) == (
        attempted and scenario != "update_failed"
    )
    assert ("SUDO:" in result.stdout) == (attempted and scenario != "root")
    assert ("installed and detected" in result.stdout) == (scenario in {"install", "root", "partial", "missing_pw_jack"})
    if scenario not in {"present", "install", "root", "partial", "missing_pw_jack"}:
        assert "Continuing without verified audio dependencies" in result.stderr
        assert "sudo apt-get install supercollider-language supercollider-server pipewire-jack" in result.stderr
    if scenario in {"update_failed", "install_failed"}:
        assert "package installation failed" in result.stderr
    if scenario == "not_detected":
        assert "missing from PATH" in result.stderr


def test_common_installer_checks_linux_renderer_before_installing_runtime():
    installer = Path("install.sh").read_text()
    assert 'source "$SOURCE_DIR/scripts/linux_dependencies.sh"' in installer
    assert installer.index("ensure_linux_supercollider") < installer.index('mkdir -p "$INSTALL_DIR/data"')
    assert installer.index('GAIA_SCAPE_INSTALL_MODE:-desktop') < installer.index("ensure_linux_supercollider")


@pytest.mark.parametrize('mode', ['desktop', 'headless'])
@pytest.mark.parametrize('state', ['present', 'missing', 'failed'])
def test_linux_host_packages_are_installed_before_python_setup(tmp_path, mode, state):
    result = subprocess.run(
        ['bash', '-c', f'''set -euo pipefail
source {shlex.quote(str(HELPER))}
INSTALL_MODE={mode}
command() {{ if [[ "$1" == -v && "$2" == apt-get ]]; then return 0; fi; builtin command "$@"; }}
dpkg-query() {{
  if [[ {state} == present ]]; then printf 'install ok installed'; else return 1; fi
}}
install_linux_packages() {{ echo "PACKAGES:$*"; [[ {state} != failed ]]; }}
ensure_linux_host_dependencies
'''], capture_output=True, text=True,
        env={**os.environ, 'GAIA_SCAPE_DATA_DIR': str(tmp_path / 'data')},
    )
    assert (result.returncode == 0) == (state != 'failed')
    if state == 'present':
        assert 'PACKAGES:' not in result.stdout
    else:
        assert 'PACKAGES:python3 python3-venv python3-pip' in result.stdout
        assert ('python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 wireplumber' in result.stdout) == (mode == 'desktop')
    installer = Path('install.sh').read_text()
    assert installer.index('ensure_linux_host_dependencies') < installer.index('command -v "$PYTHON_BIN"')


@pytest.mark.parametrize('platform,active,wrapper', [
    ('Linux', True, True), ('Linux', False, True),
    ('Linux', True, False), ('Darwin', True, True),
])
def test_gui_launcher_wraps_renderer_in_active_pipewire_session(tmp_path, platform, active, wrapper):
    import shutil

    runtime = tmp_path / 'test runtime'
    (runtime / 'scripts').mkdir(parents=True)
    (runtime / '.venv/bin').mkdir(parents=True)
    (runtime / 'data').mkdir()
    shutil.copy2('scripts/run_gaiascapes_gui.sh', runtime / 'scripts')
    tools = tmp_path / 'tools'
    tools.mkdir()
    log = tmp_path / 'commands'

    def executable(path, body):
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    (tools / 'dirname').symlink_to(shutil.which('dirname'))
    executable(tools / 'uname', f'echo {platform}')
    executable(tools / 'pgrep', 'exit 1')
    executable(tools / 'sleep', '/bin/sleep 0.1')
    executable(tools / 'wpctl', f'exit {0 if active else 1}')
    if wrapper:
        executable(tools / 'pw-jack', 'echo WRAPPED >> "$TEST_LOG"\nexec "$@"')
    executable(runtime / 'scripts/run_supercollider.sh', 'echo RENDERER >> "$TEST_LOG"')
    executable(runtime / '.venv/bin/python', 'echo "DESKTOP:$*" >> "$TEST_LOG"')
    result = subprocess.run(
        [shutil.which('bash'), str(runtime / 'scripts/run_gaiascapes_gui.sh'), '--test-argument'],
        env={**os.environ, 'PATH': str(tools), 'TEST_LOG': str(log),
             'GAIA_SCAPE_DATA_DIR': str(runtime / 'data')},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    commands = log.read_text().splitlines()
    expected_wrapper = platform == 'Linux' and active and wrapper
    assert ('WRAPPED' in commands) == expected_wrapper
    assert 'RENDERER' in commands
    assert 'DESKTOP:-m gaiascapes_host.desktop --test-argument' in commands
    if platform == 'Linux' and active and not wrapper:
        assert 'pw-jack is missing' in result.stderr
