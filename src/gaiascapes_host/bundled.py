"""Run the desktop, server, or private worker from a bundled installation.

The installer supplies Python and immutable resources. User configuration,
logs, recordings, and databases stay in the selected runtime data directory.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import webbrowser

from .config import resolve_data_dir


def resources_dir() -> Path:
    """Locate installer documentation and renderer resources."""
    return Path(__file__).resolve().parent / "installation"


def external_environment() -> dict[str, str]:
    """Restore library paths before starting system audio executables."""
    environment = os.environ.copy()
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = environment.get(name + "_ORIG")
        if original is None:
            environment.pop(name, None)
        else:
            environment[name] = original
    return environment


def _install_media() -> int:
    """Download missing Commons recordings into this installation."""
    from .birdsong_cache import install_recordings
    return 1 if install_recordings(resolve_data_dir()) else 0


def _audio_command(data_dir: Path) -> list[str] | None:
    """Find the bundled or installed renderer and preserve audio preferences."""
    audio = resources_dir() / "audio"
    candidates = [audio / "SuperCollider.app/Contents/MacOS/sclang"]
    candidates += list(audio.glob("**/sclang.exe")) if sys.platform == "win32" else []
    if configured := os.environ.get("GAIA_SCAPE_SCLANG"):
        candidates.insert(0, Path(configured))
    if executable := shutil.which("sclang"):
        candidates.append(Path(executable))
    candidates += [Path("/Applications/SuperCollider.app/Contents/MacOS/sclang"),
                   Path.home() / "Applications/SuperCollider.app/Contents/MacOS/sclang"]
    if sys.platform == "win32":
        candidates += list(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob("SuperCollider*/sclang.exe"))
    sclang = next((path for path in candidates if path.is_file()), None)
    if sclang is None:
        print("SuperCollider is unavailable; synthesized audio is disabled.", file=sys.stderr)
        return None
    # Discovery by the UI and by sclang's server boot uses this process-only PATH.
    server_dir = sclang.parent.parent / "Resources" if sys.platform == "darwin" else sclang.parent
    os.environ["PATH"] = os.pathsep.join((str(sclang.parent), str(server_dir), os.environ.get("PATH", "")))
    device_file = data_dir / "audio-device"
    if not os.environ.get("GAIA_SCAPE_AUDIO_DEVICE") and device_file.is_file():
        os.environ["GAIA_SCAPE_AUDIO_DEVICE"] = device_file.read_text().strip()
    if os.environ.get("GAIA_SCAPE_AUDIO_DEVICE") == "system":
        os.environ.pop("GAIA_SCAPE_AUDIO_DEVICE")
    if sys.platform == "darwin" and not os.environ.get("GAIA_SCAPE_AUDIO_DEVICE"):
        try:
            profile = subprocess.run(
                ["/usr/sbin/system_profiler", "SPAudioDataType", "-json"],
                check=True, capture_output=True, text=True, timeout=15,
            )
            for section in json.loads(profile.stdout).get("SPAudioDataType", []):
                for device in section.get("_items", []):
                    if device.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                        os.environ["GAIA_SCAPE_AUDIO_DEVICE"] = device["_name"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            print(f"Could not resolve the macOS output device: {exc}", file=sys.stderr)
    command = [str(sclang), "-u", os.environ.get("GAIA_SCAPE_SCLANG_PORT", "57131"),
               str(resources_dir() / "gaia-scape.scd")]
    if sys.platform.startswith("linux") and shutil.which("wpctl") and shutil.which("pw-jack"):
        if subprocess.run(["wpctl", "status"], capture_output=True, env=external_environment(), timeout=5).returncode == 0:
            command.insert(0, "pw-jack")
    return command


def main(argv=None) -> int:
    """Dispatch bundled app modes without treating the executable as Python."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Workers must retain binary stdin/stdout and must not initialize the GUI.
    if arguments == ["--worker"]:
        from .worker import main as worker_main
        worker_main()
        return 0
    parser = argparse.ArgumentParser(description="Gaiascapes bundled application")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--server", action="store_true", help="Run without a desktop window")
    modes.add_argument("--install-media", action="store_true", help="Populate/repair Commons Birdsong")
    modes.add_argument("--user-guide", action="store_true", help="Open the included PDF guide")
    modes.add_argument("--version", action="store_true", help="Print the app version")
    parser.add_argument("--no-audio", action="store_true", help="Skip synthesized audio startup")
    options, remaining = parser.parse_known_args(arguments)
    if options.version:
        from gaiascapes import __version__
        print(__version__)
        return 0
    if options.user_guide:
        if remaining:
            parser.error("Unexpected arguments")
        return 0 if webbrowser.open((resources_dir() / "user_guide.pdf").as_uri()) else 1
    if remaining and not options.server:
        parser.error("Unexpected arguments: " + " ".join(remaining))
    data_dir = resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["GAIA_SCAPE_DATA_DIR"] = str(data_dir)
    if options.install_media:
        return _install_media()
    if options.server:
        from .__main__ import main as server_main
        server_main(remaining)
        return 0

    # Windowed Windows executables have no console streams. Persist startup
    # failures and renderer output in this installation, never in the bundle.
    with (data_dir / "desktop.log").open("a", buffering=1, encoding="utf-8") as log:
        previous_streams = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = log
        renderer = None
        try:
            if not options.no_audio:
                # Do not start another renderer when its OSC port is occupied.
                import socket
                from .config import AppConfig
                config = AppConfig.load(data_dir / "config.json")
                if config.osc_enabled and config.osc_host in {"127.0.0.1", "localhost"}:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                        try:
                            probe.bind(("127.0.0.1", config.osc_port))
                        except OSError:
                            pass
                        else:
                            probe.close()
                            command = _audio_command(data_dir)
                            if command:
                                renderer = subprocess.Popen(
                                    command, env=external_environment(), stdout=log, stderr=log,
                                    start_new_session=sys.platform != "win32",
                                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                )
            if os.environ.get("GAIA_SCAPE_INSTALL_BIRDSONG", "yes") != "no":
                threading.Thread(target=_install_media, daemon=True, name="birdsong-setup").start()
            from .desktop import main as desktop_main
            return desktop_main()
        except Exception:
            import traceback
            traceback.print_exc()
            return 1
        finally:
            if renderer is not None and renderer.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(renderer.pid), "/T", "/F"],
                                   stdout=log, stderr=log, env=external_environment(), check=False)
                else:
                    import signal
                    try:
                        os.killpg(renderer.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                try:
                    renderer.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if sys.platform != "win32":
                        os.killpg(renderer.pid, signal.SIGKILL)
                    else:
                        renderer.kill()
                    renderer.wait()
            sys.stdout, sys.stderr = previous_streams
