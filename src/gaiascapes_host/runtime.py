"""Select subprocess entry points for source and bundled installations.

Frozen desktop apps use a separate console-capable helper so private worker
pipes remain available on Windows without opening a console for the GUI.
"""

from pathlib import Path
import sys


def module_command(module: str) -> list[str]:
    """Return the command for a supported Python module in this installation."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", module]
    modes = {"gaiascapes_host": "--server", "gaiascapes_host.worker": "--worker"}
    helper = Path(sys.executable).resolve().with_name(
        "gaiascapes-runtime.exe" if sys.platform == "win32" else "gaiascapes-runtime"
    )
    if not helper.is_file():
        raise RuntimeError(f"Bundled runtime helper is missing: {helper}")
    return [str(helper), modes[module]]
