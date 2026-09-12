/* Session playback and per-tile answer visibility, shared by both views. */
(() => {
  const buttons = Array.from(document.querySelectorAll("[data-playback-action]"));
  const status = document.getElementById("playbackControlStatus");
  let playing = false;
  let pending = "";

  function refresh() {
    const selected = pending || (playing ? "play" : "pause");
    buttons.forEach(button => {
      button.disabled = Boolean(pending);
      button.setAttribute("aria-pressed", String(button.dataset.playbackAction === selected));
    });
  }
  globalThis.gaiascapesControls = {
    previewEvent: null,
    setPlaying(active) {
      playing = Boolean(active);
      if (playing && pending !== "next") globalThis.gaiascapesControls.previewEvent = null;
      refresh();
    },
    showError(detail) { status.textContent = detail; },
  };
  buttons.forEach(button => button.addEventListener("click", async () => {
    if (pending) return;
    pending = button.dataset.playbackAction;
    status.textContent = "";
    refresh();
    try {
      if (pending === "pause") await stopPlayback();
      else if (pending === "play") {
        globalThis.gaiascapesControls.previewEvent = null;
        await startPlayback();
      } else {
        // Block late audio completions and cue polls during image-only stepping.
        globalThis.gaiascapesControls.previewEvent = {};
        stopRecordingPlayback(1);
        status.textContent = "Loading next animal…";
        const result = await request("/api/recordings/next-image", {method: "POST", body: "{}"});
        globalThis.gaiascapesControls.previewEvent = result.event;
        updateBackgroundStatus(result.event);
        await globalThis.animalWikipedia?.update(result.event);
        playing = false;
        status.textContent = "Paused at next animal. Press Play to hear it.";
        await updateStatus();
      }
    } catch (error) {
      status.textContent = error.message;
      if (globalThis.gaiascapesControls.previewEvent && !globalThis.gaiascapesControls.previewEvent.kind) {
        globalThis.gaiascapesControls.previewEvent = null;
      }
      await updateStatus();
    } finally {
      pending = "";
      refresh();
    }
  }));

  const selectors = Array.from(document.querySelectorAll("[data-status-visibility]"));
  selectors.forEach((selector) => {
    selector.addEventListener("change", () => {
      selectors.filter(other => other.dataset.statusVisibility === selector.dataset.statusVisibility)
        .forEach((other) => {
          other.value = selector.value;
          other.closest(".status-card").removeAttribute("title");
          document.getElementById(other.getAttribute("aria-controls")).hidden = selector.value === "hide";
        });
    });
  });
  // The first status request may have finished before this script loaded.
  updateStatus();
})();
