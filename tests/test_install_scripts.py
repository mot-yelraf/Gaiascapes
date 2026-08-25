from pathlib import Path


def test_installer_uses_dedicated_ports_and_chosen_runtime():
    installer = Path("install.sh").read_text(encoding="utf-8")
    launcher = Path("run_gaia_scape.sh").read_text(encoding="utf-8")

    assert "GAIA_SCAPE_INSTALL_DIR" in installer
    assert 'GAIA_SCAPE_AUDIO_DEVICE' in installer
    assert "install-location" in installer
    assert 'mkdir -p "$INSTALL_DIR/data"' in installer
    assert "http://127.0.0.1:8768" in installer
    assert 'GAIA_SCAPE_DATA_DIR="$RUNTIME_DIR/data"' in launcher
    assert "8000" not in installer
    assert "8765" not in installer
    assert "8767" not in installer
    assert "requirements.txt" in installer
    assert "SYSTEM_REQUIREMENTS.md" in installer
    assert "astral>=3.2,<4.0" in Path("requirements.txt").read_text(encoding="utf-8")


def test_platform_installers_delegate_to_common_installer():
    for path in ("scripts/install_macos.sh", "scripts/install_linux.sh"):
        assert 'exec "$SCRIPT_DIR/../install.sh"' in Path(path).read_text(encoding="utf-8")


def test_uninstaller_preserves_data_by_default_and_rejects_broad_targets():
    script = Path("uninstall.sh").read_text(encoding="utf-8")

    assert '""|/|"$HOME"' in script
    assert 'GAIA_SCAPE_REMOVE_DATA:-no' in script
    assert 'rm -rf "$INSTALL_DIR/data"' in script
    assert 'Application data remains in %s/data' in script


def test_gui_launcher_supervises_audio_and_audio_device_is_configurable():
    gui = Path("run_gaia_scape_gui.sh").read_text(encoding="utf-8")
    audio = Path("run_supercollider.sh").read_text(encoding="utf-8")
    synth = Path("supercollider/gaia-scape.scd").read_text(encoding="utf-8")

    assert '"$RUNTIME_DIR/run_supercollider.sh" &' in gui
    assert "trap cleanup EXIT INT TERM" in gui
    assert "data/audio-device" in audio
    assert "GAIA_SCAPE_AUDIO_DEVICE" in audio
    assert 'GAIA_SCAPE_SCLANG_PORT:-57131' in audio
    assert 'exec "$SCLANG" -u "$SCLANG_PORT"' in audio
    assert 'GAIA_SCAPE_HTTP_HOST="${GAIA_SCAPE_HTTP_HOST:-0.0.0.0}"' in gui
    assert '\"GAIA_SCAPE_AUDIO_DEVICE\".getenv' in synth
    assert "s.options.outDevice = audioDevice" in synth
    assert synth.index("s.waitForBoot") < synth.index("SynthDef")
    assert synth.index("s.sync") < synth.index("OSCdef")
    assert "msg[2].asString" in synth
    assert "msg[3].asString" in synth
    assert "(duration - 1.5).max(0.4)" in synth
    assert "(duration - 0.08).max(1.0)" in synth
    assert "SynthDef(\\stormRainLayer" in synth
    assert "SynthDef(\\lightningGlass" in synth
    assert "pitchContour = XLine.kr" in synth
    assert "Dust2.ar(8 + (strength * 28)" in synth
    assert "rainDensity = 10 + (smoothStrength * 110)" in synth
    assert "Dust2.ar(rainDensity" in synth
