"""Install the curated Commons Birdsong catalog for offline playback.

Downloads and attribution stay under the selected installation's data directory.
The setup HTTPS transport tries IPv4 first and bounds each connection attempt
so an unavailable IPv6 route cannot stall recording installation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error

from .commons_birdsong import COMMONS_CATALOG, CommonsBirdsongClient
from .http_transport import build_opener


def read_download_progress(data_dir: Path) -> dict | None:
    """Read the setup process's latest atomic download status."""
    try:
        progress = json.loads((Path(data_dir) / "birdsong-download.json").read_text())
        if (not isinstance(progress, dict)
                or not isinstance(progress.get("state"), str)
                or progress.get("state") not in {"downloading", "complete", "error"}
                or any(type(progress.get(key)) is not int or progress[key] < 0
                       for key in ("pid", "current", "total", "completed"))
                or not 0 < progress["pid"] < 2**31
                or any(not isinstance(progress.get(key), str) for key in ("title", "error"))):
            raise ValueError("Invalid birdsong download status")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {"state": "error", "error": f"Cannot read birdsong download progress: {exc}"}
    if progress["state"] == "downloading" and os.name != "nt":
        try:
            os.kill(progress["pid"], 0)
        except ProcessLookupError:
            progress.update(state="error", error="Birdsong download was interrupted. Restart the app to resume.")
        except PermissionError:
            pass
    return progress


def _write_download_progress(data_dir: Path, **progress) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "birdsong-download.json"
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps({**progress, "pid": os.getpid()}), encoding="utf-8")
    pending.replace(path)


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
    current = 0
    for cycle in range(max(len(location["recordings"]) for location in COMMONS_CATALOG)):
        for index, location in enumerate(COMMONS_CATALOG):
            if cycle >= len(location["recordings"]):
                continue
            title = location["recordings"][cycle]["title"]
            current += 1
            _write_download_progress(
                data_dir, state="downloading", current=current, total=total,
                completed=completed, title=title, error="",
            )
            try:
                client.event_at(cycle * len(COMMONS_CATALOG) + index)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    remaining = total - completed
                    _write_download_progress(
                        data_dir, state="error", current=current, total=total,
                        completed=completed, title=title,
                        error=f"Commons rate limit reached. {completed}/{total} files ready. "
                              f"Retry after {exc.headers.get('Retry-After', 'a few minutes')}; restart the app to resume.",
                    )
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
    _write_download_progress(
        data_dir, state="error" if failures else "complete", current=current,
        total=total, completed=completed, title="",
        error=f"Birdsong downloads: {completed}/{total} files ready; {failures} failed. Restart the app to retry." if failures else "",
    )
    return failures


def main(argv=None) -> int:
    """Install recordings into an explicitly selected application's data directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    return 1 if install_recordings(args.data_dir) else 0


if __name__ == "__main__":
    raise SystemExit(main())
