"""Command-line entrypoint for the Gaia Rhythms web server."""

from __future__ import annotations

import argparse

import uvicorn

from .config import AppConfig, resolve_data_dir


def main(argv=None) -> None:
    """Run the installed web application."""
    defaults = AppConfig.load(resolve_data_dir() / "config.json")
    parser = argparse.ArgumentParser(description="Run Gaia Rhythms")
    parser.add_argument("--host", default=defaults.http_host)
    parser.add_argument("--port", default=defaults.http_port, type=int)
    parser.add_argument("--no-capture", action="store_true")
    args = parser.parse_args(argv)

    from .app import create_app

    app = create_app(auto_capture=not args.no_capture)
    print(f"Gaia Rhythms is listening on http://127.0.0.1:{args.port}")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"LAN access: http://<this-computer-ip>:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=4,
    )


if __name__ == "__main__":
    main()
