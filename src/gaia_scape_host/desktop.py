"""Browser-opening convenience entrypoint for desktop use."""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .app import create_app
from .config import AppConfig, resolve_data_dir


def main() -> None:
    """Start the server and open its local URL in the default browser."""
    config = AppConfig.load(resolve_data_dir() / "config.json")
    url = f"http://127.0.0.1:{config.http_port}"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(
        create_app(),
        host=config.http_host,
        port=config.http_port,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=4,
    )


if __name__ == "__main__":
    main()
