"""Optional macOS speech rendering through the SuperCollider Say quark.

A standalone language process loads the installed quark and writes a WAV file.
Its configuration, SayBuf scratch directory, and subprocesses are isolated from
both the running renderer and the user's normal SuperCollider session.
"""

import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess


# Upstream documents use on 10.11–10.14, but declares no minimum OS version.
# Use the oldest documented version as a conservative floor, then probe runtime.
MINIMUM_MACOS = (10, 11)
# Only explicit, known native voices: never silently substitute another dialect
# or gender. Missing choices fall back to the selected eSpeak NG voice.
NATIVE_VOICES = {
    "en-us": ("en_US", ("Samantha", "Victoria"), ("Alex", "Fred")),
    "en-gb": ("en_GB", ("Serena", "Kate"), ("Daniel",)),
    "en-gb-scotland": ("en_SC", ("Fiona",), ()),
    "en-029": ("en_029", (), ()),
    "es": ("es_ES", ("Mónica", "Monica"), ("Jorge",)),
    "es-419": ("es_MX", ("Paulina",), ("Juan",)),
    "fr-fr": ("fr_FR", ("Audrey", "Aurélie", "Aurelie"), ("Thomas", "Jacques")),
    "fr-be": ("fr_BE", (), ()), "fr-ch": ("fr_CH", (), ()),
    "de": ("de_DE", ("Anna", "Petra"), ("Markus", "Yannick")),
    "uk": ("uk_UA", ("Lesya",), ()),
    "pt": ("pt_PT", ("Joana",), ("Joaquim",)),
    "pt-br": ("pt_BR", ("Luciana",), ("Felipe",)),
}

# Text goes in a UTF-8 file, never into Say's shell-built command string.
# The fixed shell comment suppresses Say's trailing empty text argument, which
# otherwise overrides -f and produces an empty recording.
SAY_SCRIPT = r'''
(
var input = thisProcess.argv[0], output = thisProcess.argv[1], voice = thisProcess.argv[2];
if (Say.isValidVoice(voice).not) { "Requested native voice is unavailable".postln; 1.exit };
(type: \say, voice: voice, text: "", wordrate: 155,
 cmds: "--file-format=WAVE --data-format=LEI16@22050 -f " ++ input.shellQuote ++ " -o " ++ output.shellQuote ++ " #",
 doneFunc: { 0.exit }).play;
)
'''


def say_quark_paths() -> tuple[Path, Path, Path] | None:
    """Find a compatible Mac, sclang class library, and an installed Say quark."""
    if platform.system() != "Darwin":
        return None
    try:
        version = tuple(int(part) for part in platform.mac_ver()[0].split('.')[:2])
    except ValueError:
        return None
    if version < MINIMUM_MACOS or not Path('/usr/bin/say').is_file():
        return None
    candidates = [Path(value) for value in [shutil.which('sclang')] if value]
    candidates += [Path('/Applications/SuperCollider.app/Contents/MacOS/sclang'),
                   Path.home() / 'Applications/SuperCollider.app/Contents/MacOS/sclang']
    quarks = [Path.home() / 'Library/Application Support/SuperCollider/downloaded-quarks/say',
              Path.home() / 'Library/Application Support/SuperCollider/Extensions/say']
    quark = next((path for path in quarks if (path / 'Classes/Say.sc').is_file()), None)
    if not quark:
        return None
    for executable in candidates:
        if not executable.is_file():
            continue
        executable = executable.resolve()
        libraries = [executable.parent.parent / 'Resources/SCClassLibrary',
                     executable.parent.parent / 'share/SuperCollider/SCClassLibrary']
        library = next((path for path in libraries if path.is_dir()), None)
        if library:
            return executable, library, quark
    return None


def native_voice(dialect: str, variant: str) -> str | None:
    """Select an installed native voice matching both dialect and requested variant."""
    locale, female, male = NATIVE_VOICES[dialect]
    result = subprocess.run(['/usr/bin/say', '-v', '?'], capture_output=True, text=True,
                            timeout=5, check=True)
    installed = {}
    for line in result.stdout.splitlines():
        match = re.match(r'^(.+?)\s+([a-z]{2,3}_[A-Za-z0-9_]+)\s+#', line)
        if match:
            installed[match[1].strip()] = match[2]
    choices = male if variant == 'male' else female if variant == 'female' else female + male
    return next((name for name in choices if installed.get(name) == locale), None)


def render_say(text: str, dialect: str, variant: str, directory: Path, output: Path) -> None:
    """Render a WAV through Say, or raise a failure suitable for eSpeak fallback."""
    paths = say_quark_paths()
    if paths is None:
        raise RuntimeError('Say quark or compatible macOS/SuperCollider is unavailable')
    voice = native_voice(dialect, variant)
    if voice is None:
        raise RuntimeError('No installed Say voice matches the dialect and variant')
    executable, library, quark = paths
    scratch = directory / 'say-worker'
    scratch.mkdir()
    # XDG overrides are supported by SuperCollider on macOS as well as Linux.
    (scratch / 'SuperCollider').mkdir()
    script = scratch / 'render.scd'
    script.write_text(SAY_SCRIPT, encoding='utf-8')
    source = scratch / 'text.txt'
    source.write_text(text, encoding='utf-8')
    config = scratch / 'sclang_conf.yaml'
    config.write_text('includePaths:\n' + ''.join('  - ' + json.dumps(str(path)) + '\n'
                      for path in (library, quark)) + 'excludeDefaultPaths: true\n', encoding='utf-8')
    environment = dict(os.environ, XDG_DATA_HOME=str(scratch), XDG_CONFIG_HOME=str(scratch))
    process = subprocess.Popen(
        [str(executable), '-D', '-a', '-l', str(config), '-u', '0', '-d', str(scratch),
         str(script), str(source), str(output), voice],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise RuntimeError('Say rendering timed out') from exc
    if process.returncode != 0 or not output.is_file():
        raise RuntimeError('Say quark failed to render audio: '
                           + (stderr or stdout).decode('utf-8', errors='replace')[-300:])
