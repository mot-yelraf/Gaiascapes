"""Exercise macOS dependency decisions with fake tools, never package installs.

Shell functions are driven with controlled answers and executable stubs in a
throwaway directory. No system Homebrew, Python installation, or renderer runs.
"""

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX installer")
HELPER = Path("scripts/macos_dependencies.sh").resolve()


def run_checks(tmp_path, body):
    env = {**os.environ, "GAIA_SCAPE_DATA_DIR": str(tmp_path / "data"), "GAIA_SCAPE_PYTHON": ""}
    return subprocess.run(["bash", "-c", f'set -eu\nsource {shlex.quote(str(HELPER))}\n'
                           + 'macos_python_candidates() { :; }\n' + body],
                          capture_output=True, text=True, env=env)


@pytest.mark.parametrize("python_state", ["missing", "old"])
def test_python_offer_uses_homebrew_interpreter(tmp_path, python_state):
    prefix = tmp_path / "brew prefix"
    (prefix / "bin").mkdir(parents=True)
    python = prefix / "bin/python3.13"
    python.write_text('#!/bin/bash\nexit 0\n')
    python.chmod(0o755)
    old = tmp_path / "old-python"
    if python_state == "old":
        old.write_text('#!/bin/bash\nexit 1\n')
        old.chmod(0o755)
    result = run_checks(tmp_path, f'''
PYTHON_BIN={shlex.quote(str(old))}
fake_brew() {{
  if [[ "$1" == install ]]; then echo "INSTALL:$*";
  else printf '%s\\n' {shlex.quote(str(prefix))}; fi
}}
find_homebrew() {{ BREW_BIN=fake_brew; }}
confirm_dependency() {{ echo "OFFER:$1"; return 0; }}
ensure_macos_python
"$PYTHON_BIN" -m venv "{tmp_path}/venv"
printf 'SELECTED:%s\\n' "$PYTHON_BIN"
''')
    assert result.returncode == 0, result.stderr
    assert "Minimum required: Python 3.10" in result.stderr
    assert "OFFER:Install supported Python 3.13" in result.stdout
    assert "INSTALL:install python@3.13" in result.stdout
    assert f"SELECTED:{python}" in result.stdout


@pytest.mark.parametrize("scenario", ["decline", "no_brew", "install_failed", "invalid_python", "prefix_failed"])
def test_python_failure_explains_required_host(tmp_path, scenario):
    result = run_checks(tmp_path, f'''
PYTHON_BIN=/missing/gaiascapes-test-python
find_homebrew() {{ BREW_BIN=fake_brew; return {1 if scenario == 'no_brew' else 0}; }}
confirm_dependency() {{ return {1 if scenario == 'decline' else 0}; }}
fake_brew() {{
  echo "BREW:$*" >&2
  if [[ "$1" == install ]]; then return {1 if scenario == 'install_failed' else 0}; fi
  echo /missing/brew-prefix
  return {1 if scenario == 'prefix_failed' else 0}
}}
ensure_macos_python
''')
    assert result.returncode != 0
    assert "Python 3.10 or newer" in result.stderr
    assert "GAIA_SCAPE_PYTHON=" in result.stderr
    assert "installation cannot continue" in result.stderr
    if scenario in {"decline", "no_brew"}:
        assert "BREW:" not in result.stderr


def test_supported_python_skips_all_offers(tmp_path):
    result = run_checks(tmp_path, '''
PYTHON_BIN=true
find_homebrew() { echo UNEXPECTED; return 1; }
confirm_dependency() { echo UNEXPECTED; return 1; }
ensure_macos_python
''')
    assert result.returncode == 0
    assert "UNEXPECTED" not in result.stdout


@pytest.mark.parametrize("scenario", ["present", "accept", "decline", "no_brew", "failed", "not_detected"])
def test_supercollider_is_optional_and_install_is_verified(tmp_path, scenario):
    result = run_checks(tmp_path, f'''
installed={'yes' if scenario == 'present' else 'no'}
supercollider_installed() {{ [[ "$installed" == yes ]]; }}
find_homebrew() {{ BREW_BIN=fake_brew; return {1 if scenario == 'no_brew' else 0}; }}
confirm_dependency() {{ echo "OFFER:$1"; return {1 if scenario == 'decline' else 0}; }}
fake_brew() {{
  echo "BREW:$*"
  installed={'yes' if scenario == 'accept' else 'no'}
  return {1 if scenario == 'failed' else 0}
}}
ensure_macos_supercollider
echo CONTINUING
''')
    assert result.returncode == 0, result.stderr
    assert "CONTINUING" in result.stdout
    if scenario in {"accept", "failed", "not_detected"}:
        assert "BREW:install --cask supercollider" in result.stdout
    else:
        assert "BREW:" not in result.stdout
    if scenario not in {"accept", "present"}:
        assert "capture, history, the web UI" in result.stderr
        assert "https://supercollider.github.io/downloads" in result.stderr


def test_noninteractive_prompt_does_not_accept(tmp_path):
    result = run_checks(tmp_path, "confirm_dependency 'Install dependency?' </dev/null")
    assert result.returncode != 0
    assert "no dependency will be installed automatically" in result.stderr


def test_new_homebrew_python_preserves_old_venv_before_replacement(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / ".venv").mkdir(parents=True)
    (runtime / ".venv/old-python-marker").write_text("old environment")
    (runtime / "data").mkdir()
    (runtime / "data/config.json").write_text('{"http_port":8768}')
    result = run_checks(tmp_path, f'''
INSTALL_DIR={shlex.quote(str(runtime))}
PYTHON_BIN={shlex.quote(sys.executable)}
MACOS_PYTHON_INSTALLED=yes
prepare_macos_venv
''')
    assert result.returncode == 0, result.stderr
    assert not (runtime / ".venv").exists()
    backups = list(runtime.glob('.venv-previous.*/venv/old-python-marker'))
    assert len(backups) == 1
    assert backups[0].read_text() == "old environment"
    assert (runtime / 'data/config.json').read_text() == '{"http_port":8768}'


