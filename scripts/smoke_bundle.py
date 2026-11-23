"""Verify a frozen app's Python workers, native decoder, assets, and HTTP API.

All subprocesses use disposable data and temporary loopback ports. The installed
runtime is never started or used as a test target.
"""

import json
import os
from pathlib import Path
import pickle
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request


def main() -> None:
    """Exercise the actual executable independently of the build interpreter."""
    bundle = Path(sys.argv[1]).resolve()
    mac = bundle.suffix == ".app"
    executable_dir = bundle / "Contents/MacOS" if mac else bundle
    helper = executable_dir / ("gaiascapes-runtime.exe" if os.name == "nt" else "gaiascapes-runtime")
    resources = (bundle / "Contents/Resources" if mac else bundle / "_internal") / "gaiascapes_host/installation"
    assert (resources / "user_guide.pdf").read_bytes().startswith(b"%PDF-")
    prompt = Path(__file__).resolve().parents[1] / "create_catalog.md"
    assert (resources / prompt.name).read_bytes() == prompt.read_bytes()
    from netCDF4 import Dataset
    with tempfile.TemporaryDirectory(prefix="gaiascapes-bundle-smoke-") as temporary:
        data = Path(temporary) / "data"
        data.mkdir()
        config = {"enabled_sources": [], "osc_enabled": False, "config_revision": 8,
                  "http_port": 8769, "osc_port": 57130}
        (data / "config.json").write_text(json.dumps(config))
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("GAIA_SCAPE_", "PYTHON", "DYLD_", "LD_LIBRARY_PATH", "SSL_CERT_"))}
        environment.update(GAIA_SCAPE_DATA_DIR=str(data), GAIA_SCAPE_INSTALL_BIRDSONG="no")
        result = subprocess.run([str(helper), "--version"], env=environment, cwd=temporary,
                                check=True, capture_output=True, timeout=30)
        version = result.stdout.decode().strip()
        assert version.startswith("v0.")
        # The builder's system trust store can hide broken certificate paths
        # on clean machines. Require the frozen runtime to supply usable roots.
        operation = ("function", "ssl", "get_default_verify_paths", (), {})
        result = subprocess.run([str(helper), "--worker"], input=pickle.dumps(operation),
                                env=environment, cwd=temporary, check=True, capture_output=True, timeout=30)
        certificates, changes, error = pickle.loads(result.stdout)
        assert error is None, error
        assert certificates.cafile and Path(certificates.cafile).is_file()
        context = ssl.create_default_context(cafile=certificates.cafile)
        assert context.cert_store_stats()["x509_ca"] > 0
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        # Check fresh-install defaults inside the frozen runtime independently
        # of the offline HTTP fixture, which deliberately disables all feeds.
        operation = ("function", "gaiascapes_host.config", "AppConfig", (), {})
        result = subprocess.run([str(helper), "--worker"], input=pickle.dumps(operation),
                                env=environment, cwd=temporary, check=True, capture_output=True, timeout=30)
        defaults, changes, error = pickle.loads(result.stdout)
        assert error is None, error
        assert {"open_meteo_storm", "open_meteo_marine"} <= set(defaults.enabled_sources)
        assert defaults.background_animation == "murmuration"
        assert defaults.background_murmuration_palette == "aurora"
        operation = ("function", "importlib.metadata", "version", ("gaiascapes",), {})
        result = subprocess.run([str(helper), "--worker"], input=pickle.dumps(operation),
                                env=environment, cwd=temporary, check=True, capture_output=True, timeout=30)
        package_version, changes, error = pickle.loads(result.stdout)
        assert error is None, error
        assert package_version == version.removeprefix("v")
        # Force a real native NetCDF decode in the bundled worker process.
        netcdf = Path(temporary) / "sample.nc"
        with Dataset(netcdf, "w") as dataset:
            dataset.createDimension("number_of_flashes", 3)
        operation = ("function", "gaiascapes_host.noaa_glm", "count_glm_flashes", (netcdf.read_bytes(),), {})
        result = subprocess.run([str(helper), "--worker"], input=pickle.dumps(operation),
                                env=environment, cwd=temporary, check=True, capture_output=True, timeout=45)
        count, changes, error = pickle.loads(result.stdout)
        assert error is None, error
        assert count == 3 and changes == {}
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (Path(temporary) / "server.log").open("w+") as log:
            process = subprocess.Popen([str(helper), "--server", "--no-capture", "--host", "127.0.0.1", "--port", str(port)],
                                       cwd=temporary, env=environment, stdout=log, stderr=log)
            try:
                ready = False
                for attempt in range(120):
                    if process.poll() is not None:
                        break
                    try:
                        with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                            ready = json.load(response)["version"] == version
                        if ready:
                            break
                    except OSError:
                        time.sleep(0.25)
                if not ready:
                    log.seek(0)
                    raise RuntimeError("Bundled server failed: " + log.read())
                for route in ("/", "/static/app.js", "/api/events"):
                    with opener.open(f"http://127.0.0.1:{port}{route}", timeout=10) as response:
                        assert response.status == 200
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        saved = json.loads((data / "config.json").read_text())
        assert saved["http_port"] == 8769 and saved["osc_port"] == 57130
    print(f"Frozen {version}: HTTPS roots, weather source defaults, Murmuration/Aurora, PDF, catalog prompt, worker pipes, NetCDF, HTTP API, and web assets passed")


if __name__ == "__main__":
    main()
