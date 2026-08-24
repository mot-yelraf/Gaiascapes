const byId = (id) => document.getElementById(id);
let observedCueSequence = null;
let cuePollInFlight = false;
let observedHistorySignature = null;

function applyLiveMode(mode) {
  const continuous = mode === "continuous";
  document.querySelectorAll(".capture-only").forEach((element) => { element.hidden = continuous; });
  document.querySelectorAll(".continuous-only").forEach((element) => { element.hidden = !continuous; });
  byId("startButton").textContent = "Start";
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function when(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString() : "Not yet";
}

function message(text, error = false) {
  byId("message").textContent = text;
  byId("message").classList.toggle("error", error);
}

const EVENT_PALETTES = {
  earthquake: ["#765236", "#93643f", "#ad7749", "#c28b59", "#d0a06d"],
  ocean_swell: ["#214c5a", "#286579", "#327f94", "#489aab", "#6ab5bd"],
  tide_turn: ["#244d68", "#2e6685", "#3c80a0", "#579bb7", "#7bb5ca"],
  storm_potential: ["#3b4568", "#4c5782", "#606b9d", "#7882b5", "#969dcc"],
  default: ["#476352", "#567966", "#679079", "#7ca68d", "#96bba1"],
};

const INSTRUMENT_PALETTES = {
  seismic_bells: ["#4f321f", "#67432a", "#805537", "#9b6945", "#b98258"],
};

function eventColors(event, instrument = "") {
  const kind = String(event?.kind || "default").toLowerCase();
  const voice = String(instrument).toLowerCase();
  const palette = INSTRUMENT_PALETTES[voice] || EVENT_PALETTES[kind] || EVENT_PALETTES.default;
  const magnitude = Math.max(0, Number(event?.traits?.magnitude ?? event?.strength ?? 0));
  const index = Math.min(palette.length - 1, Math.floor(magnitude / 1.5));
  return {kind, primary: palette[index], inner: palette[Math.max(0, index - 1)]};
}

function cueRole(cue) {
  if (cue.role) return cue.role;
  return ["ocean_swell", "storm_potential"].includes(cue.event?.kind) ? "background" : "event";
}

function animateCapturedEvent(event, instrument = "", role = "event", cueDuration = 3.6) {
  const layer = byId("eventPulseLayer");
  if (!layer) return;
  const animationDuration = role === "background"
    ? Math.max(3.6, Number(cueDuration) || 3.6)
    : 3.6;
  const longitude = Number(event?.longitude ?? 0);
  const latitude = Number(event?.latitude ?? 0);
  const magnitude = Number(event?.traits?.magnitude ?? 2);
  const wave = document.createElement("span");
  const colors = eventColors(event, instrument);
  const safeKind = colors.kind.replace(/[^a-z0-9_-]/g, "-");
  wave.className = `event-wave event-wave--${safeKind} event-wave--${role}`;
  wave.dataset.eventKind = colors.kind;
  wave.dataset.cueRole = role;
  wave.style.setProperty("--wave-x", `${Math.max(8, Math.min(92, ((longitude + 180) / 360) * 100))}%`);
  wave.style.setProperty("--wave-y", `${Math.max(12, Math.min(88, ((90 - latitude) / 180) * 100))}%`);
  wave.style.setProperty("--wave-scale", String(Math.max(6, Math.min(13, 6 + magnitude))));
  wave.style.setProperty("--wave-color", colors.primary);
  wave.style.setProperty("--wave-inner", colors.inner);
  wave.style.setProperty("--wave-duration", `${animationDuration}s`);
  layer.append(wave);
  if (byId("settingsDialog")?.open) document.body.classList.add("preview-pulse-visible");
  const removeWave = () => {
    wave.remove();
    if (!layer.querySelector(".event-wave")) {
      document.body.classList.remove("preview-pulse-visible");
    }
  };
  wave.addEventListener("animationend", removeWave, {once: true});
  setTimeout(removeWave, (animationDuration * 1000) + 400);
}

async function updateStatus() {
  try {
    const status = await request("/api/status");
    byId("eventCount").textContent = status.history.event_count.toLocaleString();
    const historySignature = `${status.history.event_count}:${status.history.latest_timestamp ?? ""}`;
    const historyChanged = observedHistorySignature !== null && observedHistorySignature !== historySignature;
    observedHistorySignature = historySignature;
    byId("captureTime").textContent = when(status.capture.last_at);
    const location = status.cues.latest_location;
    const locationText = location
      ? (location.name || `${Number(location.latitude).toFixed(2)}, ${Number(location.longitude).toFixed(2)}`)
      : "—";
    byId("locationStatus").textContent = locationText;
    byId("locationStatus").title = locationText === "—" ? "" : locationText;
    byId("systemPulse").classList.add("online");
    byId("systemPulse").querySelector("strong").textContent = status.capture.last_error ? "Capture warning" : "Online";
    const continuous = status.live.mode === "continuous";
    byId("liveMode").value = status.live.mode;
    applyLiveMode(status.live.mode);
    const active = continuous ? status.live.running : status.performance.running;
    byId("performanceBadge").textContent = continuous
      ? (status.live.running ? `Continuous · ${status.live.played_count} cues` : "Paused")
      : (status.performance.running ? `Playing ${status.performance.played_count}/${status.performance.cue_count}` : "Capture");
    byId("performanceBadge").classList.toggle("running", active);
    if (status.capture.last_error) message(status.capture.last_error, true);
    if (historyChanged) await updateEvents();
  } catch (error) {
    byId("systemPulse").classList.remove("online");
    byId("systemPulse").querySelector("strong").textContent = "Unavailable";
    message(error.message, true);
  }
}

async function updateEmittedCues() {
  if (cuePollInFlight) return;
  cuePollInFlight = true;
  let retryDelay = 0;
  try {
    const query = observedCueSequence === null ? "" : `?after=${observedCueSequence}`;
    const payload = await request(`/api/cues${query}`);
    payload.cues.forEach((cue) => animateCapturedEvent(
      cue.event, cue.instrument, cueRole(cue), cue.duration,
    ));
    if (payload.cues.length) await updateEvents();
    observedCueSequence = payload.latest_sequence;
  } catch (error) {
    console.warn("Unable to synchronize emitted cues", error);
    retryDelay = 1000;
  } finally {
    cuePollInFlight = false;
  }
  setTimeout(updateEmittedCues, retryDelay);
}

async function updateEvents() {
  try {
    const hours = Number(byId("hours").value);
    const payload = await request(`/api/events?hours=${encodeURIComponent(hours)}&limit=100`);
    const events = payload.events;
    byId("eventList").innerHTML = events.length ? events.map((event) => {
      const summary = eventSummary(event);
      const place = event.traits.place || `${event.latitude.toFixed(2)}, ${event.longitude.toFixed(2)}`;
      const instrument = instrumentLabel(event.instrument);
      return `<div class="event"><span class="magnitude">${escapeHtml(summary.badge)}</span><div><strong>${escapeHtml(place)}</strong><small>${escapeHtml(summary.detail)} · ${escapeHtml(instrument)} · ${event.latitude.toFixed(2)}, ${event.longitude.toFixed(2)}</small></div><time>${when(event.timestamp)}</time></div>`;
    }).join("") : '<p class="empty">No events in this history window.</p>';
  } catch (error) {
    message(error.message, true);
  }
}

function instrumentLabel(instrument) {
  if (instrument === "seismic_bells") return "Seismic Bell";
  if (instrument === "none") return "No instrument";
  return String(instrument || "Unassigned").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventSummary(event) {
  const traits = event.traits || {};
  if (event.kind === "ocean_swell") {
    const height = Number(traits.swell_height_m ?? traits.wave_height_m ?? 0);
    const period = Number(traits.swell_period_s ?? 0);
    return {badge: `${height.toFixed(1)}m`, detail: `${period.toFixed(1)}s modeled swell`};
  }
  if (event.kind === "tide_turn") {
    const state = String(traits.tide_state || "tide").toUpperCase();
    return {badge: state, detail: `${Number(traits.sea_level_msl_m ?? 0).toFixed(2)}m modeled sea level`};
  }
  if (event.kind === "storm_potential") {
    return {badge: "CAPE", detail: `${Number(traits.cape_jkg ?? 0).toFixed(0)} J/kg forecast storm potential`};
  }
  return {
    badge: `M${Number(traits.magnitude || 0).toFixed(1)}`,
    detail: `${Number(traits.depth_km || 0).toFixed(1)} km deep`,
  };
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value);
  return node.innerHTML;
}

byId("startButton").addEventListener("click", async () => {
  try {
    if (byId("liveMode").value === "continuous") {
      await request("/api/live/start", {method: "POST", body: "{}"});
      message("Continuous environmental sound is running with global ocean and storm rotation.");
    } else {
      const payload = await request("/api/performance/replay", {
        method: "POST",
        body: JSON.stringify({hours: Number(byId("hours").value), performance_seconds: Number(byId("duration").value)}),
      });
      message(`Started ${payload.cue_count} cues from ${payload.event_count} captured events.`);
    }
    await updateStatus();
  } catch (error) { message(error.message, true); }
});

byId("stopButton").addEventListener("click", async () => {
  try {
    const continuous = byId("liveMode").value === "continuous";
    await request(continuous ? "/api/live/stop" : "/api/performance/stop", {method: "POST", body: "{}"});
    message(continuous ? "Continuous environmental sound paused." : "Performance stopped.");
    await updateStatus();
  } catch (error) { message(error.message, true); }
});

byId("liveMode").addEventListener("change", async (event) => {
  const mode = event.target.value;
  applyLiveMode(mode);
  try {
    const live = await request("/api/live/mode", {
      method: "PUT", body: JSON.stringify({mode}),
    });
    message(mode === "continuous"
      ? "Continuous mode started: live event voices over the selected rotating global background."
      : "Capture mode selected. Start replays stored history while capture continues automatically.");
    byId("performanceBadge").textContent = live.running ? "Continuous" : "Capture";
    await updateStatus();
  } catch (error) { message(error.message, true); }
});

applyLiveMode(byId("liveMode").value);

byId("hours").addEventListener("change", updateEvents);

const settingsDialog = byId("settingsDialog");
const settingsForm = byId("settingsForm");
if (settingsDialog && settingsForm) {
  const tabs = Array.from(settingsDialog.querySelectorAll("[data-settings-pane]"));
  const panes = Array.from(settingsDialog.querySelectorAll("[data-pane]"));

  function activatePane(name, focusTab = false) {
    tabs.forEach((tab) => {
      const active = tab.dataset.settingsPane === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      if (active && focusTab) tab.focus();
    });
    panes.forEach((pane) => {
      const active = pane.dataset.pane === name;
      pane.classList.toggle("is-active", active);
      pane.hidden = !active;
    });
  }

  function openSettings() {
    if (typeof settingsDialog.showModal === "function") {
      settingsDialog.showModal();
    } else {
      settingsDialog.setAttribute("open", "");
      settingsDialog.setAttribute("aria-modal", "true");
    }
    document.body.classList.add("modal-open");
    activatePane("sources");
  }

  function closeSettings() {
    if (typeof settingsDialog.close === "function") settingsDialog.close();
    else settingsDialog.removeAttribute("open");
    document.body.classList.remove("modal-open");
  }

  document.querySelectorAll("[data-open-settings]").forEach((button) => button.addEventListener("click", openSettings));
  settingsDialog.querySelectorAll("[data-close-settings]").forEach((button) => button.addEventListener("click", closeSettings));
  tabs.forEach((tab, index) => {
    const name = tab.dataset.settingsPane;
    const pane = panes.find((item) => item.dataset.pane === name);
    tab.id = `settings-tab-${name}`;
    tab.setAttribute("aria-controls", `settings-pane-${name}`);
    pane.id = `settings-pane-${name}`;
    pane.setAttribute("role", "tabpanel");
    pane.setAttribute("aria-labelledby", tab.id);
    tab.addEventListener("click", () => activatePane(name));
    tab.addEventListener("keydown", (event) => {
      if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const forward = event.key === 'ArrowDown' || event.key === 'ArrowRight';
      const next = (index + (forward ? 1 : -1) + tabs.length) % tabs.length;
      activatePane(tabs[next].dataset.settingsPane, true);
    });
  });
  settingsDialog.addEventListener("cancel", (event) => { event.preventDefault(); closeSettings(); });
  settingsDialog.addEventListener("click", (event) => {
    if (event.target !== settingsDialog) return;
    const rect = settingsDialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeSettings();
  });
  settingsDialog.querySelectorAll(".preview-instrument-button").forEach((button) => {
    const instrumentSelect = byId(button.dataset.select);
    const updatePreviewState = () => { button.disabled = instrumentSelect.value === "none"; };
    instrumentSelect.addEventListener("change", updatePreviewState);
    updatePreviewState();
    button.addEventListener("click", async () => {
      const status = byId("settingsStatus");
      button.disabled = true;
      status.textContent = "Playing preview…";
      status.classList.remove("error");
      try {
        const instrument = byId(button.dataset.select).value;
        const kind = button.dataset.kind === "background" ? instrument : button.dataset.kind;
        const payload = await request("/api/instruments/preview", {
          method: "POST",
          body: JSON.stringify({kind, instrument}),
        });
        status.textContent = "Previewed " + payload.instrument.replaceAll("_", " ") + ".";
        await Promise.all([updateStatus(), updateEvents()]);
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
      } finally {
        updatePreviewState();
      }
    });
  });
  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = byId("settingsStatus");
    status.textContent = "Saving…";
    status.classList.remove("error");
    try {
      await request("/api/settings/audio", {
        method: "PUT",
        body: JSON.stringify({
          enabled_sources: [
            ...(byId("sourceUsgs").checked ? ["usgs"] : []),
            ...(byId("sourceMarine").checked ? ["open_meteo_marine"] : []),
            ...(byId("sourceStorm").checked ? ["open_meteo_storm"] : []),
          ],
          instrument_slots: {
            event_1: byId("event1Instrument").value,
            event_2: byId("event2Instrument").value,
            background: byId("backgroundInstrument").value,
          },
        }),
      });
      status.textContent = "Settings saved. Changes apply to the next event or background update.";
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  });
}

Promise.all([updateStatus(), updateEvents(), updateEmittedCues()]);
setInterval(updateStatus, 3000);