@pytest.mark.parametrize("explicit", [False, True])
def test_existing_python_discovery_respects_explicit_override(tmp_path, explicit):
    result = run_checks(tmp_path, f'''
PYTHON_BIN=/missing/python3
GAIA_SCAPE_PYTHON={'/missing/explicit-python' if explicit else ''}
macos_python_candidates() {{ printf '%s\\n' /missing/candidate {shlex.quote(sys.executable)}; }}
find_homebrew() {{ return 1; }}
ensure_macos_python
printf 'SELECTED:%s\\n' "$PYTHON_BIN"
''')
    if explicit:
        assert result.returncode != 0
        assert "Using existing Python" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert f"SELECTED:{sys.executable}" in result.stdout
        assert "Install supported Python" not in result.stderr


def test_candidates_include_homebrew_python_outside_path(tmp_path):
    prefix = tmp_path / "brew prefix"
    result = subprocess.run(
        ["bash", "-c", f'''set -eu
source {shlex.quote(str(HELPER))}
find_homebrew() {{ BREW_BIN=fake_brew; }}
fake_brew() {{ printf '%s\\n' {shlex.quote(str(prefix))}; }}
macos_python_candidates
'''], capture_output=True, text=True,
        env={**os.environ, "GAIA_SCAPE_DATA_DIR": str(tmp_path / "data")},
    )
    assert result.returncode == 0, result.stderr
    assert str(prefix / "opt/python@3.13/bin/python3.13") in result.stdout.splitlines()


@pytest.mark.parametrize('scenario', ['present', 'accept', 'decline', 'no_sc', 'failed', 'invalid', 'existing'])
def test_say_quark_install_is_optional_and_preserves_existing_files(tmp_path, scenario):
    home = tmp_path / 'home'
    root = home / 'Library/Application Support/SuperCollider'
    destination = root / 'Extensions/say'
    if scenario == 'present':
        classes = root / 'downloaded-quarks/say/Classes'
        classes.mkdir(parents=True)
        (classes / 'Say.sc').write_text('existing quark')
    elif scenario == 'existing':
        destination.mkdir(parents=True)
        (destination / 'custom.txt').write_text('keep')
    result = run_checks(tmp_path, f'''
HOME={shlex.quote(str(home))}
TMPDIR={shlex.quote(str(tmp_path))}
supercollider_installed() {{ return {1 if scenario == 'no_sc' else 0}; }}
confirm_dependency() {{ echo OFFER; return {1 if scenario == 'decline' else 0}; }}
git() {{
  echo "CLONE:$*"
  [[ {scenario} != failed ]] || return 1
  mkdir -p "$5/Classes"
  if [[ {scenario} != invalid ]]; then printf 'Say {{}}' > "$5/Classes/Say.sc"; fi
}}
ensure_macos_say_quark
echo CONTINUING
''')
    assert result.returncode == 0, result.stderr
    assert 'CONTINUING' in result.stdout
    assert (destination / 'Classes/Say.sc').is_file() == (scenario == 'accept')
    if scenario in {'present', 'decline', 'no_sc', 'existing'}:
        assert 'CLONE:' not in result.stdout
    if scenario not in {'present', 'accept'}:
        assert 'Quarks.install(' in result.stderr
    if scenario == 'existing':
        assert (destination / 'custom.txt').read_text() == 'keep'


def test_macos_installer_checks_say_after_supercollider():
    installer = Path('install.sh').read_text()
    assert installer.index('ensure_macos_supercollider') < installer.index('ensure_macos_say_quark')


@pytest.mark.parametrize("state", ["broken", "different", "same"])
def test_existing_venv_is_preserved_when_python_needs_replacement(tmp_path, state):
    runtime = tmp_path / "runtime"
    executable = runtime / ".venv/bin/python"
    executable.parent.mkdir(parents=True)
    if state == "same":
        executable.symlink_to(sys.executable)
    elif state == "different":
        executable.write_text('#!/bin/bash\nprintf "/previous/python\\n"\n')
        executable.chmod(0o755)
    (runtime / "data").mkdir()
    config = runtime / "data/config.json"
    config.write_text('{"http_port":8768,"osc_port":57130}')
    result = run_checks(tmp_path, f'''
INSTALL_DIR={shlex.quote(str(runtime))}
PYTHON_BIN={shlex.quote(sys.executable)}
prepare_macos_venv
''')
    assert result.returncode == 0, result.stderr
    assert (runtime / ".venv").exists() == (state == "same")
    assert len(list(runtime.glob(".venv-previous.*"))) == (0 if state == "same" else 1)
    assert config.read_text() == '{"http_port":8768,"osc_port":57130}'


@pytest.mark.parametrize('answer,accepted', [('yes', True), ('y', True), ('', False), ('no', False)])
def test_terminal_offer_requires_yes(tmp_path, answer, accepted):
    import pty

    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(
            ['bash', '-c', f'source {shlex.quote(str(HELPER))}\nconfirm_dependency "Install dependency?"'],
            stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, 'GAIA_SCAPE_DATA_DIR': str(tmp_path / 'data')},
        )
        os.write(master, (answer + '\n').encode())
        stdout, stderr = process.communicate(timeout=5)
        assert (process.returncode == 0) is accepted
        assert '[y/N]' in stderr
    finally:
        os.close(master)
        os.close(slave)
