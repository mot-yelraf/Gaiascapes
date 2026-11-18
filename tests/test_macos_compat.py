"""Check deployment-target rejection without invoking native build tools.

Synthetic Mach-O headers and captured otool load commands exercise compatibility
checks independently of the developer's operating system and installed runtime.
"""

from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


MODULE = runpy.run_path(str(Path(__file__).parents[1] / 'packaging/macos_compat.py'))


def test_deployment_versions_ignore_linked_library_versions():
    output = '''
      cmd LC_ID_DYLIB
  current version 20.0.0
      cmd LC_BUILD_VERSION
 platform 1
    minos 10.13
      sdk 15.0
      cmd LC_LOAD_DYLIB
  current version 99.0.0
      cmd LC_VERSION_MIN_MACOSX
  version 12.0
      sdk 15.0
'''
    assert MODULE['deployment_versions'](output) == ['10.13', '12.0']
    assert MODULE['version_tuple']('12.0') == (12, 0, 0)
    assert MODULE['version_tuple']('12.7.6') == (12, 7, 6)
    with pytest.raises(ValueError):
        MODULE['version_tuple']('12; invalid')


def test_bundle_audit_rejects_newer_native_dependency(tmp_path, monkeypatch):
    bundle = tmp_path / 'Test.app'
    bundle.mkdir()
    (bundle / 'app').write_bytes(bytes.fromhex('cffaedfe') + b'native')
    (bundle / 'numpy.so').write_bytes(bytes.fromhex('cafebabe') + b'universal')
    (bundle / 'guide.pdf').write_bytes(b'%PDF-')
    (bundle / 'alias').symlink_to(bundle / 'app')
    versions = {'app': '10.13', 'numpy.so': '14.0'}
    calls = []

    def otool(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='cmd LC_BUILD_VERSION\n minos ' + versions[Path(command[-1]).name])

    monkeypatch.setattr(MODULE['subprocess'], 'run', otool)
    with pytest.raises(RuntimeError, match='numpy.so: requires macOS 14.0.0'):
        MODULE['audit_bundle'](bundle, 'x86_64', '12.0')
    versions['numpy.so'] = '12.0'
    report = MODULE['audit_bundle'](bundle, 'x86_64', '12.0')
    assert report['checked_native_files'] == 2
    assert report['highest_native_minimum'] == '12.0.0'
    assert all(command[:4] == ['otool', '-arch', 'x86_64', '-l'] for command in calls)


def test_bundle_without_verified_native_targets_is_rejected(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match='No native files found'):
        MODULE['audit_bundle'](tmp_path, 'x86_64', '12.0')
    (tmp_path / 'unrecognized').write_bytes(bytes.fromhex('cffaedfe'))
    monkeypatch.setattr(MODULE['subprocess'], 'run', lambda *args, **kwargs: SimpleNamespace(stdout=''))
    with pytest.raises(RuntimeError, match='no macOS deployment target'):
        MODULE['audit_bundle'](tmp_path, 'x86_64', '12.0')
