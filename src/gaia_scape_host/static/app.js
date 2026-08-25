const byId = (id) => document.getElementById(id);
let observedCueSequence = null;
let cuePollInFlight = false;
let observedHistorySignature = null;
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

const ROBINSON_X = [1, .9986, .9954, .99, .9822, .973, .96, .9427, .9216, .8962, .8679, .835, .7986, .7597, .7186, .6732, .6213, .5722, .5322];
const ROBINSON_Y = [0, .062, .124, .186, .248, .31, .372, .434, .4958, .5571, .6176, .6769, .7346, .7903, .8435, .8936, .9394, .9761, 1];

function interpolateRobinson(table, latitude) {
  const position = Math.min(18, Math.abs(Number(latitude)) / 5);
  const lower = Math.floor(position);
  const upper = Math.min(18, lower + 1);
  return table[lower] + ((table[upper] - table[lower]) * (position - lower));
}

function projectCoordinates(longitude, latitude) {
  const safeLongitude = Math.max(-180, Math.min(180, Number(longitude) || 0));
  const safeLatitude = Math.max(-90, Math.min(90, Number(latitude) || 0));
  const xScale = interpolateRobinson(ROBINSON_X, safeLatitude);
  const yScale = interpolateRobinson(ROBINSON_Y, safeLatitude);
  return {
    x: 512 + (443 * (safeLongitude / 180) * xScale),
    y: 512 - (Math.sign(safeLatitude) * 290 * yScale),
  };
}

function inverseProjectCoordinates(x, y) {
  const normalizedY = Math.max(-1, Math.min(1, (512 - y) / 290));
  const targetY = Math.abs(normalizedY);
  let band = 0;
  while (band < ROBINSON_Y.length - 2 && ROBINSON_Y[band + 1] < targetY) band += 1;
  const span = ROBINSON_Y[band + 1] - ROBINSON_Y[band] || 1;
  const latitude = Math.sign(normalizedY) * ((band + ((targetY - ROBINSON_Y[band]) / span)) * 5);
  const xScale = interpolateRobinson(ROBINSON_X, latitude);
  const longitude = ((x - 512) / (443 * xScale)) * 180;
  return {latitude, longitude};
}

function createSvgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

function mapPath(points) {
  return points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
}

function mapProjectionBoundary() {
  const points = [];
  for (let latitude = -90; latitude <= 90; latitude += 2) points.push(projectCoordinates(180, latitude));
  for (let latitude = 90; latitude >= -90; latitude -= 2) points.push(projectCoordinates(-180, latitude));
  return `${mapPath(points)} Z`;
}

function renderMapProjection() {
  const boundary = mapProjectionBoundary();
  ["mapGlobeClipPath", "mapGlowPath", "mapOceanPath"].forEach((id) => {
    byId(id)?.setAttribute("d", boundary);
  });
}

function mapContainsPoint(x, y) {
  const normalizedY = (512 - Number(y)) / 290;
  if (Math.abs(normalizedY) > 1) return false;
  const latitude = inverseProjectCoordinates(512, y).latitude;
  const halfWidth = 443 * interpolateRobinson(ROBINSON_X, latitude);
  return Math.abs(Number(x) - 512) <= halfWidth;
}

function renderMapGrid() {
  const layer = byId("mapGridLayer");
  const labels = byId("mapCoordinateLabels");
  if (!layer || !labels) return;
  for (let latitude = -60; latitude <= 60; latitude += 30) {
    const points = [];
    for (let longitude = -180; longitude <= 180; longitude += 4) points.push(projectCoordinates(longitude, latitude));
    layer.append(createSvgElement("path", {d: mapPath(points), class: `map-grid-line${latitude === 0 ? " map-grid-equator" : ""}`}));
    if (latitude !== 0) {
      const position = projectCoordinates(-180, latitude);
      const label = createSvgElement("text", {x: position.x - 8, y: position.y + 4, class: "map-coordinate-label", "text-anchor": "end"});
      label.textContent = `${Math.abs(latitude)}°${latitude > 0 ? "N" : "S"}`;
      labels.append(label);
    }
  }
  for (let longitude = -180; longitude <= 180; longitude += 30) {
    const points = [];
    for (let latitude = -90; latitude <= 90; latitude += 3) points.push(projectCoordinates(longitude, latitude));
    layer.append(createSvgElement("path", {d: mapPath(points), class: `map-grid-line${longitude === 0 ? " map-grid-prime" : ""}`}));
    if (longitude % 60 === 0) {
      const position = projectCoordinates(longitude, 0);
      const label = createSvgElement("text", {x: position.x, y: 826, class: "map-coordinate-label", "text-anchor": "middle"});
      label.textContent = longitude === 0 ? "0°" : `${Math.abs(longitude)}°${longitude > 0 ? "E" : "W"}`;
      labels.append(label);
    }
  }
}

