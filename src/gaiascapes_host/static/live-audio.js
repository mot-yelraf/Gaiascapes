/* Per-device playback of framed stereo PCM from the host renderer.
 * Short scheduled buffers work on ordinary LAN HTTP, without AudioWorklet's
 * secure-context requirement. Late data is discarded instead of accumulating.
 */
class LiveAudioPlayer {
  constructor(onState) {
    this.onState = onState;
    this.context = null;
    this.controller = null;
    this.sources = new Set();
    this.retryTimer = null;
    this.retryDelay = 1000;
    this.wanted = false;
  }

  async unlock(reset = false) {
    if (!this.context || this.context.state === 'closed') {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) throw new Error('This browser does not support audio playback.');
      this.context = new AudioContextClass();
    }
    const context = this.context;
    let timer;
    try {
      const operation = reset && context.state === 'running'
        ? context.suspend().then(() => context.resume()) : context.resume();
      await Promise.race([operation, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Audio did not resume. Tap Listen to retry.')), 5000);
      })]);
    } finally {
      clearTimeout(timer);
    }
    if (context.state !== 'running') throw new Error('Tap Listen to allow audio playback.');
  }

  /** Resume the existing audio context and replace any pre-sleep stream. */
  async recover() {
    if (!this.wanted) return;
    const context = this.context;
    // Discard pre-sleep PCM and reconnect at the live edge after resuming.
    clearTimeout(this.retryTimer);
    this.disconnect();
    try {
      await this.unlock(true);
    } catch (error) {
      if (this.wanted && context === this.context) throw error;
      return;
    }
    if (this.wanted && context === this.context) await this.start();
  }

  async start() {
    const context = this.context;
    this.wanted = true;
    clearTimeout(this.retryTimer);
    this.disconnect();
    const controller = new AbortController();
    this.controller = controller;
    this.nextTime = 0;
    this.sequence = null;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      if (!context || context.state !== 'running') throw new Error('Tap Listen to allow audio playback.');
      const response = await fetch('/api/audio/stream', {signal: controller.signal, cache: 'no-store'});
      if (!response.ok) throw new Error(`Host audio unavailable (HTTP ${response.status}).`);
      if (!response.body) throw new Error('This browser does not support live audio streaming.');
      if (controller !== this.controller || !this.wanted) return;
      this.onState('listening');
      this.read(response.body.getReader(), controller).catch(error => this.reconnect(controller, error));
    } catch (error) {
      this.reconnect(controller, error);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  reconnect(controller, error) {
    if (!this.wanted || controller !== this.controller) return;
    this.disconnect();
    this.onState('reconnecting', error.message);
    this.retryTimer = setTimeout(() => {
      if (this.wanted) this.start().catch(() => {});
    }, this.retryDelay);
    this.retryDelay = Math.min(30000, this.retryDelay * 2);
  }

  async read(reader, controller) {
    let pending = new Uint8Array(0);
    const blockBytes = 12 + 512 * 2 * 4;
    try {
      while (!controller.signal.aborted) {
        let timer;
        let chunk;
        try {
          chunk = await Promise.race([
            reader.read(),
            new Promise((_, reject) => {
              timer = setTimeout(() => reject(new Error('Host audio stalled.')), 10000);
            }),
          ]);
        } finally {
          clearTimeout(timer);
        }
        const {value, done} = chunk;
        if (done) throw new Error('Host audio disconnected. Tap Listen to reconnect.');
        const bytes = new Uint8Array(pending.length + value.length);
        bytes.set(pending);
        bytes.set(value, pending.length);
        let offset = 0;
        while (offset + blockBytes <= bytes.length) {
          this.schedule(new DataView(bytes.buffer, offset, blockBytes));
          offset += blockBytes;
        }
        pending = bytes.slice(offset);
      }
    } finally {
      reader.cancel().catch(() => {});
    }
  }

  schedule(packet) {
    if (packet.getUint32(0, false) !== 0x47414941) throw new Error('Invalid host audio stream.');
    const sequence = packet.getUint32(4, true);
    const rate = packet.getUint32(8, true);
    if (rate < 8000 || rate > 192000) throw new Error('Invalid host audio sample rate.');
    const context = this.context;
    if (!context || context.state !== 'running') {
      throw new Error('Audio was paused by this browser. Tap Listen to reconnect.');
    }
    if (this.sequence !== null && sequence <= this.sequence) return;
    const duration = 512 / rate;
    if (this.sequence !== null) this.nextTime += Math.min(0.25, (sequence - this.sequence - 1) * duration);
    this.sequence = sequence;
    this.retryDelay = 1000;
    if (this.nextTime <= context.currentTime) this.nextTime = context.currentTime + 0.15;
    // Keep a slow/backgrounded browser from replaying an old backlog.
    if (this.nextTime > context.currentTime + 0.75) return;
    const buffer = context.createBuffer(2, 512, rate);
    for (let channel = 0; channel < 2; channel++) {
      const samples = buffer.getChannelData(channel);
      for (let frame = 0; frame < 512; frame++) {
        const value = packet.getFloat32(12 + (frame * 2 + channel) * 4, true);
        if (!Number.isFinite(value)) throw new Error('Invalid host audio sample.');
        samples[frame] = Math.max(-0.95, Math.min(0.95, value));
      }
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    this.sources.add(source);
    source.onended = () => { source.disconnect(); this.sources.delete(source); };
    source.start(this.nextTime);
    this.nextTime += duration;
  }

  disconnect() {
    this.controller?.abort();
    this.controller = null;
    this.sources.forEach(source => { source.stop(); source.disconnect(); });
    this.sources.clear();
  }

  stop() {
    this.wanted = false;
    clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.disconnect();
    if (this.context) this.context.close().catch(() => {});
    this.context = null;
  }
}
