"""Tests for installation and service-launch scripts.

Static assertions protect platform delegation, safe runtime paths, dedicated
ports, data preservation, and optional SuperCollider configuration.
"""

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
    assert "pywebview>=5.4,<6.0" in Path("requirements.txt").read_text(encoding="utf-8")
    assert "import webview" in installer
    assert "gir1.2-webkit2-4.1" in installer


def test_platform_installers_delegate_to_common_installer():
    for path in ("scripts/install_macos.sh", "scripts/install_linux.sh"):
        assert 'exec "$SCRIPT_DIR/../install.sh"' in Path(path).read_text(encoding="utf-8")


def test_uninstaller_preserves_data_by_default_and_rejects_broad_targets():
    script = Path("uninstall.sh").read_text(encoding="utf-8")

    assert '""|/|"$HOME"' in script
    assert 'GAIA_SCAPE_REMOVE_DATA:-no' in script
    assert 'rm -rf "$INSTALL_DIR/data"' in script
    assert 'Library/Application Support/Gaia Scape/Gaia Scape.app' in script
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
    assert "s.options.memSize = 65536" in synth
    assert synth.index("s.waitForBoot") < synth.index("SynthDef")
    assert synth.index("s.sync") < synth.index("OSCdef")
    assert "msg[2].asString" in synth
    assert "msg[3].asString" in synth
    assert "(duration - 1.5).max(0.4)" in synth
    assert "(duration - 0.08).max(1.0)" in synth
    assert "SynthDef(\\stormRainLayer" in synth
    assert "SynthDef(\\lightningGlass" in synth
    assert "SynthDef(\\naturalThunder" in synth
    assert 'if(instrument == "natural_thunder", { synthName = \\naturalThunder })' in synth
    assert 'if(kind != "lightning_flash"' in synth
    assert "pitchContour = XLine.kr" in synth
    assert "Dust2.ar(8 + (strength * 28)" in synth
    assert "BrownNoise.ar(0.9)" in synth
    assert "Compander.ar(signal, signal" in synth
    assert "Limiter.ar(signal, 0.82" in synth
    earthquake = synth.split("SynthDef(\\earthquake", 1)[1].split("}).add;", 1)[0]
    assert "life = duration.clip(1.4, 8)" in earthquake
    assert "(freq * 0.25).clip(26, 52)" in earthquake
    assert "pWaveDelay = depth.clip(0, 700).linlin(0, 700, 0.16, 0.5)" in earthquake
    assert "surfaceMotion = SinOsc.kr" in earthquake
    assert "bodyMotion = LFNoise1.kr" in earthquake
    assert "pWave = SinOsc.ar" in earthquake
    assert "rumbleFreq * [2.2, 3.4]" in earthquake
    assert "rumbleFreq * [1, 1.006, 2.03]" in earthquake
    assert ".exprange(55, 125)" in earthquake
    assert "envelope * amp * 3.75" in earthquake
    assert "onsetEnvelope" not in earthquake
    seismic_bells = synth.split("SynthDef(\\seismicBells", 1)[1].split("}).add;", 1)[0]
    assert "duration.clip(0.18, 1.78) * 2.4" in seismic_bells
    natural_thunder = synth.split("SynthDef(\\naturalThunder", 1)[1].split("}).add;", 1)[0]
    assert ".exprange(85, 360)" in natural_thunder
    assert "HPF.ar(BrownNoise.ar(0.8), 45)" in natural_thunder
    assert "DelayC.ar" not in natural_thunder
    assert "AllpassC.ar" not in natural_thunder
    assert "drySignal = Pan2.ar(rumble + deepBody, pan)" in natural_thunder
    assert "reflections = reflections + Pan2.ar" in natural_thunder
    assert "    crackEnvelope = EnvGen.ar" not in natural_thunder
    assert "    crackSource = WhiteNoise.ar" not in natural_thunder
    assert "    crack = Mix(BPF.ar" not in natural_thunder
    assert "rainDensity = 10 + (smoothStrength * 110)" in synth
    assert "Dust2.ar(rainDensity" in synth
