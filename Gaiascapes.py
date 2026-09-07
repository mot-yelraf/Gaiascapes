"""Source-checkout launcher for Gaiascapes.

This shim preserves a convenient top-level command while delegating runtime
startup to the installed host package.
"""

from gaiascapes_host.__main__ import main


if __name__ == "__main__":
    main()
