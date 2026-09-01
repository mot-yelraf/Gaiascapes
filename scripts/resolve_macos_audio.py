#!/usr/bin/env python3
"""Report the user-selected macOS audio output device.

The launcher uses System Profiler's JSON output so device names containing
spaces or punctuation can be passed to SuperCollider without text scraping.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def selected_output_name(profile: dict[str, Any]) -> str | None:
    """Return the default audio output name from a System Profiler payload."""
    for section in profile.get("SPAudioDataType", []):
        for device in section.get("_items", []):
            if device.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                name = device.get("_name")
                if isinstance(name, str) and name:
                    return name
    return None


def main() -> int:
    """Print the selected output name, returning failure when it is unavailable."""
    result = subprocess.run(
        ["/usr/sbin/system_profiler", "SPAudioDataType", "-json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return result.returncode
    try:
        name = selected_output_name(json.loads(result.stdout))
    except json.JSONDecodeError:
        return 1
    if not name:
        return 1
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
