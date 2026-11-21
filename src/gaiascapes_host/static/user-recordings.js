/* Import a catalog or append a recording through the Sound Sources tiles. */
(() => {
  const dialog = document.getElementById("recordingEntryDialog");
  const form = document.getElementById("recordingEntryForm");
  const importFields = document.getElementById("recordingImportFields");
  const localFields = document.getElementById("recordingLocalFields");
  const catalogFile = form.elements.namedItem("catalog");
  const summary = document.getElementById("recordingImportSummary");
  const status = document.getElementById("recordingEntryStatus");
  const submit = document.getElementById("recordingEntrySubmit");
  const close = document.getElementById("recordingEntryClose");
  const mib = 1024 * 1024;
  let selection;
  let busy = false;

  document.querySelectorAll("[data-recording-action]").forEach((button) => {
    button.addEventListener("click", () => {
      selection = button.dataset;
      const importing = selection.recordingAction === "import";
      form.reset();
      importFields.hidden = importFields.disabled = !importing;
      localFields.hidden = localFields.disabled = importing;
      summary.textContent = "";
      status.textContent = "";
      document.getElementById("recordingEntryTile").textContent = selection.recordingLabel;
      document.getElementById("recordingEntryTitle").textContent = importing ? "Import catalog" : "Add local sound/picture";
      submit.textContent = importing ? "Import recordings" : "Add recording";
      submit.disabled = false;
      dialog.showModal();
    });
  });

  async function readCatalog(file) {
    if (!file || file.size > mib) throw new Error("Choose a catalog JSON file up to 1 MiB.");
    let catalog;
    try {
      catalog = JSON.parse(await file.text());
    } catch {
      throw new Error("Choose a valid JSON catalog.");
    }
    if (catalog?.format_version !== 1 || !Array.isArray(catalog.recordings)
        || !catalog.recordings.length || catalog.recordings.length > 100) {
      throw new Error("Choose a version 1 Gaiascapes catalog with 1–100 recordings.");
    }
    if (catalog.recordings.some((entry) => entry?.kind !== selection.recordingKind)) {
      throw new Error(`This catalog must contain only recordings for ${selection.recordingLabel}.`);
    }
    return catalog;
  }

  catalogFile.addEventListener("change", async () => {
    const file = catalogFile.files[0];
    summary.textContent = "";
    status.textContent = "";
    if (!file) return;
    try {
      const entries = (await readCatalog(file)).recordings;
      if (catalogFile.files[0] === file) {
        const pictured = entries.filter((entry) => entry.picture).length;
        const label = entries.length === 1 ? "recording" : "recordings";
        summary.textContent = `${entries.length} ${label} · ${pictured} with pictures`;
      }
    } catch (error) {
      if (catalogFile.files[0] === file) status.textContent = error.message;
    }
  });

  function checkMedia(file, image) {
    const url = URL.createObjectURL(file);
    const player = document.createElement(image ? "img" : "audio");
    return new Promise((resolve, reject) => {
      const unavailable = () => reject(new Error(image ? "The picture could not be opened." : "The audio could not be opened."));
      const pending = setTimeout(unavailable, 10000);
      const ready = () => {
        const duration = player.duration;
        if (!image && (!Number.isFinite(duration) || duration <= 0)) unavailable();
        else resolve(duration);
      };
      player.onerror = unavailable;
      if (image) player.onload = ready;
      else {
        player.preload = "metadata";
        player.onloadedmetadata = ready;
      }
      player.src = url;
      player.addEventListener("error", () => clearTimeout(pending), {once: true});
      player.addEventListener(image ? "load" : "loadedmetadata", () => clearTimeout(pending), {once: true});
    }).finally(() => {
      player.removeAttribute("src");
      URL.revokeObjectURL(url);
    });
  }

  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => {
    if (busy) event.preventDefault();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !selection) return;
    busy = true;
    close.disabled = submit.disabled = true;
    const importing = selection.recordingAction === "import";
    status.textContent = importing ? "Checking and downloading catalog media…" : "Checking and saving the recording…";
    try {
      let body;
      const headers = {};
      if (importing) {
        body = JSON.stringify(await readCatalog(catalogFile.files[0]));
        headers["Content-Type"] = "application/json";
      } else {
        body = new FormData(form);
        const sound = body.get("sound");
        const picture = body.get("picture");
        if (!sound.size || sound.size > 64 * mib || !picture.size || picture.size > 10 * mib) {
          throw new Error("Choose audio up to 64 MiB and a picture up to 10 MiB.");
        }
        const [duration] = await Promise.all([checkMedia(sound, false), checkMedia(picture, true)]);
        body.set("duration_seconds", String(duration));
      }
      const response = await fetch(`/api/recordings/catalog/${selection.recordingKind}/${selection.recordingAction}`, {
        method: "POST", headers, body,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Unable to save the recording.");
      const skipped = result.skipped ? ` ${result.skipped} already in the catalog.` : "";
      status.textContent = `Added ${result.added} ${result.added === 1 ? "recording" : "recordings"}.${skipped}`;
      form.reset();
      summary.textContent = "";
      document.dispatchEvent(new Event("user-recordings-changed"));
    } catch (error) {
      status.textContent = error.message;
    } finally {
      busy = false;
      close.disabled = submit.disabled = false;
    }
  });
})();
