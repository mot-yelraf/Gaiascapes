/* Recording loudness adjustment and peak protection.
 * Measure gated RMS once per URL in this page, preserving the source files and
 * natural dynamics. This is an RMS approximation, not broadcast LUFS metering.
 */
const recordingNormalizer = (() => {
  let context;
  let output;
  const gains = new Map();

  function measureGain(buffer) {
    const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
    const blockSize = Math.max(1, Math.round(buffer.sampleRate * 0.4));
    const blocks = [];
    let peak = 0;
    for (let start = 0; start < buffer.length; start += blockSize) {
      const end = Math.min(buffer.length, start + blockSize);
      let energy = 0;
      for (const channel of channels) {
        for (let i = start; i < end; i++) {
          const sample = channel[i];
          if (!Number.isFinite(sample)) throw new Error("Recording contains invalid audio samples");
          peak = Math.max(peak, Math.abs(sample));
          energy += sample * sample;
        }
      }
      const count = (end - start) * channels.length;
      if (count && energy / count >= 1e-5) blocks.push({energy, count});
    }
    if (!blocks.length || !peak) return 1;
    const average = blocks.reduce((sum, b) => sum + b.energy, 0)
      / blocks.reduce((sum, b) => sum + b.count, 0);
    const audible = blocks.filter(b => b.energy / b.count >= average * 0.01);
    const rms = Math.sqrt(audible.reduce((sum, b) => sum + b.energy, 0)
      / audible.reduce((sum, b) => sum + b.count, 0));
    // Attenuate toward -30 dBFS RMS without ever boosting the source.
    return Math.min(1, 10 ** (-30 / 20) / rms, 0.85 / peak);
  }

  async function resume() {
    if (!context) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) throw new Error("This browser does not support recording normalization");
      context = new AudioContextClass();
      // A sample ceiling protects crossfade peaks without the automatic makeup
      // gain of DynamicsCompressorNode, which would amplify quiet recordings.
      output = context.createWaveShaper();
      output.curve = Float32Array.from({length: 4097}, (_, i) =>
        Math.max(-0.95, Math.min(0.95, i / 2048 - 1)));
      output.connect(context.destination);
    }
    await context.resume();
    if (context.state !== "running") throw new Error("Select Start or Preview to allow normalized audio");
  }

  // AudioBuffer playback uses the context unlocked by Listen, so every new
  // animal recording does not require another iPhone media-element gesture.
  function createPlayer() {
    const player = new EventTarget();
    player.webAudio = true;
    player.paused = true;
    player.ended = false;
    player.duration = NaN;
    let source;
    let startedAt = 0;
    let offset = 0;
    let timer;
    Object.defineProperty(player, "currentTime", {get: () => player.paused
      ? offset : Math.min(player.duration, offset + context.currentTime - startedAt)});
    player.play = async () => {
      source = context.createBufferSource();
      source.buffer = player.decodedBuffer;
      source.connect(player.input);
      offset = Math.max(0, Math.min(player.duration, player.startOffset || 0));
      startedAt = context.currentTime;
      player.paused = false;
      source.onended = () => {
        offset = player.duration;
        player.paused = true;
        player.ended = true;
        clearInterval(timer);
        source.disconnect();
        player.dispatchEvent(new Event("ended"));
      };
      source.start(0, offset);
      timer = setInterval(() => player.dispatchEvent(new Event("timeupdate")), 250);
    };
    player.pause = () => {
      offset = player.currentTime;
      player.paused = true;
      clearInterval(timer);
      if (source) { source.onended = null; source.stop(); source.disconnect(); source = null; }
    };
    player.removeAttribute = () => { player.decodedBuffer = null; };
    return player;
  }

  async function prepare(audio, url, signal) {
    let gain = gains.get(url);
    if (gain === undefined || audio.webAudio) {
      const response = await fetch(url, {signal});
      if (!response.ok) throw new Error(`Unable to load recording (HTTP ${response.status})`);
      const bytes = await response.arrayBuffer();
      let buffer;
      try {
        buffer = await context.decodeAudioData(bytes);
      } catch (error) {
        error.recordingFailure = "decode_failed";
        throw error;
      }
      signal.throwIfAborted();
      try {
        gain = measureGain(buffer);
      } catch (error) {
        error.recordingFailure = "decode_failed";
        throw error;
      }
      if (audio.webAudio) { audio.decodedBuffer = buffer; audio.duration = buffer.duration; }
      if (gains.size >= 64) gains.delete(gains.keys().next().value);
      gains.set(url, gain);
    }
    signal.throwIfAborted();
    const source = audio.webAudio ? context.createGain() : context.createMediaElementSource(audio);
    if (audio.webAudio) audio.input = source;
    const level = context.createGain();
    level.gain.value = gain;
    const volume = context.createGain();
    // Start silent, even on hosts that ignore HTMLMediaElement.volume.
    volume.gain.value = 0;
    source.connect(level);
    level.connect(volume);
    volume.connect(output);
    audio.setRecordingOutputGain = (value) => {
      volume.gain.value = Number.isFinite(value) ? Math.max(0, Math.min(0.75, value)) : 0;
    };
    audio.setRecordingOutputGain(audio.recordingOutputGain ?? 0);
    audio.volume = 1;
    audio.releaseNormalization = () => {
      source.disconnect();
      level.disconnect();
      volume.disconnect();
      delete audio.setRecordingOutputGain;
    };
  }

  return {resume, prepare, measureGain, createPlayer};
})();
