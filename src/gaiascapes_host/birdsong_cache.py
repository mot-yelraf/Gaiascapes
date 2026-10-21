"""Install the curated Commons Birdsong catalog for offline playback.

Downloads and attribution stay under the selected installation's data directory.
The setup HTTPS transport tries IPv4 first and bounds each connection attempt
so an unavailable IPv6 route cannot stall recording installation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time
import urllib.error

from .commons_birdsong import COMMONS_CATALOG, CommonsBirdsongClient
from .http_transport import build_opener


class _DownloadOpener:
    def __init__(self):
        self._opener = build_opener()
        self._last_request = 0.0

    def __call__(self, request, timeout):
        delay = 2.0 - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()
        return self._opener.open(request, timeout=timeout)


def install_recordings(data_dir: Path, client=None) -> int:
    """Cache every curated recording, report failures, and return their count."""
    if client is None:
        client = CommonsBirdsongClient(
            data_dir, opener=_DownloadOpener(),
            allow_downloads=True,
        )
    total = sum(len(location["recordings"]) for location in COMMONS_CATALOG)
    completed = failures = 0
    for cycle in range(max(len(location["recordings"]) for location in COMMONS_CATALOG)):
        for index, location in enumerate(COMMONS_CATALOG):
            if cycle >= len(location["recordings"]):
                continue
            title = location["recordings"][cycle]["title"]
            try:
                client.event_at(cycle * len(COMMONS_CATALOG) + index)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    remaining = total - completed
                    print(
                        f"Commons rate limit reached; {completed}/{total} recordings available locally. "
                        f"Retry after {exc.headers.get('Retry-After', 'a few minutes')}; "
                        "rerun the installer to resume without downloading completed files again.",
                        flush=True,
                    )
                    return remaining
                failures += 1
                print(f"Birdsong download failed: {title}: {exc}", flush=True)
            except Exception as exc:
                failures += 1
                print(f"Birdsong download failed: {title}: {exc}", flush=True)
            else:
                completed += 1
                print(f"Birdsong local recordings: {completed}/{total}: {title}", flush=True)
    print(f"Birdsong catalog: {completed}/{total} available locally; {failures} failed.", flush=True)
    return failures


def main(argv=None) -> int:
    """Install recordings into an explicitly selected application's data directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    return 1 if install_recordings(args.data_dir) else 0


if __name__ == "__main__":
    raise SystemExit(main())
