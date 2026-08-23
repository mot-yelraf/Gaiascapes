"""Write a path-safe macOS LaunchAgent plist for the installer."""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path


destination, launcher, data_dir = map(Path, sys.argv[1:4])
document = {
    "Label": "local.gaia-rhythms",
    "ProgramArguments": [str(launcher)],
    "RunAtLoad": True,
    "KeepAlive": True,
    "StandardOutPath": str(data_dir / "gaia-rhythms.log"),
    "StandardErrorPath": str(data_dir / "gaia-rhythms-error.log"),
}
with destination.open("wb") as output:
    plistlib.dump(document, output)

