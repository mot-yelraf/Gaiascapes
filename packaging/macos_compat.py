"""Reject native bundle libraries that require a newer macOS release.

Wheel platform tags guide dependency resolution, but each packaged Mach-O slice
is also inspected before an installer can claim compatibility with an older OS.
"""

from pathlib import Path
import re
import subprocess


MACHO_MAGICS = {bytes.fromhex(value) for value in (
    'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
    'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}


def version_tuple(value: str) -> tuple[int, int, int]:
    """Normalize a macOS release for numeric deployment-target comparisons."""
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', value):
        raise ValueError('macOS minimum must be major.minor or major.minor.patch')
    parts = tuple(int(part) for part in value.split('.'))
    return (*parts, 0) if len(parts) == 2 else parts


def deployment_versions(output: str) -> list[str]:
    """Read only macOS minimum-version commands from otool output."""
    versions = []
    command = None
    for line in output.splitlines():
        words = line.split()
        if len(words) == 2 and words[0] == 'cmd':
            command = words[1]
        if len(words) == 2 and ((command == 'LC_BUILD_VERSION' and words[0] == 'minos')
                               or (command == 'LC_VERSION_MIN_MACOSX' and words[0] == 'version')):
            version_tuple(words[1])
            versions.append(words[1])
    return versions


def audit_bundle(bundle: Path, architecture: str, minimum: str) -> dict:
    """Fail packaging when any native slice exceeds the advertised minimum."""
    target = version_tuple(minimum)
    checked = 0
    highest = (0, 0, 0)
    failures = []
    for path in sorted(bundle.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as source:
            if source.read(4) not in MACHO_MAGICS:
                continue
        result = subprocess.run(['otool', '-arch', architecture, '-l', str(path)],
                                check=True, capture_output=True, text=True, timeout=30)
        versions = deployment_versions(result.stdout)
        if not versions:
            failures.append(f'{path.relative_to(bundle)}: no macOS deployment target for {architecture}')
            continue
        checked += 1
        required = max(version_tuple(value) for value in versions)
        highest = max(highest, required)
        if required > target:
            failures.append(f'{path.relative_to(bundle)}: requires macOS {".".join(map(str, required))}')
    if failures or checked == 0:
        raise RuntimeError(f'Bundle is not verified for macOS {minimum}:\n' +
                           ('\n'.join(failures) or 'No native files found'))
    return {'architecture': architecture, 'minimum_macos': minimum,
            'checked_native_files': checked,
            'highest_native_minimum': '.'.join(map(str, highest))}
