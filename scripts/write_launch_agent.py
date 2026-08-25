"""Write a path-safe macOS LaunchAgent plist for the installer.

The installer invokes this helper with resolved paths so plist serialization
does not depend on fragile shell escaping.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path


destination, launcher, data_dir = map(Path, sys.argv[1:4])
document = {
    "Label": "local.gaia-scape",
    "ProgramArguments": [str(launcher)],
    "RunAtLoad": True,
    "KeepAlive": True,
    "StandardOutPath": str(data_dir / "gaia-scape.log"),
    "StandardErrorPath": str(data_dir / "gaia-scape-error.log"),
}
with destination.open("wb") as output:
    plistlib.dump(document, output)
