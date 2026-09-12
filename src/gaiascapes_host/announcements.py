"""Offline spoken labels for recorded animal sounds.

Say is preferred on supported Macs; eSpeak NG remains the cross-platform
fallback. Bounded WAV clips are rendered beneath the selected installation's
data directory without requiring a running audio server.
"""

from collections import OrderedDict
import hashlib
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import wave

from .mammals import MAMMAL_KINDS
from .macos_say import render_say, say_quark_paths


ANNOUNCEMENT_VOICES = {
    "en-us": "English — United States", "en-gb": "English — United Kingdom",
    "en-gb-scotland": "English — Scotland", "en-029": "English — Caribbean",
    "es": "Español — España", "es-419": "Español — Latinoamérica",
    "fr-fr": "Français — France", "fr-be": "Français — Belgique",
    "fr-ch": "Français — Suisse", "de": "Deutsch — Deutschland",
    "uk": "Українська — Україна", "pt": "Português — Portugal",
    "pt-br": "Português — Brasil",
}
ANNOUNCEMENT_VARIANTS = {"default": "", "male": "m2", "female": "f2"}
RECORDED_KINDS = {"birdsong", "frog_calls", "whale_song", "dolphin_calls", *MAMMAL_KINDS}
INSTALL_MESSAGE = "Install eSpeak NG on the Gaiascapes host to enable announcements."


def recording_announcement(event: dict) -> str:
    """Return the recorded species and named location, omitting coordinates."""
    if event.get("kind") not in RECORDED_KINDS:
        return ""
    traits = event.get("traits", {})
    title = str(traits.get("title") or "").removeprefix("File:").split(" · ")[0]
    # Commons catalog titles start with a binomial followed by the common name.
    title = re.sub(r"^[A-Z][a-z]+ [a-z]+\s+-\s+", "", title)
    title = re.sub(r"\s+XC\d+.*$|\.(?:mp3|ogg|wav|flac)$", "", title, flags=re.I)
    title = re.sub(r"\s+(?:vocalizations?|song|calls?|whistles?|clicks?)(?:\s+.*)?$", "", title, flags=re.I)
    species = str(traits.get("common_name") or title or traits.get("scientific_name") or "").strip()
    place = str(traits.get("place") or traits.get("region_name") or "").strip()
    coordinates = re.sub(r"\b(?:latitude|longitude|lat|lon|long)\b", "", place, flags=re.I)
    if ((re.search(r"\d", place)
         and not re.search(r"[^\W\d_]", re.sub(r"[NSEWnsew]", "", coordinates)))
            or place.lower() in {"unknown", "unknown location", "unspecified"}):
        place = ""
    # Plain names work in every voice without introducing English filler words.
    text = ". ".join(part for part in (species[:160], place[:220]) if part)
    return " ".join(text.replace("[[", "").replace("]]", "").split())


def espeak_executable() -> str | None:
    """Find eSpeak NG on PATH or in its standard desktop install locations."""
    found = shutil.which("espeak-ng")
    if found:
        return found
    candidates = [Path("/opt/homebrew/bin/espeak-ng"), Path("/usr/local/bin/espeak-ng")]
    if os.name == "nt":
        candidates = [Path(os.environ.get(name, "C:/Program Files")) / "eSpeak NG/espeak-ng.exe"
                      for name in ("ProgramFiles", "ProgramFiles(x86)")]
    return next((str(path) for path in candidates if path.is_file()), None)


class AnnouncementRenderer:
    """Serialize optional speech generation with a bounded in-memory clip cache."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir) / "announcements"
        self._cache = OrderedDict()
        self._lock = threading.Lock()
        self.last_backend = ""
        self.last_fallback = ""

    def render(self, text: str, voice: str, variant: str = "default", synthesizer: str = "auto") -> bytes:
        """Render one short label as WAV, raising an operator-readable failure."""
        if (voice not in ANNOUNCEMENT_VOICES or variant not in ANNOUNCEMENT_VARIANTS
                or synthesizer not in {"auto", "say", "espeak-ng"}
                or not text or len(text) > 400):
            raise ValueError("Invalid announcement text, dialect, or variant")
        executable = espeak_executable()
        use_say = synthesizer != "espeak-ng" and say_quark_paths() is not None
        if not executable and not use_say:
            raise RuntimeError(INSTALL_MESSAGE)
        suffix = ANNOUNCEMENT_VARIANTS[variant]
        espeak_voice = f"{voice}+{suffix}" if suffix else voice
        key = hashlib.sha256(f"{synthesizer}\0{use_say}\0{espeak_voice}\0{text}".encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                clip, self.last_backend, self.last_fallback = self._cache[key]
                return clip
            self.last_backend = "eSpeak NG"
            self.last_fallback = ""
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="speech-", dir=self.data_dir) as temporary:
                output = Path(temporary) / "announcement.wav"
                if use_say:
                    try:
                        render_say(text, voice, variant, Path(temporary), output)
                        # Validate native output before deciding whether to fall back.
                        with wave.open(str(output), "rb") as audio:
                            if audio.getnframes() < 1 or audio.getnchannels() != 1 or output.stat().st_size > 4_000_000:
                                raise ValueError("Invalid native speech audio")
                        self.last_backend = "Say quark"
                    except (OSError, RuntimeError, subprocess.SubprocessError, wave.Error, EOFError, ValueError):
                        self.last_fallback = "Say voice unavailable or rendering failed; using eSpeak NG."
                elif synthesizer == "say" or (synthesizer == "auto" and platform.system() == "Darwin"):
                    self.last_fallback = "Say quark unavailable on this installation; using eSpeak NG."
                if self.last_backend != "Say quark":
                    if not executable:
                        raise RuntimeError("Say could not render this voice. " + INSTALL_MESSAGE)
                    try:
                        result = subprocess.run(
                            [executable, "-v", espeak_voice, "-s", "155", "-w", str(output), "--stdin"],
                            input=text.encode("utf-8"), capture_output=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        raise RuntimeError(f"eSpeak NG could not render the announcement: {exc}") from exc
                    if result.returncode:
                        raise RuntimeError(f"eSpeak NG could not use dialect {voice}: "
                                           + result.stderr.decode("utf-8", errors="replace")[:300])
                try:
                    if output.stat().st_size > 4_000_000:
                        raise ValueError("Announcement audio exceeds the size limit")
                    with wave.open(str(output), "rb") as audio:
                        if audio.getnframes() < 1 or audio.getnchannels() != 1:
                            raise ValueError("Invalid announcement audio")
                    clip = output.read_bytes()
                except (OSError, EOFError, wave.Error, ValueError) as exc:
                    raise RuntimeError(f"eSpeak NG produced invalid audio: {exc}") from exc
            self._cache[key] = (clip, self.last_backend, self.last_fallback)
            if len(self._cache) > 32:
                self._cache.popitem(last=False)
            return clip
