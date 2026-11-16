"""Build native installers with a private Python runtime and user guide.

Run on each target OS/architecture in a dedicated build environment. Generated
artifacts and build work stay under installers/; installed user data is untouched.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))
from gaiascapes import __version__
from audio import prepare_audio


def run(*command: str) -> None:
    """Execute a build tool and stop on failure."""
    print("Running: " + " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True, cwd=ROOT)


def build_deb(bundle: Path, work: Path, output: Path, name: str, arch: str) -> Path:
    """Package the private runtime with Debian desktop and audio prerequisites."""
    deb_arch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armhf"}[arch]
    staging = work / "deb"
    app = staging / "opt/gaiascapes"
    app.parent.mkdir(parents=True)
    shutil.copytree(bundle, app, symlinks=True)
    control = staging / "DEBIAN"
    control.mkdir()
    installed_size = sum(path.stat().st_size for path in app.rglob("*") if path.is_file()) // 1024
    (control / "control").write_text(
        f"Package: gaiascapes\nVersion: {__version__.removeprefix('v')}\nArchitecture: {deb_arch}\n"
        "Maintainer: Gaiascapes <noreply@github.com>\nSection: sound\nPriority: optional\n"
        f"Installed-Size: {installed_size}\n"
        "Depends: libc6 (>= 2.36), libgtk-3-0, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, "
        "libgirepository-1.0-1, supercollider-language, supercollider-server, pipewire-jack, wireplumber\n"
        "Description: Living Earth soundscapes with a private Python runtime\n"
        " Live environmental events, local history, desktop and browser interfaces.\n"
        " Internet access is required. User data is preserved under ~/Gaiascapes/data.\n"
    )
    applications = staging / "usr/share/applications"
    applications.mkdir(parents=True)
    (applications / "earth.gaia_scape.GaiaScape.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Gaiascapes\n"
        "Comment=Living Earth soundscapes\nExec=/opt/gaiascapes/Gaiascapes\n"
        "Icon=earth.gaia_scape.GaiaScape\nTerminal=false\nCategories=AudioVideo;Audio;\n"
        "StartupWMClass=earth.gaia_scape.GaiaScape\n"
    )
    icons = staging / "usr/share/icons/hicolor/512x512/apps"
    icons.mkdir(parents=True)
    shutil.copy2(ROOT / "src/gaiascapes_host/static/gaia-scape-desktop-icon.png",
                 icons / "earth.gaia_scape.GaiaScape.png")
    docs = staging / "usr/share/doc/gaiascapes"
    docs.mkdir(parents=True)
    for source in (ROOT / "user_guide.pdf", ROOT / "installers/README.md", ROOT / "LICENSE",
                   ROOT / "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(source, docs / source.name)
    destination = output / f"{name}.deb"
    run("dpkg-deb", "--root-owner-group", "--build", staging, destination)
    return destination


def build_macos(bundle: Path, work: Path, output: Path, name: str) -> list[Path]:
    """Create a drag-install disk image and a standard macOS package."""
    # Ad-hoc signing supports local execution on Apple Silicon. This is neither
    # Developer ID signing nor notarization; Gatekeeper approval may be needed.
    run("codesign", "--force", "--deep", "--sign", "-", bundle)
    run("codesign", "--verify", "--deep", "--strict", bundle)
    payload = work / "pkg-root/Applications"
    payload.mkdir(parents=True)
    run("ditto", bundle, payload / bundle.name)
    component_plist = work / "components.plist"
    run("pkgbuild", "--analyze", "--root", payload.parent, component_plist)
    import plistlib
    components = plistlib.loads(component_plist.read_bytes())
    # Do not relocate an existing bundle or preserve stale nested Python files.
    for component in components:
        component["BundleIsRelocatable"] = False
        component["BundleIsVersionChecked"] = False
        component["BundleOverwriteAction"] = "upgrade"
    component_plist.write_bytes(plistlib.dumps(components))
    pkg = output / f"{name}.pkg"
    run("pkgbuild", "--root", payload.parent, "--component-plist", component_plist,
        "--identifier", "earth.gaiascape.GaiaScape.installer", "--version",
        __version__.removeprefix("v"), "--install-location", "/", pkg)
    image = work / "disk-image"
    image.mkdir()
    run("ditto", bundle, image / bundle.name)
    (image / "Applications").symlink_to("/Applications", target_is_directory=True)
    shutil.copy2(ROOT / "user_guide.pdf", image / "user_guide.pdf")
    shutil.copy2(ROOT / "installers/README.md", image / "INSTALLATION.txt")
    dmg = output / f"{name}.dmg"
    run("hdiutil", "create", "-volname", "Gaiascapes", "-srcfolder", image,
        "-format", "UDZO", "-ov", dmg)
    return [pkg, dmg]


def build_windows(bundle: Path, work: Path, output: Path, name: str) -> Path:
    """Build a per-user setup executable including the WebView2 bootstrapper."""
    setup = work / "MicrosoftEdgeWebview2Setup.exe"
    with urllib.request.urlopen("https://go.microsoft.com/fwlink/p/?LinkId=2124703", timeout=120) as response:
        with setup.open("wb") as target:
            shutil.copyfileobj(response, target)
    # Microsoft signs this bootstrapper; refuse a modified or unsigned payload.
    run("powershell.exe", "-NoProfile", "-Command",
        "$s=Get-AuthenticodeSignature -LiteralPath '" + str(setup).replace("'", "''") + "'; "
        "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') { exit 1 }")
    compiler = shutil.which("ISCC.exe")
    if not compiler:
        candidate = Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")
        compiler = str(candidate) if candidate.is_file() else None
    if not compiler:
        raise RuntimeError("Install Inno Setup 6 to build the Windows setup executable")
    run(compiler, f"/DBundleDir={bundle}", f"/DSourceRoot={ROOT}",
        f"/DOutputDir={output}", f"/DOutputName={name}",
        f"/DAppVersion={__version__.removeprefix('v')}", f"/DWebViewSetup={setup}",
        ROOT / "packaging/windows.iss")
    return output / f"{name}.exe"


def main() -> None:
    """Freeze, smoke-test, and package the current platform's application."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-only", action="store_true", help="Freeze and verify without creating the OS installer")
    parser.add_argument("--without-audio", action="store_true", help="Omit private SuperCollider on macOS/Windows")
    args = parser.parse_args()
    for dependency in ("PyInstaller", "webview", "netCDF4", "eumdac"):
        if importlib.util.find_spec(dependency) is None:
            parser.error(f"Missing {dependency}. Install packaging/requirements-build.txt and .[desktop,lightning,eumetsat]")
    arch = platform.machine().lower()
    if sys.platform == "win32" and arch not in {"amd64", "x86_64"}:
        parser.error("The Windows installer currently targets x64")
    output = ROOT / "installers"
    output.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="build-", dir=output))
    name = f"Gaiascapes-{__version__}-{platform.system().lower()}-{arch}"
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", work / "dist",
        "--workpath", work / "pyinstaller", ROOT / "packaging/gaiascapes.spec")
    bundle = work / "dist" / ("Gaiascapes.app" if sys.platform == "darwin" else "Gaiascapes")
    resources = (bundle / "Contents/Resources" if sys.platform == "darwin" else bundle / "_internal")
    resources = resources / "gaiascapes_host/installation"
    if not args.without_audio:
        prepare_audio(resources / "audio", output / ".cache")
    shutil.copy2(ROOT / "installers/README.md", resources / "INSTALLATION.txt")
    run(sys.executable, ROOT / "scripts/smoke_bundle.py", bundle)
    artifacts = []
    if not args.bundle_only:
        if sys.platform == "darwin":
            artifacts = build_macos(bundle, work, output, name)
        elif sys.platform == "win32":
            artifacts = [build_windows(bundle, work, output, name)]
        elif sys.platform.startswith("linux"):
            artifacts = [build_deb(bundle, work, output, name, arch)]
        else:
            parser.error("Supported build platforms: macOS, Linux, Windows")
    manifest = {"version": __version__, "system": platform.system(), "architecture": arch,
                "build_os": platform.platform(), "python": platform.python_version(),
                "private_supercollider": not args.without_audio and sys.platform in {"darwin", "win32"},
                "bundle": str(bundle.relative_to(output)), "files": {}}
    for artifact in artifacts:
        with artifact.open("rb") as file:
            manifest["files"][artifact.name] = hashlib.file_digest(file, "sha256").hexdigest()
    (output / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified bundle: {bundle}")
    for artifact in artifacts:
        print(f"Installer: {artifact}")


if __name__ == "__main__":
    main()