function mapMarkerTitle(event) {
  const place = event.traits?.place || event.kind;
  const magnitude = Number(event.traits?.magnitude);
  const magnitudeText = event.kind === "earthquake" && Number.isFinite(magnitude)
    ? ` · M${magnitude.toFixed(1)}`
    : "";
  return `${place}${magnitudeText} · ${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)}`;
}

function updateMapBackgroundLocation(location, color = EVENT_PALETTES.ocean_swell[3]) {
  const layer = byId("mapBackgroundLayer");
  if (!layer) return;
  layer.replaceChildren();
  if (!location) return;
  const position = projectCoordinates(location.longitude, location.latitude);
  const ring = createSvgElement("circle", {cx: position.x, cy: position.y, r: 11, class: "map-background-marker", stroke: color});
  ring.style.color = color;
  const core = createSvgElement("circle", {cx: position.x, cy: position.y, r: 4, class: "map-background-core", fill: color});
  const title = createSvgElement("title");
  title.textContent = `${location.name || "Background sound"} · ${Number(location.latitude).toFixed(2)}, ${Number(location.longitude).toFixed(2)}`;
  ring.append(title);
  layer.append(ring, core);
}

function renderMapHistory(events) {
  const layer = byId("mapHistoryLayer");
  if (!layer) return;
  layer.replaceChildren();
  events.slice().reverse().forEach((event) => {
    const position = projectCoordinates(event.longitude, event.latitude);
    const colors = eventColors(event, event.instrument);
    const marker = createSvgElement("circle", {cx: position.x, cy: position.y, r: 3.7, class: "map-history-marker", fill: colors.primary});
    const title = createSvgElement("title");
    title.textContent = mapMarkerTitle(event);
    marker.append(title);
    layer.append(marker);
  });
}

function animateMapEvent(event, instrument, role, animationDuration) {
  const layer = byId("mapPulseLayer");
  if (!layer) return;
  const colors = eventColors(event, instrument);
  const position = projectCoordinates(event.longitude, event.latitude);
  const group = createSvgElement("g", {class: `map-cue map-cue--${role}`});
  const pulse = createSvgElement("circle", {cx: position.x, cy: position.y, r: role === "background" ? 10 : 7, class: "map-cue-pulse", stroke: colors.primary});
  const core = createSvgElement("circle", {cx: position.x, cy: position.y, r: role === "background" ? 5 : 4, class: "map-cue-core", fill: colors.primary});
  const title = createSvgElement("title");
  title.textContent = mapMarkerTitle(event);
  pulse.style.setProperty("--map-pulse-duration", `${animationDuration}s`);
  pulse.style.setProperty("--map-pulse-scale", role === "background" ? "3.1" : "2.8");
  group.append(title, pulse, core);
  layer.append(group);
  if (role === "background") updateMapBackgroundLocation({name: event.traits?.place || "", latitude: event.latitude, longitude: event.longitude}, colors.primary);
  setTimeout(() => group.remove(), (animationDuration * 1000) + 400);
}

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
  return timestamp
    ? new Date(timestamp * 1000).toLocaleString().replace(/,\s*/, " ")
    : "Not yet";
}

function message(text, error = false) {
  byId("message").textContent = text;
  byId("message").classList.toggle("error", error);
}

function updateSoundLocation(location) {
  const locationText = location
    ? (location.name || `${Number(location.latitude).toFixed(2)}, ${Number(location.longitude).toFixed(2)}`)
    : "—";
  byId("backgroundSoundsStatus").textContent = locationText;
  byId("backgroundSoundsStatus").title = locationText === "—" ? "" : locationText;
  updateMapBackgroundLocation(location);
}

function backgroundSoundLabel(instrument) {
  if (instrument === "ocean_swell") return "Ocean Swells";
  if (instrument === "storm_potential") return "Storm Outlook";
  return "Background Sounds";
}

