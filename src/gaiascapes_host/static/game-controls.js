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
    setPlaying(active) {
      playing = Boolean(active);
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
      else {
        const next = pending === "next";
        if (next) status.textContent = "Loading next recording…";
        if (await startPlayback(next)) status.textContent = "";
      }
    } catch (error) {
      status.textContent = error.message;
      await updateStatus();
    } finally {
      pending = "";
      refresh();
    }
  }));

  const selectors = Array.from(document.querySelectorAll("[data-status-visibility]"));
  selectors.forEach((selector) => {
    selector.addEventListener("change", (event) => {
      selectors.filter(other => other.dataset.statusVisibility === selector.dataset.statusVisibility)
        .forEach((other) => {
          other.querySelectorAll('input[type="radio"]').forEach((input) => {
            input.checked = input.value === event.target.value;
          });
          other.closest(".status-card").removeAttribute("title");
          document.getElementById(other.getAttribute("aria-controls")).hidden = event.target.value === "hide";
        });
    });
  });
  // The first status request may have finished before this script loaded.
  updateStatus();
})();
