"""Start the frozen application through its explicit runtime dispatcher.

Both desktop and console helpers share this entry point and bundled resources.
"""

from gaiascapes_host.bundled import main

if __name__ == "__main__":
    raise SystemExit(main())
