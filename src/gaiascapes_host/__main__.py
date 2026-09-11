"""Command-line entrypoint for the Gaiascapes web server.

Command-line options select the HTTP bind address and delegate application
serving to Uvicorn without enabling noisy access logs.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import os
import signal
import sys
import threading

import uvicorn

from .config import AppConfig, resolve_data_dir
from .desktop import DESKTOP_OWNER_PID_ENV


def _console_log_config() -> dict:
    """Timestamp server and provider logs in local time."""
    config = deepcopy(uvicorn.config.LOGGING_CONFIG)
    for formatter in config["formatters"].values():
        formatter["fmt"] = "%(asctime)s " + formatter["fmt"]
        formatter["datefmt"] = "%Y-%m-%d %H:%M:%S"
    config["loggers"]["gaiascapes_host"] = {
        "handlers": ["default"], "level": "INFO", "propagate": False,
    }
    return config


def _watch_desktop_owner(
    owner_pid: int, stop_event: threading.Event, interval: float = 0.5
) -> None:
    """Terminate this server when its owning desktop process disappears."""
    while not stop_event.wait(interval):
        if os.getppid() == owner_pid:
            continue
        os.kill(os.getpid(), signal.SIGTERM)
        return


def main(argv=None) -> None:
    """Run the installed web application."""
    defaults = AppConfig.load(resolve_data_dir() / "config.json")
    parser = argparse.ArgumentParser(description="Run Gaiascapes")
    parser.add_argument("--host", default=defaults.http_host)
    parser.add_argument("--port", default=defaults.http_port, type=int)
    parser.add_argument("--no-capture", action="store_true")
    args = parser.parse_args(argv)

    from .app import create_app

    app = create_app(auto_capture=not args.no_capture)
    print(f"Gaiascapes is listening on http://127.0.0.1:{args.port}")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"LAN access: http://<this-computer-ip>:{args.port}")
    owner_stop = threading.Event()
    owner_thread = None
    raw_owner_pid = os.environ.get(DESKTOP_OWNER_PID_ENV)
    if raw_owner_pid:
        try:
            owner_pid = int(raw_owner_pid)
        except ValueError:
            print(
                f"Ignoring invalid {DESKTOP_OWNER_PID_ENV}: {raw_owner_pid!r}",
                file=sys.stderr,
            )
        else:
            owner_thread = threading.Thread(
                target=_watch_desktop_owner,
                args=(owner_pid, owner_stop),
                name="gaiascapes-desktop-owner",
                daemon=True,
            )
            owner_thread.start()
    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            log_config=_console_log_config(),
            access_log=False,
            timeout_graceful_shutdown=4,
        )
    finally:
        owner_stop.set()
        if owner_thread is not None:
            owner_thread.join(timeout=1)


if __name__ == "__main__":
    main()
