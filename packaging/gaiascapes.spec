# PyInstaller builds on the target operating system and CPU architecture.
from importlib import metadata
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "src"))
from gaiascapes import __version__

resources = "gaiascapes_host/installation"
datas = collect_data_files("gaiascapes_host")
for name in ("user_guide.pdf", "LICENSE", "THIRD_PARTY_NOTICES.md", "PRIVACY.md", "SECURITY.md"):
    datas.append((str(root / name), resources))
datas.append((str(root / "supercollider/gaia-scape.scd"), resources))
# Retain installed distribution metadata, including supplied license files.
for distribution in metadata.distributions():
    datas += copy_metadata(distribution.metadata["Name"])

hidden = collect_submodules("gaiascapes_host") + [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "netCDF4", "eumdac",
]
analysis = Analysis([str(root / "packaging/entrypoint.py")],
                    pathex=[str(root / "src")], datas=datas, hiddenimports=hidden,
                    excludes=["tkinter", "pytest", "IPython"], noarchive=False)
archive = PYZ(analysis.pure)
icon = root / "src/gaiascapes_host/static"
icon = str(icon / ("gaia-scape-desktop-icon.icns" if sys.platform == "darwin"
                   else "gaia-scape-desktop-icon.ico")) if sys.platform in {"darwin", "win32"} else None
desktop = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="Gaiascapes",
              console=sys.platform.startswith("linux"), icon=icon)
runtime = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="gaiascapes-runtime",
              console=True, icon=icon)
collection = COLLECT(desktop, runtime, analysis.binaries, analysis.datas, name="Gaiascapes")
if sys.platform == "darwin":
    numeric_version = ".".join(str(int(part)) for part in __version__.removeprefix("v0.").split("."))
    app = BUNDLE(collection, name="Gaiascapes.app", icon=icon,
                 bundle_identifier="earth.gaiascape.GaiaScape",
                 version=numeric_version,
                 info_plist={"CFBundleDisplayName": "Gaiascapes", "NSHighResolutionCapable": True})
