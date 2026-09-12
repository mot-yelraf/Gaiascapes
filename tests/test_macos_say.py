"""Check native voice selection, compatibility gates, and eSpeak fallback.

Mocks keep automated tests independent of installed voices and SuperCollider.
"""

import subprocess
from types import SimpleNamespace

import pytest

from gaiascapes_host import announcements, macos_say
from test_announcements import wav_bytes


@pytest.mark.parametrize('system,version', [('Linux', '26.0'), ('Darwin', '10.10.5'),
                                           ('Darwin', ''), ('Darwin', 'invalid')])
def test_unsupported_platforms_skip_say(monkeypatch, system, version):
    monkeypatch.setattr(macos_say.platform, 'system', lambda: system)
    monkeypatch.setattr(macos_say.platform, 'mac_ver', lambda: (version, (), ''))
    assert macos_say.say_quark_paths() is None


def test_native_voice_requires_matching_dialect_and_variant(monkeypatch):
    monkeypatch.setattr(macos_say.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        stdout='Samantha en_US # Hello\nDaniel en_GB # Hello\nLesya uk_UA # Hello\n'))
    assert macos_say.native_voice('en-us', 'female') == 'Samantha'
    assert macos_say.native_voice('en-us', 'male') is None
    assert macos_say.native_voice('en-gb', 'default') == 'Daniel'
    assert macos_say.native_voice('uk', 'female') == 'Lesya'
    assert macos_say.native_voice('fr-ch', 'default') is None


@pytest.mark.parametrize('failure', [False, True, 'invalid'])
def test_native_success_and_failure_fallback(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(announcements, 'say_quark_paths', lambda: ('sclang', 'library', 'quark'))
    monkeypatch.setattr(announcements, 'espeak_executable', lambda: '/fake/espeak-ng')
    calls = []
    def native(text, voice, variant, directory, output):
        calls.append('say')
        if failure is True:
            raise RuntimeError('native failed')
        output.write_bytes(b'invalid' if failure else wav_bytes())
    def espeak(command, **kwargs):
        calls.append('espeak')
        from pathlib import Path
        Path(command[command.index('-w') + 1]).write_bytes(wav_bytes())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(announcements, 'render_say', native)
    monkeypatch.setattr(announcements.subprocess, 'run', espeak)
    renderer = announcements.AnnouncementRenderer(tmp_path)
    assert renderer.render('Bird', 'en-us') == wav_bytes()
    assert calls == (['say', 'espeak'] if failure else ['say'])
    assert bool(renderer.last_fallback) == bool(failure)
    assert renderer.last_backend == ('eSpeak NG' if failure else 'Say quark')
    calls.clear()
    assert renderer.render('Bird', 'en-us', synthesizer='espeak-ng') == wav_bytes()
    assert calls == ['espeak']
    assert renderer.last_fallback == ''


def test_worker_isolation_and_text_file(tmp_path, monkeypatch):
    monkeypatch.setattr(macos_say, 'say_quark_paths', lambda: (tmp_path/'sclang', tmp_path/'lib', tmp_path/'quark'))
    monkeypatch.setattr(macos_say, 'native_voice', lambda *args: 'Samantha')
    output = tmp_path/'audio.wav'
    text = 'Bird "$HOME" `whoami` $(id)'
    def start(command, **kwargs):
        assert kwargs['start_new_session'] is True
        assert kwargs['env']['XDG_DATA_HOME'] == str(tmp_path/'say-worker')
        assert kwargs['env']['XDG_CONFIG_HOME'] == str(tmp_path/'say-worker')
        assert text not in command
        assert (tmp_path/'say-worker/text.txt').read_text() == text
        assert '-a' in command and command[command.index('-u') + 1] == '0'
        output.write_bytes(wav_bytes())
        return SimpleNamespace(returncode=0, communicate=lambda timeout: (b'', b''))
    monkeypatch.setattr(macos_say.subprocess, 'Popen', start)
    macos_say.render_say(text, 'en-us', 'female', tmp_path, output)
    assert output.read_bytes() == wav_bytes()
