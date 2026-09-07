"""Write a path-safe user-level systemd service for the installer.

The installer supplies resolved runtime paths and this helper safely encodes
them into a service unit for the current user.
"""

from __future__ import annotations

import sys
from pathlib import Path


destination, launcher = map(Path, sys.argv[1:3])
escaped_launcher = str(launcher).replace("\\", "\\\\").replace('"', '\\"')
destination.write_text(
    "\n".join(
        (
            "[Unit]",
            "Description=Gaiascapes terrestrial sonification",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=simple",
            f'ExecStart="{escaped_launcher}"',
            "Restart=on-failure",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        )
    ),
    encoding="utf-8",
)
