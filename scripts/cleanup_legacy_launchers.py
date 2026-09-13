"""Remove unused, installer-generated forwarding launchers from a runtime.

Only the three exact legacy wrappers are eligible. Current scripts, custom
launchers, symlinks, and wrappers referenced by user services are preserved.
"""

from __future__ import annotations

import os
from pathlib import Path
import plistlib
import sys


LAUNCHERS = ("run_gaiascapes.sh", "run_gaiascapes_gui.sh", "run_supercollider.sh")


def cleanup_legacy_launchers(runtime: Path, home: Path, config_home: Path) -> list[str]:
    """Remove redundant wrappers unless a user service still references them."""
    references = []
    try:
        for plist in (home / "Library/LaunchAgents").glob("*.plist"):
            document = plistlib.loads(plist.read_bytes())
            if not isinstance(document, dict):
                raise ValueError(f"Unexpected service document: {plist.name}")
            references.extend(str(value) for value in document.get("ProgramArguments", []))
            references.append(str(document.get("Program", "")))
        for unit in (config_home / "systemd/user").glob("*.service"):
            references.append(unit.read_text(encoding="utf-8"))
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        print(f"Legacy launcher cleanup skipped: could not inspect user service references ({exc}).")
        return []
    removed = []
    for name in LAUNCHERS:
        legacy = runtime / name
        current = runtime / "scripts" / name
        expected = f'#!/usr/bin/env bash\nexec "$(dirname -- "$0")/scripts/{name}" "$@"\n'
        if legacy.is_symlink() or not legacy.is_file() or not current.is_file():
            continue
        if legacy.read_text(encoding="utf-8", errors="replace") != expected:
            print(f"Preserving custom or unrecognized launcher: {legacy}")
            continue
        paths = (str(legacy), str(legacy).replace(" ", "\\x20"),
                 str(legacy).replace(" ", "\\ "))
        if any(path in reference for path in paths for reference in references):
            print(f"Preserving launcher referenced by a user service: {legacy}. Update the service to {current} first.")
            continue
        legacy.unlink()
        removed.append(name)
        print(f"Removed obsolete forwarding launcher: {legacy}; use {current}")
    return removed


if __name__ == "__main__":
    cleanup_legacy_launchers(Path(sys.argv[1]), Path.home(),
                            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))))
