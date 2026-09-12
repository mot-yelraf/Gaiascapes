/* Spoken recording labels share the unlocked recording audio context.
 * Each device cancels stale speech independently of the host and other players.
 */
globalThis.recordingAnnouncements = (() => {
  const tile = document.getElementById("announcementTile");
  const status = document.getElementById("announcementStatus");
  let settings = {
    announcements_enabled: tile.dataset.enabled === "true",
    announcement_voice: tile.dataset.voice,
    announcement_volume: Number(tile.dataset.volume),
  };
  let generation = 0;
  let controller;
  let player;
  let lastSequence = null;

  function enabled() {
    return settings.announcements_enabled && settings.announcement_volume > 0;
  }

  function release(audio) {
    if (!audio || audio.announcementReleased) return;
    audio.announcementReleased = true;
    audio.pause();
    audio.releaseNormalization?.();
    audio.removeAttribute("src");
  }

  function stop() {
    generation += 1;
    controller?.abort();
    controller = null;
    if (player) {
      release(player);
      player = null;
    }
  }

  async function play(cue) {
    if (cue.sequence === lastSequence) return;
    stop();
    if (!enabled()) return;
    lastSequence = cue.sequence;
    const current = generation;
    const requestController = new AbortController();
    controller = requestController;
    const timeout = setTimeout(() => requestController.abort(new Error("Announcement timed out")), 45000);
    let audio;
    let url;
    let onAbort;
    try {
      const response = await fetch(`/api/announcements/${encodeURIComponent(cue.sequence)}`, {signal: requestController.signal});
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Announcement unavailable (HTTP ${response.status})`);
      }
      url = URL.createObjectURL(await response.blob());
      if (generation !== current) return;
      audio = recordingNormalizer.createPlayer();
      await recordingNormalizer.resume();
      await recordingNormalizer.prepare(audio, url, requestController.signal);
      if (generation !== current) return;
      player = audio;
      audio.setRecordingOutputGain(settings.announcement_volume ** 2 * 0.75);
      const ended = new Promise((resolve, reject) => {
        audio.addEventListener("ended", resolve, {once: true});
        onAbort = () => reject(requestController.signal.reason);
        requestController.signal.addEventListener("abort", onAbort, {once: true});
      });
      requestController.signal.throwIfAborted();
      status.textContent = response.headers?.get("X-Announcement-Fallback") || "";
      await Promise.all([audio.play(), ended]);
    } catch (error) {
      if (generation === current) {
        status.textContent = `Announcement unavailable: ${error.message}`;
        stop();
      }
    } finally {
      clearTimeout(timeout);
      if (url) URL.revokeObjectURL(url);
      if (onAbort) requestController.signal.removeEventListener("abort", onAbort);
      if (player === audio) player = null;
      release(audio);
    }
  }

  function configure(values) {
    stop();
    settings = values;
    lastSequence = null;
  }
  return {play, stop, configure, enabled};
})();