function updateBackgroundSoundsTitle(instrument) {
  byId("backgroundSoundsTitle").textContent = backgroundSoundLabel(instrument);
}

const EVENT_PALETTES = {
  earthquake: ["#765236", "#93643f", "#ad7749", "#c28b59", "#d0a06d"],
  ocean_swell: ["#214c5a", "#286579", "#327f94", "#489aab", "#6ab5bd"],
  tide_turn: ["#244d68", "#2e6685", "#3c80a0", "#579bb7", "#7bb5ca"],
  lightning_flash: ["#79500a", "#9d6a10", "#c58a1b", "#e5aa2b", "#ffd15a"],
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

function animateCapturedEvent(event, instrument = "", role = "event", cueDuration = 3.6, volume = 1) {
  const animationDuration = role === "background"
    ? Math.max(3.6, Number(cueDuration) || 3.6)
    : 3.6;
  animateMapEvent(event, instrument, role, animationDuration);
  if (!byId("mapView")?.hidden) return;
  const layer = byId("eventPulseLayer");
  if (!layer) return;
  const longitude = Number(event?.longitude ?? 0);
  const latitude = Number(event?.latitude ?? 0);
  const magnitude = Number(event?.traits?.magnitude ?? 2);
  const visualVolume = Math.max(0, Math.min(1, Number(volume) || 0));
  const baseScale = Math.max(6, Math.min(13, 6 + magnitude));
  const wave = document.createElement("span");
  const colors = eventColors(event, instrument);
  const safeKind = colors.kind.replace(/[^a-z0-9_-]/g, "-");
  wave.className = `event-wave event-wave--${safeKind} event-wave--${role}`;
  wave.dataset.eventKind = colors.kind;
  wave.dataset.cueRole = role;
  wave.style.setProperty("--wave-x", `${Math.max(8, Math.min(92, ((longitude + 180) / 360) * 100))}%`);
  wave.style.setProperty("--wave-y", `${Math.max(12, Math.min(88, ((90 - latitude) / 180) * 100))}%`);
  // Keep muted/quiet cues visible, while making pulse diameter follow slot volume.
  wave.style.setProperty("--wave-scale", String(Math.max(1.5, baseScale * visualVolume)));
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
    byId("eventTimeStatus").textContent = when(status.capture.last_at);
    updateSoundLocation(status.cues.latest_background_location);
    const eventSounds = (status.cues.latest_event_sounds || []).map(instrumentLabel).join(" + ") || "—";
    byId("eventSoundsStatus").textContent = eventSounds;
    byId("eventSoundsStatus").title = eventSounds === "—" ? "" : eventSounds;
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
    payload.cues.forEach((cue) => {
      animateCapturedEvent(
        cue.event, cue.instrument, cueRole(cue), cue.duration, cue.volume ?? 1
      );
    });
    const locationCue = payload.cues.filter((cue) => cueRole(cue) === "background").at(-1);
    if (locationCue) updateSoundLocation({
      name: locationCue.event.traits?.place || "",
      latitude: locationCue.event.latitude,
      longitude: locationCue.event.longitude,
    });
    if (payload.cues.some((cue) => cue.history_updated !== false)) await updateEvents();
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
    renderMapHistory(events);
    byId("eventList").innerHTML = events.length ? events.map((event) => {
      const summary = eventSummary(event);
      const place = event.traits.place || `${event.latitude.toFixed(2)}, ${event.longitude.toFixed(2)}`;
      const instruments = (event.instruments || [event.instrument]).map(instrumentLabel).join(" + ");
      const backgroundForecast = ["ocean_swell", "storm_potential"].includes(event.kind);
      const detail = backgroundForecast
        ? `${instruments} · ${summary.detail}`
        : `${summary.detail} · ${instruments}`;
      return `<div class="event"><span class="magnitude">${escapeHtml(summary.badge)}</span><div><strong>${escapeHtml(place)}</strong><small>${escapeHtml(detail)} · ${event.latitude.toFixed(2)}, ${event.longitude.toFixed(2)}</small></div><time>${when(event.timestamp)}</time></div>`;
    }).join("") : '<p class="empty">No events in this history window.</p>';
  } catch (error) {
    message(error.message, true);
  }
}

