"""Prepare verified official SuperCollider binaries and matching source.

macOS and Windows installers carry a private renderer. Debian-family packages
use the distribution's maintained SuperCollider and audio service packages.
"""

import hashlib
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

VERSION = "3.14.1"
BASE = f"https://github.com/supercollider/supercollider/releases/download/Version-{VERSION}/"
ASSETS = {
    "darwin": (f"SuperCollider-{VERSION}-macOS-universal.dmg", "ed264b32752d27fc86e506dd0a7eb36de7c19ebce73c3fdf2ed5514f8c73f02e"),
    "win32": (f"SuperCollider-{VERSION}-win64.zip", "a5f95416307d35c039ca53a9f9c6151c26585064d3229521093a60dddb9458cd"),
    "source": (f"SuperCollider-{VERSION}-Source.tar.bz2", "ee640c68777ae697682066ce5c4a8b7e56c5b223e76c79c13b5be5387ee55bb2"),
}


def download_asset(kind: str, cache: Path) -> Path:
    """Reuse or download an upstream asset, checking its pinned SHA-256."""
    name, expected = ASSETS[kind]
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / name
    if not destination.exists():
        pending = destination.with_suffix(destination.suffix + ".part")
        print(f"Downloading {name}", flush=True)
        with urllib.request.urlopen(BASE + name, timeout=120) as response, pending.open("wb") as output:
            shutil.copyfileobj(response, output)
        with pending.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != expected:
            pending.unlink()
            raise RuntimeError(f"SHA-256 mismatch for {name}")
        pending.replace(destination)
    with destination.open("rb") as downloaded:
        actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError(f"Cached asset checksum mismatch: {destination}")
    return destination


def prepare_audio(destination: Path, cache: Path) -> None:
    """Copy a private renderer and corresponding source into the app resources."""
    if sys.platform not in {"darwin", "win32"}:
        return
    destination.mkdir(parents=True, exist_ok=True)
    source = download_asset("source", cache)
    shutil.copy2(source, destination / source.name)
    binary = download_asset(sys.platform, cache)
    if sys.platform == "win32":
        with zipfile.ZipFile(binary) as archive:
            for member in archive.infolist():
                target = (destination / member.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Unsafe path in upstream audio archive")
            archive.extractall(destination)
        if not list(destination.glob("**/sclang.exe")) or not list(destination.glob("**/scsynth.exe")):
            raise RuntimeError("The SuperCollider archive is missing renderer executables")
    else:
        result = subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(binary)],
                                check=True, capture_output=True)
        entities = plistlib.loads(result.stdout)["system-entities"]
        mounts = [item["mount-point"] for item in entities if "mount-point" in item]
        try:
            app = next(Path(mount) / "SuperCollider.app" for mount in mounts
                       if (Path(mount) / "SuperCollider.app").is_dir())
            subprocess.run(["ditto", str(app), str(destination / "SuperCollider.app")], check=True)
        finally:
            for mount in mounts:
                subprocess.run(["hdiutil", "detach", mount], check=True)