function instrumentLabel(instrument) {
  if (instrument === "seismic_bells") return "Seismic Bell";
  if (instrument === "lightning_glass") return "Lightning R2D2";
  if (instrument === "ocean_swell") return "Ocean Swells";
  if (instrument === "storm_potential") return "Storm Outlook";
  if (instrument === "none") return "No instrument";
  return String(instrument || "Unassigned").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventSummary(event) {
  const traits = event.traits || {};
  const imperial = byId("displayUnits")?.value === "imperial";
  if (event.kind === "ocean_swell") {
    const heightMeters = Number(traits.swell_height_m ?? traits.wave_height_m ?? 0);
    const height = imperial ? heightMeters * 3.28084 : heightMeters;
    const heightUnit = imperial ? "ft" : "m";
    const period = Number(traits.swell_period_s ?? 0);
    return {badge: `${height.toFixed(1)}${heightUnit}`, detail: `${period.toFixed(1)}s modeled swell`};
  }
  if (event.kind === "tide_turn") {
    const state = String(traits.tide_state || "tide").toUpperCase();
    const levelMeters = Number(traits.sea_level_msl_m ?? 0);
    const level = imperial ? levelMeters * 3.28084 : levelMeters;
    const levelUnit = imperial ? "ft" : "m";
    return {badge: state, detail: `${level.toFixed(2)}${levelUnit} modeled sea level`};
  }
  if (event.kind === "storm_potential") {
    return {badge: "CAPE", detail: `${Number(traits.cape_jkg ?? 0).toFixed(0)} J/kg Storm Outlook forecast`};
  }
  if (event.kind === "lightning_flash") {
    const area = Number(traits.flash_area_km2 ?? 0);
    const detail = area > 0
      ? `${area.toFixed(1)} km² observed flash area`
      : "observed lightning flash";
    return {badge: "FLASH", detail};
  }
  return {
    badge: `M${Number(traits.magnitude || 0).toFixed(1)}`,
    detail: imperial
      ? `${(Number(traits.depth_km || 0) * 0.621371).toFixed(1)} mi deep`
      : `${Number(traits.depth_km || 0).toFixed(1)} km deep`,
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

const appViewButtons = Array.from(document.querySelectorAll("[data-app-view-button]"));
const appViews = Array.from(document.querySelectorAll("[data-app-view]"));
const APP_VIEW_STORAGE_KEY = "gaia-scape-app-view";

function savedAppView() {
  try {
    const name = window.localStorage.getItem(APP_VIEW_STORAGE_KEY);
    return appViews.some((view) => view.dataset.appView === name) ? name : "dashboard";
  } catch (_error) {
    return "dashboard";
  }
}

function saveAppView(name) {
  try {
    window.localStorage.setItem(APP_VIEW_STORAGE_KEY, name);
  } catch (_error) {
    // The view still works when storage is disabled or unavailable.
  }
}

function activateAppView(name, persist = false) {
  const selectedName = appViews.some((view) => view.dataset.appView === name)
    ? name
    : "dashboard";
  appViewButtons.forEach((button) => {
    const active = button.dataset.appViewButton === selectedName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  appViews.forEach((view) => { view.hidden = view.dataset.appView !== selectedName; });
  document.body.dataset.appView = selectedName;
  if (persist) saveAppView(selectedName);
}

appViewButtons.forEach((button) => {
  button.addEventListener("click", () => activateAppView(button.dataset.appViewButton, true));
});
activateAppView(savedAppView());

const worldMap = byId("worldMap");
if (worldMap) {
  renderMapProjection();
  renderMapGrid();
  worldMap.addEventListener("pointermove", (event) => {
    const point = worldMap.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const mapPoint = point.matrixTransform(worldMap.getScreenCTM().inverse());
    const readout = byId("mapCoordinateReadout");
    if (!mapContainsPoint(mapPoint.x, mapPoint.y)) {
      readout.textContent = "Outside mapped coordinates";
      return;
    }
    const coordinates = inverseProjectCoordinates(mapPoint.x, mapPoint.y);
    readout.textContent = `${Math.abs(coordinates.latitude).toFixed(2)}°${coordinates.latitude >= 0 ? "N" : "S"} · ${Math.abs(coordinates.longitude).toFixed(2)}°${coordinates.longitude >= 0 ? "E" : "W"}`;
  });
  worldMap.addEventListener("pointerleave", () => { byId("mapCoordinateReadout").textContent = "Move over the map to inspect coordinates"; });
}

const workspaceTabs = Array.from(document.querySelectorAll("[data-workspace-tab]"));
const workspacePanes = Array.from(document.querySelectorAll("[data-workspace-pane]"));

function activateWorkspacePane(name, focusTab = false) {
  workspaceTabs.forEach((tab) => {
    const active = tab.dataset.workspaceTab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focusTab) tab.focus();
  });
  workspacePanes.forEach((pane) => {
    const active = pane.dataset.workspacePane === name;
    pane.classList.toggle("is-active", active);
    pane.hidden = !active;
  });
}

workspaceTabs.forEach((tab, index) => {
  tab.addEventListener("click", () => activateWorkspacePane(tab.dataset.workspaceTab));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    let next = event.key === "Home" ? 0 : event.key === "End" ? workspaceTabs.length - 1 : index;
    if (event.key === "ArrowLeft") next = (index - 1 + workspaceTabs.length) % workspaceTabs.length;
    if (event.key === "ArrowRight") next = (index + 1) % workspaceTabs.length;
    activateWorkspacePane(workspaceTabs[next].dataset.workspaceTab, true);
  });
});

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
  settingsDialog.querySelectorAll('.volume-control input[type="range"]').forEach((slider) => {
    const output = slider.parentElement.querySelector("output");
    const updateVolumeLabel = () => { output.textContent = `${slider.value}%`; };
    slider.addEventListener("input", updateVolumeLabel);
    updateVolumeLabel();
  });
  const lightningSampleSliders = Array.from(
    settingsDialog.querySelectorAll("[data-lightning-sample-rate]")
  );
  const syncLightningSampleRate = (value) => {
    lightningSampleSliders.forEach((slider) => {
      slider.value = value;
      slider.parentElement.querySelector("output").textContent = value;
    });
  };
  lightningSampleSliders.forEach((slider) => {
    slider.addEventListener("input", () => syncLightningSampleRate(slider.value));
  });
  ["event1Instrument", "event2Instrument", "event3Instrument"].forEach((selectId) => {
    const select = byId(selectId);
    const control = select.parentElement.querySelector("[data-lightning-sample-control]");
    const updateSampleRateVisibility = () => {
      control.hidden = select.value !== "lightning_glass";
    };
    select.addEventListener("change", updateSampleRateVisibility);
    updateSampleRateVisibility();
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
        const kind = button.dataset.kind === "background"
          ? instrument
          : (instrument === "tidal_bell"
            ? "tide_turn"
            : (instrument === "lightning_glass" ? "lightning_flash" : "earthquake"));
        const payload = await request("/api/instruments/preview", {
          method: "POST",
          body: JSON.stringify({
            kind,
            instrument,
            volume: Number(byId(button.dataset.volume).value) / 100,
          }),
        });
        status.textContent = "Previewed " + instrumentLabel(payload.instrument) + ".";
        await Promise.all([updateStatus(), updateEvents()]);
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
      } finally {
        updatePreviewState();
      }
    });
  });
  byId("backgroundInstrument").addEventListener("change", (event) => {
    updateBackgroundSoundsTitle(event.target.value);
  });
  updateBackgroundSoundsTitle(byId("backgroundInstrument").value);
  byId("displayUnits").addEventListener("change", updateEvents);
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
            ...(byId("sourceGlm").checked ? ["noaa_glm"] : []),
          ],
          instrument_slots: {
            event_1: byId("event1Instrument").value,
            event_2: byId("event2Instrument").value,
            event_3: byId("event3Instrument").value,
            background: byId("backgroundInstrument").value,
          },
          instrument_volumes: {
            event_1: Number(byId("event1Volume").value) / 100,
            event_2: Number(byId("event2Volume").value) / 100,
            event_3: Number(byId("event3Volume").value) / 100,
            background: Number(byId("backgroundVolume").value) / 100,
          },
          lightning_sample_rate: Number(lightningSampleSliders[0].value),
          units: byId("displayUnits").value,
        }),
      });
      status.textContent = "Settings saved.";
      await updateEvents();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  });
}

Promise.all([updateStatus(), updateEvents(), updateEmittedCues()]);
setInterval(updateStatus, 3000);
