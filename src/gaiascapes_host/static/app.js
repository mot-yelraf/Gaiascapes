const byId = (id) => document.getElementById(id);
let observedCueSequence = null;
let cuePollInFlight = false;
let cuePollController = null;
let wakeRecoveryInFlight = false;
let observedHistorySignature = null;
const observedRecoveryTransitions = new Map();
const LIGHTNING_INTENSITY_HOLD_MS = 3000;
let displayedLightningEvent = null;
let displayedLightningUnits = null;
let pendingLightningEvent = null;
let lightningIntensityTimer = null;
let lastLightningIntensityUpdate = 0;
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const MARINE_BACKGROUNDS = ["whale_song", "dolphin_calls"];
const MAMMAL_BACKGROUNDS = {feline_calls: "Feline Calls", canine_calls: "Canine Calls", elephant_calls: "Elephants", primate_calls: "Primates"};
const RECORDED_BACKGROUNDS = ["birdsong", "frog_calls", ...MARINE_BACKGROUNDS, ...Object.keys(MAMMAL_BACKGROUNDS)];
let deviceListening = false;
let deviceMuted = false;
let listeningAttempt = 0;
const localRecordingPlayback = document.body?.dataset.localPlayback !== "false";
let lastPlayedRecordingSequence = null;
let recordingLoadController = null;
let recordingKind = null;
let recordingPlaybackGeneration = 0;
let recordingAudio = null;
let pendingRecordingAudio = null;
let recordingFadeTimer = null;
let recordingPreviewTimer = null;
let recordingPreviewUntil = 0;
let recordingWatchdog = null;
const activeRecordingAudio = new Set();

function setRecordingFade(audio, fraction) {
  audio.recordingFade = fraction;
  // A squared taper gives the lower slider range useful background levels.
  audio.recordingOutputGain = audio.recordingVolume ** 2 * 0.75 * fraction;
  audio.setRecordingOutputGain?.(audio.recordingOutputGain);
}

function applyRecordingVolume(volume) {
  const level = Number(volume);
  if (!Number.isFinite(level)) return;
  const players = new Set(activeRecordingAudio);
  if (pendingRecordingAudio) players.add(pendingRecordingAudio);
  players.forEach((audio) => {
    audio.recordingVolume = Math.max(0, Math.min(1, level));
    setRecordingFade(audio, audio.recordingFade);
  });
}

function updateRecordingCountdown() {
  document.querySelectorAll(".recording-countdown").forEach((countdown) => {
    const audio = recordingAudio;
    const visible = audio?.fullRecording && !audio.ended
      && audio.recordingMediaUrl === countdown.dataset.mediaUrl
      && Number.isFinite(audio.duration) && audio.duration > 0;
    countdown.hidden = !visible;
    if (!visible) {
      countdown.textContent = "";
      return;
    }
    const remaining = Math.max(0, Math.ceil(audio.duration - audio.currentTime));
    const time = `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`;
    countdown.textContent = `−${time}`;
    countdown.setAttribute("aria-label", `${time} remaining`);
    countdown.title = `${time} remaining`;
  });
}

async function recordingRequest(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    return await request(path, {
      method: "POST", body: JSON.stringify(body), signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

async function advanceRecording(sequence, reason = "") {
  return recordingRequest("/api/recordings/advance", reason ? {sequence, reason} : {sequence});
}

function recoverRecording(sequence, generation, reason) {
  if (!localRecordingPlayback || !sequence || generation !== recordingPlaybackGeneration) return;
  advanceRecording(sequence, reason).catch(error => {
    if (generation !== recordingPlaybackGeneration) return;
    message(`Unable to advance recording: ${error.message}; retrying.`, true);
    setTimeout(() => recoverRecording(sequence, generation, reason), 1000);
  });
}

function clearRecordingWatchdog() {
  if (recordingWatchdog !== null) clearInterval(recordingWatchdog);
  recordingWatchdog = null;
}

function stopRecordingPlayback(fadeMilliseconds = 700) {
  clearRecordingWatchdog();
  recordingLoadController?.abort();
  recordingPlaybackGeneration += 1;
  recordingKind = null;
  if (!globalThis.gaiascapesControls?.previewEvent) globalThis.animalWikipedia?.update(null);
  globalThis.recordingAnnouncements?.stop();
  if (recordingFadeTimer) clearInterval(recordingFadeTimer);
  if (recordingPreviewTimer) clearTimeout(recordingPreviewTimer);
  recordingFadeTimer = null;
  recordingPreviewTimer = null;
  recordingPreviewUntil = 0;
  const players = Array.from(activeRecordingAudio);
  recordingAudio = null;
  if (!players.length) return;
  const initialFades = players.map((audio) => audio.recordingFade);
  const startedAt = performance.now();
  const timer = setInterval(() => {
    const progress = Math.min(1, (performance.now() - startedAt) / fadeMilliseconds);
    players.forEach((audio, index) => setRecordingFade(audio, initialFades[index] * (1 - progress)));
    if (progress >= 1) {
      clearInterval(timer);
      players.forEach((audio) => {
        audio.pause();
        audio.releaseNormalization?.();
        audio.removeAttribute("src");
        activeRecordingAudio.delete(audio);
      });
    }
  }, 50);
}

async function playRecordingCue(cue) {
  if (globalThis.gaiascapesControls?.previewEvent) return;
  const mediaUrl = cue.event?.traits?.media_url;
  if (!mediaUrl) {
    if (cue.recording_rotation) recoverRecording(cue.sequence, recordingPlaybackGeneration, "missing_media");
    return;
  }
  clearRecordingWatchdog();
  recordingLoadController?.abort();
  const controller = new AbortController();
  recordingLoadController = controller;
  const generation = ++recordingPlaybackGeneration;
  recordingKind = cue.event.kind;
  globalThis.recordingAnnouncements?.stop();
  const cueDuration = Number(cue.duration ?? 0);
  // Protect a preview from status refreshes while the media is still loading.
  recordingPreviewUntil = cueDuration > 0 && cueDuration <= 10
    ? Infinity : 0;
  let previous = recordingAudio;
  // Play the buffer already decoded for normalization on desktop as well.
  // A second media-element load can stall independently of that successful load.
  const next = recordingNormalizer.createPlayer();
  if (deviceListening && cue.emitted_at) {
    next.startOffset = Math.max(0, Date.now() / 1000 - cue.emitted_at);
  }
  lastPlayedRecordingSequence = cue.sequence;
  pendingRecordingAudio = next;
  next.recordingVolume = Math.max(0, Math.min(1, Number(cue.volume ?? 1)));
  setRecordingFade(next, 0);
  next.recordingMediaUrl = mediaUrl;
  next.fullRecording = !(cueDuration > 0 && cueDuration <= 10);
  next.rotationSequence = cue.recording_rotation ? cue.sequence : previous?.rotationSequence;
  // Play once per location visit; the next rotation selects the next recording.
  next.loop = false;
  next.preload = "auto";
  next.volume = 0;
  let rejectLoad;
  const cancelled = new Promise((_, reject) => { rejectLoad = reject; });
  const onAbort = () => rejectLoad(controller.signal.reason);
  controller.signal.addEventListener("abort", onAbort, {once: true});
  const loadTimeout = setTimeout(() => {
    controller.abort(new Error("Recording loading timed out"));
  }, 30000);
  try {
    await Promise.race([cancelled, (async () => {
      await recordingNormalizer.resume();
      controller.signal.throwIfAborted();
      await recordingNormalizer.prepare(next, mediaUrl, controller.signal);
      controller.signal.throwIfAborted();
      if (globalThis.recordingAnnouncements?.enabled()) {
        // End outgoing animal audio before speaking; keep the incoming buffer silent.
        if (recordingFadeTimer) clearInterval(recordingFadeTimer);
        if (recordingPreviewTimer) clearTimeout(recordingPreviewTimer);
        recordingFadeTimer = null;
        recordingPreviewTimer = null;
        for (const audio of activeRecordingAudio) {
          audio.pause();
          audio.releaseNormalization?.();
          audio.removeAttribute("src");
        }
        activeRecordingAudio.clear();
        previous = null;
        recordingAudio = null;
        next.startOffset = 0;
        globalThis.animalWikipedia?.update(cue.event);
        // Speech has its own deadline; the media-loading deadline ends here.
        clearTimeout(loadTimeout);
        await globalThis.recordingAnnouncements.play(cue);
        controller.signal.throwIfAborted();
      }
      await next.play();
      if (controller.signal.aborted) next.pause();
      controller.signal.throwIfAborted();
    })()]);
  } catch (error) {
    next.pause();
    next.releaseNormalization?.();
    next.removeAttribute("src");
    if (generation !== recordingPlaybackGeneration) return;
    recordingPreviewUntil = 0;
    if (error.recordingWake) {
      lastPlayedRecordingSequence = null;
      return;
    }
    console.warn("Unable to play normalized recording", error);
    const recovery = next.rotationSequence && localRecordingPlayback
      ? "Advancing to the next recording." : "Select Start or Preview to retry.";
    message(`Unable to play recording: ${error.message}. ${recovery}`, true);
    recoverRecording(next.rotationSequence, generation, error.recordingFailure || "load_failed");
    return;
  } finally {
    clearTimeout(loadTimeout);
    controller.signal.removeEventListener("abort", onAbort);
    if (pendingRecordingAudio === next) pendingRecordingAudio = null;
  }
  if (generation !== recordingPlaybackGeneration) {
    next.pause();
    next.releaseNormalization?.();
    next.removeAttribute("src");
    return;
  }
  recordingAudio = next;
  globalThis.animalWikipedia?.update(cue.event);
  next.addEventListener("ended", () => {
    if (recordingAudio === next) {
      globalThis.animalWikipedia?.update(null);
      globalThis.recordingAnnouncements?.stop();
    }
  }, {once: true});
  activeRecordingAudio.add(next);
  if (byId("mapPulseLayer")) {
    animateMapEvent(cue.event, cue.instrument, cueRole(cue), cueDuration, next);
  }
  if (cue.recording_rotation) {
    let advancing = false;
    let reporting = false;
    let lastPosition = Number(next.currentTime) || 0;
    let lastProgressAt = performance.now();
    let recoveredStall = false;
    const finish = (reason = "") => {
      if (advancing || generation !== recordingPlaybackGeneration) return;
      advancing = true;
      clearRecordingWatchdog();
      if (reason) {
        next.pause();
        next.releaseNormalization?.();
        next.removeAttribute("src");
        activeRecordingAudio.delete(next);
        if (recordingAudio === next) recordingAudio = null;
        message(`Recording ${reason}; advancing to the next recording.`, true);
      }
      recoverRecording(cue.sequence, generation, reason);
    };
    const advanceAtEnd = () => {
      const transition = Math.min(3, next.duration * 0.1);
      if (next.ended || (Number.isFinite(next.duration)
          && next.duration - next.currentTime <= transition)) finish();
    };
    const checkProgress = async () => {
      if (advancing || generation !== recordingPlaybackGeneration) return;
      if (wakeRecoveryInFlight) {
        lastProgressAt = performance.now();
        return;
      }
      advanceAtEnd();
      if (advancing) return;
      const position = Number(next.currentTime) || 0;
      if (position > lastPosition) {
        lastPosition = position;
        lastProgressAt = performance.now();
        recoveredStall = false;
      } else if (performance.now() - lastProgressAt >= 30000) {
        if (!recoveredStall) {
          recoveredStall = true;
          lastProgressAt = performance.now();
          recoverAfterWake();
          return;
        }
        finish("stalled");
        return;
      }
      if (!localRecordingPlayback || reporting) return;
      reporting = true;
      try {
        await recordingRequest("/api/recordings/progress", {sequence: cue.sequence, position});
      } catch (error) {
        // Retry on the next tick. The server also expires abandoned recordings.
        console.warn("Unable to report recording progress", error);
      } finally {
        reporting = false;
      }
    };
    next.addEventListener("timeupdate", advanceAtEnd);
    next.addEventListener("ended", advanceAtEnd);
    next.addEventListener("error", () => finish(
      next.error?.code === 3 || next.error?.code === 4 ? "decode_failed" : "playback_failed"
    ));
    recordingWatchdog = setInterval(checkProgress, 10000);
    checkProgress();
  }
  if (recordingPreviewTimer) clearTimeout(recordingPreviewTimer);
  if (cueDuration > 0 && cueDuration <= 10) {
    recordingPreviewUntil = Date.now() + (cueDuration * 1000);
    recordingPreviewTimer = setTimeout(() => {
      stopRecordingPlayback();
      if (previous?.rotationSequence && localRecordingPlayback) {
        advanceRecording(previous.rotationSequence).catch(error => message(error.message, true));
      }
    }, cueDuration * 1000);
  } else {
    recordingPreviewTimer = null;
    recordingPreviewUntil = 0;
  }
  if (recordingFadeTimer) clearInterval(recordingFadeTimer);
  const startedAt = performance.now();
  const fadeMilliseconds = Number.isFinite(next.duration)
    ? Math.max(50, Math.min(3000, next.duration * 100)) : 3000;
  const previousFadeMilliseconds = cue.recording_rotation && previous && Number.isFinite(previous.duration)
    ? Math.max(50, (previous.duration - previous.currentTime) * 1000) : fadeMilliseconds;
  const previousFade = previous?.recordingFade || 0;
  recordingFadeTimer = setInterval(() => {
    const progress = Math.min(1, (performance.now() - startedAt) / fadeMilliseconds);
    setRecordingFade(next, progress);
    const previousProgress = Math.min(1, (performance.now() - startedAt) / previousFadeMilliseconds);
    if (previous) setRecordingFade(previous, previousFade * (1 - previousProgress));
    if (progress >= 1 && (!previous || previousProgress >= 1)) {
      clearInterval(recordingFadeTimer);
      recordingFadeTimer = null;
      if (previous) {
        previous.pause();
        previous.releaseNormalization?.();
        previous.removeAttribute("src");
        activeRecordingAudio.delete(previous);
      }
    }
  }, 50);
}

let mapProjection = byId("mapProjection")?.value || "robinson";

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
  if (mapProjection === "eckert_iv") {
    // Solve theta + sin(theta) * (cos(theta) + 2) = (2 + pi/2) * sin(latitude).
    // Bisection remains stable at the poles, where the derivative vanishes.
    const target = (2 + Math.PI / 2) * Math.sin(safeLatitude * Math.PI / 180);
    let lower = -Math.PI / 2;
    let upper = Math.PI / 2;
    for (let step = 0; step < 48; step += 1) {
      const theta = (lower + upper) / 2;
      if (theta + Math.sin(theta) * (Math.cos(theta) + 2) < target) lower = theta;
      else upper = theta;
    }
    const theta = Math.abs(safeLatitude) === 90 ? Math.sign(safeLatitude) * Math.PI / 2 : (lower + upper) / 2;
    return {
      x: 512 + 443 * (safeLongitude / 180) * (1 + Math.cos(theta)) / 2,
      y: 512 - 221.5 * Math.sin(theta),
    };
  }
  const xScale = interpolateRobinson(ROBINSON_X, safeLatitude);
  const yScale = interpolateRobinson(ROBINSON_Y, safeLatitude);
  return {
    x: 512 + (443 * (safeLongitude / 180) * xScale),
    y: 512 - (Math.sign(safeLatitude) * 290 * yScale),
  };
}

function inverseProjectCoordinates(x, y) {
  if (mapProjection === "eckert_iv") {
    const sine = Math.max(-1, Math.min(1, (512 - y) / 221.5));
    const theta = Math.asin(sine);
    const latitudeSine = (theta + sine * (Math.cos(theta) + 2)) / (2 + Math.PI / 2);
    return {
      latitude: Math.asin(Math.max(-1, Math.min(1, latitudeSine))) * 180 / Math.PI,
      longitude: ((x - 512) / (443 * (1 + Math.cos(theta)) / 2)) * 180,
    };
  }
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
  globalThis.animalWikipedia?.refreshPointer();
  const boundary = mapProjectionBoundary();
  ["mapGlobeClipPath", "mapGlowPath", "mapOceanPath", "forecastMapClipPath", "forecastMapOceanPath"].forEach((id) => {
    byId(id)?.setAttribute("d", boundary);
  });
}

function mapContainsPoint(x, y) {
  const normalizedY = (512 - Number(y)) / (mapProjection === "eckert_iv" ? 221.5 : 290);
  if (Math.abs(normalizedY) > 1) return false;
  const latitude = inverseProjectCoordinates(512, y).latitude;
  const halfWidth = projectCoordinates(180, latitude).x - 512;
  return Math.abs(Number(x) - 512) <= halfWidth;
}

function renderMapGrid() {
  const layer = byId("mapGridLayer");
  const labels = byId("mapCoordinateLabels");
  if (!layer || !labels) return;
  layer.replaceChildren();
  labels.replaceChildren();
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
      const position = projectCoordinates(longitude, -90);
      const label = createSvgElement("text", {x: position.x, y: position.y + 24, class: "map-coordinate-label", "text-anchor": "middle"});
      label.textContent = longitude === 0 ? "0°" : `${Math.abs(longitude)}°${longitude > 0 ? "E" : "W"}`;
      labels.append(label);
    }
  }
}

function mapMarkerTitle(event) {
  const place = displayPlace(event.traits?.place || event.kind);
  const magnitude = Number(event.traits?.magnitude);
  const magnitudeText = event.kind === "earthquake" && Number.isFinite(magnitude)
    ? ` · M${magnitude.toFixed(1)}`
    : "";
  const sourceText = event.kind === "lightning_flash"
    ? ` · ${lightningSourceLabel(event)}`
    : "";
  return `${place}${magnitudeText}${sourceText} · ${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)}`;
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

function updateMapSystemLocation(location) {
  const coordinates = byId("soundLocationCoordinates");
  if (coordinates) {
    const valid = location?.latitude != null && location?.longitude != null
      && Number.isFinite(Number(location.latitude)) && Number.isFinite(Number(location.longitude));
    coordinates.hidden = !valid;
    coordinates.textContent = valid
      ? `My location ${Number(location.latitude).toFixed(4)}, ${Number(location.longitude).toFixed(4)}`
      : "";
  }
  const layer = byId("mapSystemLocationLayer");
  if (!layer) return;
  layer.replaceChildren();
  const latitude = Number(location?.latitude);
  const longitude = Number(location?.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  const position = projectCoordinates(longitude, latitude);
  const group = createSvgElement("g", {class: "map-system-location"});
  const title = createSvgElement("title");
  title.textContent = `Approximate system location: ${location.name || `${latitude.toFixed(2)}, ${longitude.toFixed(2)}`}`;
  const marker = createSvgElement("circle", {
    cx: position.x,
    cy: position.y,
    r: 4.5,
    class: "map-system-location-marker",
  });
  group.append(title, marker);
  layer.append(group);
}

async function updateSystemLocation() {
  try {
    const payload = await request("/api/system-location");
    updateMapSystemLocation(payload.location);
    window.dispatchEvent(new CustomEvent("systemlocationchange", {detail: payload}));
  } catch (error) {
    updateMapSystemLocation(null);
  }
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

function animateMapEvent(event, instrument, role, animationDuration, audio = null) {
  const layer = byId("mapPulseLayer");
  if (!layer) return;
  const colors = eventColors(event, instrument);
  const position = projectCoordinates(event.longitude, event.latitude);
  const provider = String(event?.provider || "unknown").replace(/[^a-z0-9_-]/gi, "-");
  const group = createSvgElement("g", {class: `map-cue map-cue--${role} map-cue--provider-${provider}`});
  const pulse = createSvgElement("circle", {cx: position.x, cy: position.y, r: role === "background" ? 10 : 7, class: "map-cue-pulse", stroke: colors.primary});
  const core = createSvgElement("circle", {cx: position.x, cy: position.y, r: role === "background" ? 5 : 4, class: "map-cue-core", fill: colors.primary});
  const title = createSvgElement("title");
  title.textContent = mapMarkerTitle(event);
  pulse.style.setProperty("--map-pulse-duration", `${animationDuration}s`);
  pulse.style.setProperty("--map-pulse-scale", role === "background" ? "3.1" : "2.8");
  group.append(title, pulse, core);
  layer.append(group);
  if (role === "background") updateMapBackgroundLocation({name: event.traits?.place || "", latitude: event.latitude, longitude: event.longitude}, colors.primary);
  if (audio) {
    pulse.style.animationPlayState = "paused";
    const syncPlayback = () => {
      if (!activeRecordingAudio.has(audio) || audio.ended) {
        group.remove();
        return;
      }
      const duration = audio.fullRecording ? audio.duration : Math.min(audio.duration, animationDuration);
      const knownDuration = Number.isFinite(duration) && duration > 0;
      pulse.style.visibility = knownDuration ? "" : "hidden";
      if (knownDuration) {
        pulse.style.setProperty("--map-pulse-duration", `${duration}s`);
        pulse.style.animationDelay = `-${Math.min(audio.currentTime, duration)}s`;
      }
      requestAnimationFrame(syncPlayback);
    };
    syncPlayback();
  } else {
    setTimeout(() => group.remove(), (animationDuration * 1000) + 400);
  }
}

function applyLiveMode(mode) {
  const continuous = mode === "continuous";
  document.querySelectorAll(".capture-only").forEach((element) => { element.hidden = continuous; });
  document.querySelectorAll(".continuous-only").forEach((element) => { element.hidden = !continuous; });
  byId("startButton").textContent = "Start";
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const externalSignal = options.signal;
  const abort = () => controller.abort(externalSignal.reason);
  if (externalSignal?.aborted) abort();
  else externalSignal?.addEventListener("abort", abort, {once: true});
  const timeout = setTimeout(() => controller.abort(new Error("Request timed out; please retry.")),
    path.startsWith("/api/cues") ? 35000 : 20000);
  try {
    const response = await fetch(path, {
      headers: {"Content-Type": "application/json"}, ...options, signal: controller.signal,
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error(response.ok
        ? "The server returned an invalid response. Please try again."
        : `The server could not complete the request (HTTP ${response.status}). Please try again.`);
    }
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    return payload;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abort);
  }
}

function when(timestamp) {
  return timestamp
    ? new Date(timestamp * 1000).toLocaleString().replace(/,\s*/, " ")
    : "Not yet";
}

function usesImperialUnits() {
  return byId("displayUnits")?.value === "imperial";
}

function displayPlace(place) {
  const text = String(place || "");
  if (!usesImperialUnits()) return text;
  return text.replace(/(\d+(?:\.\d+)?)\s*km\b/gi, (_match, distance) => {
    const miles = Number(distance) * 0.621371;
    return `${miles.toFixed(1)} mi`;
  });
}

function message(text, error = false, source = "") {
  const banner = byId("message");
  banner.textContent = text;
  banner.classList.toggle("error", error);
  banner.dataset.messageSource = source;
}

function syncRecoveryToasts(health = {}) {
  const stack = byId("recoveryToasts");
  if (!stack) return;
  Object.values(health).forEach((source) => {
    const existing = stack.querySelector(`[data-recovery-source="${source.source}"]`);
    if (!source.enabled || !source.notify) {
      existing?.remove();
      observedRecoveryTransitions.set(source.source, source.transition);
      return;
    }
    const previousTransition = observedRecoveryTransitions.get(source.source);
    if (previousTransition === source.transition) {
      existing?.querySelector("span")?.replaceChildren(source.message);
      return;
    }
    observedRecoveryTransitions.set(source.source, source.transition);
    existing?.remove();
    const toast = document.createElement("button");
    toast.type = "button";
    toast.className = `recovery-toast recovery-toast--${source.severity}`;
    toast.dataset.recoverySource = source.source;
    toast.setAttribute("aria-label", `${source.message} Click to dismiss.`);
    const title = document.createElement("strong");
    title.textContent = source.state === "online"
      ? "Recovered"
      : source.state.charAt(0).toUpperCase() + source.state.slice(1);
    const detail = document.createElement("span");
    detail.textContent = source.message;
    const dismiss = document.createElement("small");
    dismiss.textContent = "Click to dismiss";
    toast.append(title, detail, dismiss);
    const timer = setTimeout(() => toast.remove(), 5000);
    toast.addEventListener("click", () => {
      clearTimeout(timer);
      toast.remove();
    }, {once: true});
    stack.append(toast);
  });
}

function updateStatusField(field, text, title = null) {
  document.querySelectorAll(`[data-status-field="${field}"]`).forEach((element) => {
    element.textContent = text;
    if (title !== null) element.title = title;
  });
}

function updateSoundLocation(location) {
  const locationText = location
    ? (location.name || `${Number(location.latitude).toFixed(2)}, ${Number(location.longitude).toFixed(2)}`)
    : "—";
  updateStatusField(
    "background-location", locationText, locationText === "—" ? "" : locationText
  );
  updateMapBackgroundLocation(location);
}

function stormMeasurements(traits) {
  const imperial = byId("displayUnits")?.value === "imperial";
  const capeJkg = Number(traits.cape_jkg ?? 0);
  const showersMm = Number(traits.showers_mm ?? 0);
  const gustKmh = Number(traits.wind_gust_kmh ?? 0);
  if (imperial) {
    return {
      cape: capeJkg * 10.7639,
      capeUnit: "ft²/s²",
      showers: showersMm / 25.4,
      showersUnit: "in",
      gust: gustKmh * 0.621371,
      gustUnit: "mph",
    };
  }
  return {
    cape: capeJkg,
    capeUnit: "J/kg",
    showers: showersMm,
    showersUnit: "mm",
    gust: gustKmh,
    gustUnit: "km/h",
  };
}

function stormCapeSeverity(capeJkg) {
  if (capeJkg >= 2500) return {label: "Strong", className: "storm-cape--strong"};
  if (capeJkg >= 1000) return {label: "Substantial", className: "storm-cape--substantial"};
  if (capeJkg >= 500) return {label: "Modest", className: "storm-cape--modest"};
  return {label: "Weak", className: "storm-cape--weak"};
}

function oceanSwellMeasurements(traits) {
  const imperial = byId("displayUnits")?.value === "imperial";
  const heightMeters = Number(traits.swell_height_m ?? traits.wave_height_m ?? 0);
  return {
    heightMeters,
    height: imperial ? heightMeters * 3.28084 : heightMeters,
    heightUnit: imperial ? "ft" : "m",
    period: Number(traits.swell_period_s ?? 0),
    direction: Number(traits.swell_direction_deg ?? 0),
  };
}

function oceanSwellSeverity(heightMeters) {
  if (heightMeters >= 4.6) return {label: "Extreme", className: "swell-height--extreme"};
  if (heightMeters >= 3.0) return {label: "Very Large", className: "swell-height--very-large"};
  if (heightMeters >= 1.8) return {label: "Large", className: "swell-height--large"};
  if (heightMeters >= 0.9) return {label: "Moderate", className: "swell-height--moderate"};
  if (heightMeters >= 0.3) return {label: "Small", className: "swell-height--small"};
  return {label: "Minimal", className: "swell-height--minimal"};
}

function backgroundCharacteristics(event) {
  if (!event) return "Awaiting background";
  const traits = event.traits || {};
  if (RECORDED_BACKGROUNDS.includes(event.kind)) {
    return `${traits.title || "Animal recording"} · ${traits.creator || "Unknown contributor"}`;
  }
  if (event.kind === "ocean_swell") {
    const measurements = oceanSwellMeasurements(traits);
    const severity = oceanSwellSeverity(measurements.heightMeters);
    return `${severity.label} · Swell ${measurements.height.toFixed(1)} ${measurements.heightUnit} · Period ${measurements.period.toFixed(1)} s · Direction ${measurements.direction.toFixed(0)}°`;
  }
  if (event.kind === "storm_potential") {
    const measurements = stormMeasurements(traits);
    const severity = stormCapeSeverity(Number(traits.cape_jkg ?? 0));
    const cape = measurements.cape.toLocaleString(undefined, {maximumFractionDigits: 0});
    return `${severity.label} · CAPE ${cape} ${measurements.capeUnit} · Wind gusts ${measurements.gust.toFixed(0)} ${measurements.gustUnit}`;
  }
  return "Awaiting forecast";
}

function updateBackgroundCharacteristics(event, fallbackText = null) {
  const severityClasses = [
    "storm-cape--weak", "storm-cape--modest",
    "storm-cape--substantial", "storm-cape--strong",
    "swell-height--minimal", "swell-height--small", "swell-height--moderate",
    "swell-height--large", "swell-height--very-large", "swell-height--extreme",
  ];
  document.querySelectorAll('[data-status-field="background-characteristics"]').forEach((element) => {
    element.replaceChildren();
    element.classList.remove("forecast-characteristics", ...severityClasses);
    if (event?.kind === "ocean_swell") {
      const measurements = oceanSwellMeasurements(event.traits || {});
      const severity = oceanSwellSeverity(measurements.heightMeters);
      const heightPill = document.createElement("span");
      heightPill.classList.add("swell-height-pill", severity.className);
      heightPill.textContent = `${severity.label} · Swell ${measurements.height.toFixed(1)} ${measurements.heightUnit}`;
      const details = document.createElement("span");
      details.className = "forecast-characteristics-details";
      details.textContent = `Period ${measurements.period.toFixed(1)} s · Direction ${measurements.direction.toFixed(0)}°`;
      element.classList.add("forecast-characteristics");
      element.append(heightPill, details);
      element.setAttribute("aria-label", backgroundCharacteristics(event));
      return;
    }
    if (event?.kind === "storm_potential") {
      const traits = event.traits || {};
      const measurements = stormMeasurements(traits);
      const severity = stormCapeSeverity(Number(traits.cape_jkg ?? 0));
      const cape = measurements.cape.toLocaleString(undefined, {maximumFractionDigits: 0});
      const capePill = document.createElement("span");
      capePill.classList.add("storm-cape-pill", severity.className);
      capePill.textContent = `${severity.label} · CAPE ${cape} ${measurements.capeUnit}`;
      const details = document.createElement("span");
      details.className = "forecast-characteristics-details";
      details.textContent = `Wind gusts ${measurements.gust.toFixed(0)} ${measurements.gustUnit}`;
      element.classList.add("forecast-characteristics");
      element.append(capePill, details);
      element.setAttribute("aria-label", backgroundCharacteristics(event));
      return;
    }
    if (RECORDED_BACKGROUNDS.includes(event?.kind)) {
      const traits = event.traits || {};
      const source = document.createElement("a");
      source.href = traits.source_url || (event.provider === "xeno_canto" ? "https://xeno-canto.org/" : "https://commons.wikimedia.org/");
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      source.textContent = traits.title || "Animal recording";
      const description = document.createElement("span");
      description.className = "recording-description";
      const countdown = document.createElement("span");
      countdown.className = "recording-countdown";
      countdown.dataset.mediaUrl = traits.media_url || "";
      countdown.hidden = true;
      description.append(source, countdown);
      const credit = document.createElement("span");
      credit.className = "forecast-characteristics-details recording-attribution";
      const creator = traits.creator || "Unknown contributor";
      credit.textContent = event.provider === "noaa_sanctsound"
        ? creator.replace(/ · NOAA\/Navy SanctSound$/, "") : creator;
      const provenance = document.createElement("span");
      provenance.className = "forecast-characteristics-details recording-attribution";
      const sourceName = {
        noaa_sanctsound: "NOAA/Navy SanctSound",
        xeno_canto: "Xeno-canto",
        wikimedia_commons: "Wikimedia Commons",
        figshare: "Figshare",
        zenodo: "Zenodo",
        freesound: "Freesound",
      }[event.provider] || event.provider || "Unknown source";
      provenance.textContent = `${sourceName} · ${traits.license || "License unavailable"}`;
      element.classList.add("forecast-characteristics");
      element.append(description, credit, provenance);
      if (traits.context) {
        const context = document.createElement("span");
        context.className = "forecast-characteristics-details recording-attribution";
        context.textContent = traits.context;
        element.append(context);
      }
      element.setAttribute("aria-label", `${source.textContent}; ${credit.textContent}; ${provenance.textContent}`);
      return;
    }
    element.removeAttribute("aria-label");
    element.textContent = fallbackText ?? backgroundCharacteristics(event);
  });
  updateRecordingCountdown();
}

function updateBackgroundStatus(event, recordingStatuses = {}) {
  const selection = byId("backgroundInstrument")?.value || "none";
  updateBackgroundSoundsTitle(selection);
  if (selection === "none") {
    updateSoundLocation(null);
    updateBackgroundCharacteristics(null, "No background selected");
    return;
  }
  const recordingStatus = recordingStatuses[selection];
  if (recordingStatus?.error || recordingStatus?.state === "loading") {
    updateSoundLocation(null);
    updateBackgroundCharacteristics(null, recordingStatus.error
      || `Looking for ${instrumentLabel(selection)} recordings…`);
    return;
  }
  const activeEvent = event?.kind === selection ? event : null;
  updateSoundLocation(activeEvent ? {
    name: activeEvent.traits?.place || "",
    latitude: activeEvent.latitude,
    longitude: activeEvent.longitude,
  } : null);
  updateBackgroundCharacteristics(activeEvent);
}

function eventKindLabel(kind) {
  const labels = {
    earthquake: "Earthquake",
    tide_turn: "Tide Turn",
    lightning_flash: "Lightning Flash",
    ocean_swell: "Ocean Swell",
    storm_potential: "Storm Outlook",
    birdsong: "Birdsong Atlas",
    frog_calls: "Frog Calls",
    whale_song: "Whale Song",
    dolphin_calls: "Dolphin Calls",
    ...MAMMAL_BACKGROUNDS,
  };
  return labels[kind] || instrumentLabel(kind);
}

function eventStatusText(event) {
  if (!event) return "—";
  const type = eventKindLabel(event.kind);
  if (event.kind === "lightning_flash") return `${type} · ${lightningSourceLabel(event, true)}`;
  if (event.kind !== "earthquake") return type;
  const magnitude = Number(event.traits?.magnitude ?? 0).toFixed(1);
  return `${type} · M${magnitude} · ${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)}`;
}

function lightningSourceLabel(event, compact = false) {
  if (event?.provider === "eumetsat_mtg_li") {
    return compact ? "MTG-LI · 12m delay" : "EUMETSAT MTG-LI · 12-minute delayed playback";
  }
  if (event?.provider === "noaa_glm") {
    return compact ? "GOES GLM · live" : "NOAA GOES GLM · near-live";
  }
  return "Observed lightning";
}

function lightningIntensity(event) {
  const strength = Math.max(0, Math.min(1, Number(event?.strength ?? 0)));
  if (strength >= 0.75) return {label: "Intense", className: "lightning-intensity--intense"};
  if (strength >= 0.5) return {label: "Strong", className: "lightning-intensity--strong"};
  if (strength >= 0.25) return {label: "Moderate", className: "lightning-intensity--moderate"};
  return {label: "Faint", className: "lightning-intensity--faint"};
}

function formatLightningEnergy(energyJoules) {
  const energy = Math.max(0, Number(energyJoules) || 0);
  if (usesImperialUnits()) {
    const footPounds = energy * 0.737562;
    return `${footPounds.toExponential(1)} ft·lbf`;
  }
  if (energy >= 1e-9) return `${(energy * 1e9).toFixed(2)} nJ`;
  if (energy >= 1e-12) return `${(energy * 1e12).toFixed(2)} pJ`;
  if (energy >= 1e-15) return `${(energy * 1e15).toFixed(1)} fJ`;
  return `${energy.toExponential(1)} J`;
}

function formatLightningSignal(event) {
  const traits = event?.traits || {};
  if (event?.provider === "eumetsat_mtg_li") {
    const radiance = Math.max(0, Number(traits.flash_radiance_mw_m2_sr) || 0);
    const value = radiance >= 1000 ? radiance.toExponential(1) : radiance.toFixed(1);
    return `${value} mW·m⁻²·sr⁻¹`;
  }
  return formatLightningEnergy(traits.flash_energy_j);
}

function lightningMeasurements(traits) {
  const areaSquareKilometers = Number(traits.flash_area_km2 ?? 0);
  const durationMilliseconds = Number(traits.flash_duration_ms ?? 0);
  if (usesImperialUnits()) {
    return {
      area: areaSquareKilometers * 0.386102,
      areaUnit: "mi²",
      duration: durationMilliseconds / 1000,
      durationUnit: "s",
    };
  }
  return {
    area: areaSquareKilometers,
    areaUnit: "km²",
    duration: durationMilliseconds,
    durationUnit: "ms",
  };
}

function renderLastEventStatus(event) {
  document.querySelectorAll(".status-card--event").forEach((card) => {
    card.dataset.eventKind = event?.kind || "";
  });
  const text = eventStatusText(event);
  updateStatusField("last-event-type", text, text === "—" ? "" : text);
  const locationAndTime = event
    ? `${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)} @ ${when(event.timestamp)}`
    : "Not yet";
  document.querySelectorAll('[data-status-field="last-event-time"]').forEach((element) => {
    element.replaceChildren();
    element.classList.remove("lightning-characteristics");
    element.removeAttribute("aria-label");
    if (event?.kind !== "lightning_flash") {
      element.textContent = locationAndTime;
      element.title = locationAndTime === "Not yet" ? "" : locationAndTime;
      return;
    }
    const traits = event.traits || {};
    const intensity = lightningIntensity(event);
    const signal = formatLightningSignal(event);
    const pill = document.createElement("span");
    pill.classList.add("lightning-intensity-pill", intensity.className);
    pill.textContent = `${intensity.label} · ${signal}`;
    const observation = document.createElement("span");
    observation.className = "lightning-characteristics-location";
    observation.textContent = locationAndTime;
    element.classList.add("lightning-characteristics");
    element.append(pill, observation);
    element.setAttribute("aria-label", `${intensity.label} lightning, ${lightningSourceLabel(event)}, ${signal}, ${locationAndTime}`);
    element.title = "";
  });
}

function lightningEventKey(event) {
  return `${event?.provider || ""}:${event?.event_id || ""}`;
}

function updateLastEventStatus(event) {
  if (event?.kind !== "lightning_flash") {
    if (lightningIntensityTimer !== null) clearTimeout(lightningIntensityTimer);
    lightningIntensityTimer = null;
    displayedLightningEvent = null;
    displayedLightningUnits = null;
    pendingLightningEvent = null;
    lastLightningIntensityUpdate = 0;
    renderLastEventStatus(event);
    return;
  }
  const selectedUnits = usesImperialUnits() ? "imperial" : "metric";
  if (lightningEventKey(event) === lightningEventKey(displayedLightningEvent)) {
    if (displayedLightningUnits !== selectedUnits) {
      displayedLightningUnits = selectedUnits;
      renderLastEventStatus(event);
    }
    return;
  }
  if (lightningEventKey(event) === lightningEventKey(pendingLightningEvent)) return;
  const now = Date.now();
  if (!displayedLightningEvent || now - lastLightningIntensityUpdate >= LIGHTNING_INTENSITY_HOLD_MS) {
    displayedLightningEvent = event;
    displayedLightningUnits = selectedUnits;
    pendingLightningEvent = null;
    lastLightningIntensityUpdate = now;
    renderLastEventStatus(event);
    return;
  }
  if (!pendingLightningEvent || Number(event.strength ?? 0) > Number(pendingLightningEvent.strength ?? 0)) {
    pendingLightningEvent = event;
  }
  if (lightningIntensityTimer !== null) return;
  const remaining = LIGHTNING_INTENSITY_HOLD_MS - (now - lastLightningIntensityUpdate);
  lightningIntensityTimer = setTimeout(() => {
    lightningIntensityTimer = null;
    if (!pendingLightningEvent) return;
    displayedLightningEvent = pendingLightningEvent;
    displayedLightningUnits = usesImperialUnits() ? "imperial" : "metric";
    pendingLightningEvent = null;
    lastLightningIntensityUpdate = Date.now();
    renderLastEventStatus(displayedLightningEvent);
  }, remaining);
}

function earthquakeSeverity(magnitude) {
  if (magnitude >= 8) return {label: "Great", className: "earthquake-magnitude--great"};
  if (magnitude >= 7) return {label: "Major", className: "earthquake-magnitude--major"};
  if (magnitude >= 6) return {label: "Strong", className: "earthquake-magnitude--strong"};
  if (magnitude >= 5) return {label: "Moderate", className: "earthquake-magnitude--moderate"};
  if (magnitude >= 4) return {label: "Light", className: "earthquake-magnitude--light"};
  if (magnitude >= 2) return {label: "Minor", className: "earthquake-magnitude--minor"};
  return {label: "Micro", className: "earthquake-magnitude--micro"};
}

function updateLastEarthquakeStatus(event) {
  const location = event
    ? (displayPlace(event.traits?.place) || `${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)}`)
    : "—";
  updateStatusField("last-earthquake-location", location, location === "—" ? "" : location);
  document.querySelectorAll('[data-status-field="last-earthquake-detail"]').forEach((element) => {
    element.replaceChildren();
    element.classList.remove("earthquake-characteristics");
    element.removeAttribute("aria-label");
    if (!event) {
      element.textContent = "Not yet";
      element.title = "";
      return;
    }
    const magnitude = Number(event.traits?.magnitude ?? 0);
    const severity = earthquakeSeverity(magnitude);
    const pill = document.createElement("span");
    pill.classList.add("earthquake-magnitude-pill", severity.className);
    pill.textContent = `${severity.label} · M${magnitude.toFixed(1)}`;
    const observation = document.createElement("span");
    observation.className = "earthquake-characteristics-location";
    observation.textContent = `${Number(event.latitude).toFixed(2)}, ${Number(event.longitude).toFixed(2)} @ ${when(event.timestamp)}`;
    element.classList.add("earthquake-characteristics");
    element.append(pill, observation);
    element.setAttribute("aria-label", `${severity.label} earthquake, magnitude ${magnitude.toFixed(1)}, ${observation.textContent}`);
    element.title = "";
  });
}

function backgroundSoundLabel(instrument) {
  if (MAMMAL_BACKGROUNDS[instrument]) return MAMMAL_BACKGROUNDS[instrument];
  if (instrument === "ocean_swell") return "Ocean Swells";
  if (instrument === "storm_potential") return "Storm Outlook";
  if (instrument === "birdsong") return "Birdsong Atlas";
  if (instrument === "frog_calls") return "Frog Calls";
  if (instrument === "whale_song") return "Whale Song";
  if (instrument === "dolphin_calls") return "Dolphin Calls";
  return "Background Sounds";
}

function updateBackgroundSoundsTitle(instrument) {
  updateStatusField("background-title", backgroundSoundLabel(instrument));
}

const EVENT_PALETTES = {
  earthquake: ["#765236", "#93643f", "#ad7749", "#c28b59", "#d0a06d"],
  ocean_swell: ["#214c5a", "#286579", "#327f94", "#489aab", "#6ab5bd"],
  tide_turn: ["#244d68", "#2e6685", "#3c80a0", "#579bb7", "#7bb5ca"],
  lightning_flash: ["#79500a", "#9d6a10", "#c58a1b", "#e5aa2b", "#ffd15a"],
  storm_potential: ["#3b4568", "#4c5782", "#606b9d", "#7882b5", "#969dcc"],
  birdsong: ["#355c37", "#467847", "#5a965a", "#75b873", "#99d493"],
  whale_song: ["#204755", "#326579", "#538f9d", "#85b5bb", "#b9d4cc"],
  dolphin_calls: ["#285360", "#3f7b89", "#64a0aa", "#98c5c5", "#c4ded5"],
  frog_calls: ["#365331", "#537544", "#73964e", "#96b765", "#bed58b"],
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
  return ["ocean_swell", "storm_potential", ...RECORDED_BACKGROUNDS].includes(cue.event?.kind) ? "background" : "event";
}

function animateCapturedEvent(event, instrument = "", role = "event", cueDuration = 3.6, volume = 1) {
  const animationDuration = role === "background"
    ? Math.max(3.6, Number(cueDuration) || 3.6)
    : 3.6;
  if (!RECORDED_BACKGROUNDS.includes(event?.kind) || !event.traits?.media_url) {
    animateMapEvent(event, instrument, role, animationDuration);
  }
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
    const historySignature = `${status.history.event_count}:${status.history.latest_timestamp ?? ""}`;
    const historyChanged = observedHistorySignature !== null && observedHistorySignature !== historySignature;
    observedHistorySignature = historySignature;
    updateBackgroundStatus(status.cues.latest_background_event, status.sources?.recordings);
    updateLastEventStatus(status.cues.latest_event);
    updateLastEarthquakeStatus(status.cues.latest_earthquake_event);
    syncRecoveryToasts({
      ...(status.sources?.recovery ? {all_sources: status.sources.recovery} : {}),
      ...(status.sources?.health || {}),
    });
    const continuous = status.live.mode === "continuous";
    const previewingRecording = Date.now() < recordingPreviewUntil;
    const recordingDisabled = recordingKind && status.sources?.[`${recordingKind}_enabled`] === false;
    if (recordingDisabled || ((!continuous || !status.live.running
        || byId("backgroundInstrument")?.value !== recordingKind) && !previewingRecording)) {
      stopRecordingPlayback();
    }
    byId("liveMode").value = status.live.mode;
    applyLiveMode(status.live.mode);
    const active = continuous ? status.live.running : status.performance.running;
    byId("performanceBadge").textContent = continuous
      ? (status.live.running ? `Continuous · ${status.live.played_count} cues` : "Paused")
      : (status.performance.running ? `Playing ${status.performance.played_count}/${status.performance.cue_count}` : "Capture");
    byId("performanceBadge").classList.toggle("running", active);
    globalThis.gaiascapesControls?.setPlaying(active);
    if (historyChanged) await updateEvents();
  } catch (error) {
    message(error.message, true);
  }
}

async function updateEmittedCues() {
  if (cuePollInFlight || wakeRecoveryInFlight) return;
  cuePollInFlight = true;
  const controller = new AbortController();
  cuePollController = controller;
  let retryDelay = 0;
  try {
    const query = observedCueSequence === null ? "" : `?after=${observedCueSequence}`;
    const payload = await request(`/api/cues${query}`, {signal: controller.signal});
    if (controller.signal.aborted) return;
    const latestRecording = payload.cues.filter(cue => RECORDED_BACKGROUNDS.includes(cue.event?.kind)).at(-1);
    const now = Date.now() / 1000;
    payload.cues.forEach((cue) => {
      if (cue === latestRecording && cue.sequence !== lastPlayedRecordingSequence
          && !deviceMuted && (deviceListening || localRecordingPlayback)) playRecordingCue(cue);
      // Webviews may deliver a backlog after being hidden. Old event pulses
      // should not appear together as if they were happening now.
      if (cue.emitted_at && now - cue.emitted_at > Math.max(3.6, Number(cue.duration) || 0)) return;
      animateCapturedEvent(
        cue.event, cue.instrument, cueRole(cue), cue.duration, cue.volume ?? 1
      );
    });
    const locationCue = payload.cues.filter((cue) => cueRole(cue) === "background").at(-1);
    if (locationCue) updateBackgroundStatus(locationCue.event);
    const eventCue = payload.cues.filter((cue) => cueRole(cue) === "event").at(-1);
    if (eventCue) updateLastEventStatus(eventCue.event);
    const earthquakeCue = payload.cues.filter((cue) => cue.event?.kind === "earthquake").at(-1);
    if (earthquakeCue) updateLastEarthquakeStatus(earthquakeCue.event);
    if (payload.cues.some((cue) => cue.history_updated !== false)) await updateEvents();
    if (!controller.signal.aborted) observedCueSequence = payload.latest_sequence;
  } catch (error) {
    if (!controller.signal.aborted) {
      console.warn("Unable to synchronize emitted cues", error);
      retryDelay = 1000;
    }
  } finally {
    cuePollInFlight = false;
    cuePollController = null;
    setTimeout(updateEmittedCues, retryDelay);
  }
}

async function recoverAfterWake() {
  if (wakeRecoveryInFlight || document.hidden) return;
  wakeRecoveryInFlight = true;
  observedCueSequence = null;
  cuePollController?.abort();
  try {
    if (!deviceMuted && (localRecordingPlayback || deviceListening)) {
      if (pendingRecordingAudio) {
        recordingLoadController?.abort(Object.assign(new Error("Reload recording after wake"), {recordingWake: true}));
      }
      if (!recordingAudio || recordingAudio.ended) lastPlayedRecordingSequence = null;
      const results = await Promise.allSettled([
        recordingNormalizer.recover(),
        deviceListening ? liveAudioPlayer.recover() : Promise.resolve(),
      ]);
      if (!deviceMuted) results.forEach(result => {
        if (result.status === "rejected") message(`Unable to restore audio after wake: ${result.reason.message}`, true);
      });
    }
  } finally {
    wakeRecoveryInFlight = false;
    updateEmittedCues();
    updateStatus();
    updateEvents();
  }
}

async function updateEvents() {
  try {
    const hours = Number(byId("hours").value);
    const payload = await request(`/api/events?hours=${encodeURIComponent(hours)}&limit=100`);
    const events = payload.events;
    renderMapHistory(events);
    byId("eventList").innerHTML = events.length ? events.map((event) => {
      const summary = eventSummary(event);
      const place = displayPlace(event.traits.place) || `${event.latitude.toFixed(2)}, ${event.longitude.toFixed(2)}`;
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
  if (MAMMAL_BACKGROUNDS[instrument]) return MAMMAL_BACKGROUNDS[instrument];
  if (instrument === "tidal_bell") return "Tidal Tone";
  if (instrument === "seismic_bells") return "Seismic Tone";
  if (instrument === "lightning_glass") return "Lightning R2D2";
  if (instrument === "natural_thunder") return "Thunder";
  if (instrument === "test_tone") return "440 Hz Test Tone";
  if (instrument === "ocean_swell") return "Ocean Swells";
  if (instrument === "storm_potential") return "Storm Outlook";
  if (instrument === "none") return "No instrument";
  return String(instrument || "Unassigned").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function eventSummary(event) {
  const traits = event.traits || {};
  if (RECORDED_BACKGROUNDS.includes(event.kind)) {
    return {badge: "Recording", detail: traits.title || instrumentLabel(event.kind)};
  }
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
    const measurements = stormMeasurements(traits);
    const cape = measurements.cape.toLocaleString(undefined, {maximumFractionDigits: 0});
    return {
      badge: "CAPE",
      detail: `${cape} ${measurements.capeUnit} · ${measurements.showers.toFixed(2)} ${measurements.showersUnit} showers · ${measurements.gust.toFixed(0)} ${measurements.gustUnit} gusts`,
    };
  }
  if (event.kind === "lightning_flash") {
    const measurements = lightningMeasurements(traits);
    const detail = measurements.area > 0
      ? `${measurements.area.toFixed(1)} ${measurements.areaUnit} observed flash area`
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

const listenButton = byId("listenButton");
const listenStatus = byId("listenStatus");
const liveAudioPlayer = new LiveAudioPlayer((state, detail) => {
  if (state === "error") {
    muteDevice();
    listenStatus.textContent = detail;
    listenStatus.classList.add("error");
  } else if (state === "reconnecting") {
    listenStatus.textContent = `Recordings available; reconnecting host audio: ${detail}`;
  } else {
    listenStatus.textContent = "Listening on this device";
  }
});

function muteDevice() {
  listeningAttempt += 1;
  deviceListening = false;
  deviceMuted = true;
  liveAudioPlayer.stop();
  // Silence immediately; clean up recording players through their normal path.
  activeRecordingAudio.forEach(audio => audio.setRecordingOutputGain?.(0));
  stopRecordingPlayback(1);
  lastPlayedRecordingSequence = null;
  listenButton.textContent = "Listen on this device";
  listenButton.setAttribute("aria-pressed", "false");
  listenStatus.textContent = "Muted on this device";
}

async function listenOnDevice() {
  const attempt = ++listeningAttempt;
  deviceListening = true;
  deviceMuted = false;
  listenButton.textContent = "Mute this device";
  listenButton.setAttribute("aria-pressed", "true");
  listenStatus.textContent = "Connecting to host audio…";
  listenStatus.classList.remove("error");
  try {
    // Treat explicit listening as media playback, including in iPhone Silent Mode.
    if (navigator.audioSession) navigator.audioSession.type = "playback";
    // Unlock both contexts synchronously within the original tap on iPhone.
    await Promise.all([recordingNormalizer.resume(), liveAudioPlayer.unlock()]);
    if (attempt !== listeningAttempt) return;
    const availability = await request("/api/audio/status");
    if (attempt !== listeningAttempt) return;
    if (availability.enabled) {
      try {
        await liveAudioPlayer.start();
      } catch (error) {
        // Synthesized audio is optional; recordings use their own audio context.
        listenStatus.textContent = `Recordings available; reconnecting host audio: ${error.message}`;
      }
    } else {
      listenStatus.textContent = "Listening to recordings; host synthesized audio is disabled.";
    }
    if (attempt !== listeningAttempt) return;
    const current = await request("/api/cues");
    if (attempt !== listeningAttempt) return;
    const cue = current.cues.filter(cue => RECORDED_BACKGROUNDS.includes(cue.event?.kind)).at(-1);
    if (cue && cue.sequence !== lastPlayedRecordingSequence) await playRecordingCue(cue);
  } catch (error) {
    if (attempt !== listeningAttempt) return;
    muteDevice();
    listenStatus.textContent = error.message;
    listenStatus.classList.add("error");
  }
}

listenButton.addEventListener("click", () => {
  if (deviceListening) muteDevice();
  else listenOnDevice();
});
window.addEventListener("pagehide", () => {
  // A cached page can return on wake/navigation; preserve the user's intent.
  liveAudioPlayer.disconnect();
  stopRecordingPlayback(1);
});
window.addEventListener("pageshow", recoverAfterWake);
window.addEventListener("focus", recoverAfterWake);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) recoverAfterWake();
});
let lastWakeCheck = Date.now();
setInterval(() => {
  const now = Date.now();
  const interrupted = now - lastWakeCheck > 15000;
  lastWakeCheck = now;
  if (interrupted) recoverAfterWake();
}, 5000);

async function startPlayback() {
  if (globalThis.gaiascapesControls) globalThis.gaiascapesControls.previewEvent = null;
  try {
    if (!deviceMuted && (localRecordingPlayback || deviceListening)
        && RECORDED_BACKGROUNDS.includes(byId("backgroundInstrument")?.value)) {
      await recordingNormalizer.resume();
    }
    if (byId("liveMode").value === "continuous") {
      await request("/api/live/start", {method: "POST", body: "{}"});
      message("Continuous environmental sound is running with the selected global background.");
    } else {
      const payload = await request("/api/performance/replay", {
        method: "POST",
        body: JSON.stringify({hours: Number(byId("hours").value), performance_seconds: Number(byId("duration").value)}),
      });
      message(`Started ${payload.cue_count} cues from ${payload.event_count} captured events.`);
    }
    await updateStatus();
    return true;
  } catch (error) {
    message(error.message, true);
    globalThis.gaiascapesControls?.showError(error.message);
    return false;
  }
}
byId("startButton").addEventListener("click", startPlayback);

async function stopPlayback() {
  try {
    const continuous = byId("liveMode").value === "continuous";
    await request(continuous ? "/api/live/stop" : "/api/performance/stop", {method: "POST", body: "{}"});
    stopRecordingPlayback(1);
    message(continuous ? "Continuous environmental sound paused." : "Performance stopped.");
    await updateStatus();
    return true;
  } catch (error) {
    message(error.message, true);
    globalThis.gaiascapesControls?.showError(error.message);
    return false;
  }
}
byId("stopButton").addEventListener("click", stopPlayback);

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
  const configuredView = appViews.some((view) => view.dataset.appView === document.body.dataset.initialAppView)
    ? document.body.dataset.initialAppView
    : "dashboard";
  try {
    const name = window.localStorage.getItem(APP_VIEW_STORAGE_KEY);
    return appViews.some((view) => view.dataset.appView === name) ? name : configuredView;
  } catch (_error) {
    return configuredView;
  }
}

function saveAppView(name) {
  try {
    window.localStorage.setItem(APP_VIEW_STORAGE_KEY, name);
  } catch (_error) {
    // The view still works when storage is disabled or unavailable.
  }
  request("/api/settings/view", {
    method: "PUT",
    body: JSON.stringify({view: name}),
  }).catch((error) => message(`Could not save view preference: ${error.message}`, true));
}

function activateAppView(name, persist = false) {
  globalThis.animalWikipedia?.refreshPointer();
  const selectedName = appViews.some((view) => view.dataset.appView === name)
    ? name
    : "dashboard";
  appViewButtons.forEach((button) => {
    const active = button.dataset.appViewButton === selectedName;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  appViews.forEach((view) => { view.hidden = view.dataset.appView !== selectedName; });
  document.body.dataset.activeAppView = selectedName;
  if (persist) saveAppView(selectedName);
}

appViewButtons.forEach((button) => {
  button.addEventListener("click", () => activateAppView(button.dataset.appViewButton, true));
});
// Sync any preference retained by an older browser-only release into config.json.
activateAppView(savedAppView(), true);

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

let settingsToastTimer = null;

// Keep dialog feedback visible for five seconds after the latest result.
function showSettingsToast(text, failed = false) {
  const stack = byId("settingsToasts");
  clearTimeout(settingsToastTimer);
  const toast = document.createElement("button");
  toast.type = "button";
  toast.className = `dialog-toast${failed ? " dialog-toast--error" : ""}`;
  toast.textContent = `${failed ? "Error: " : ""}${text}`;
  toast.setAttribute("aria-label", `${toast.textContent} Click to dismiss.`);
  toast.addEventListener("click", () => {
    clearTimeout(settingsToastTimer);
    toast.remove();
  }, {once: true});
  stack.replaceChildren(toast);
  settingsToastTimer = setTimeout(() => toast.remove(), 5000);
}

const settingsDialog = byId("settingsDialog");
const settingsForm = byId("settingsForm");
if (settingsDialog && settingsForm) {
  const tabs = Array.from(settingsDialog.querySelectorAll("[data-settings-pane]"));
  const panes = Array.from(settingsDialog.querySelectorAll("[data-pane]"));
  const locationDataElement = byId("forecastLocationData");
  const parsedLocationData = locationDataElement
    ? JSON.parse(locationDataElement.textContent)
    : {current: {}, defaults: {}};
  const cloneCatalog = (catalog) => (catalog || []).map((location) => ({...location}));
  const forecastLocationCatalogs = {
    birdsong: cloneCatalog(parsedLocationData.current.birdsong),
    frog_calls: cloneCatalog(parsedLocationData.current.frog_calls),
    whale_song: cloneCatalog(parsedLocationData.current.whale_song),
    dolphin_calls: cloneCatalog(parsedLocationData.current.dolphin_calls),
    ocean_swell: cloneCatalog(parsedLocationData.current.ocean_swell),
    storm_outlook: cloneCatalog(parsedLocationData.current.storm_outlook),
  };
  const defaultForecastLocationCatalogs = {
    birdsong: cloneCatalog(parsedLocationData.defaults.birdsong),
    frog_calls: cloneCatalog(parsedLocationData.defaults.frog_calls),
    whale_song: cloneCatalog(parsedLocationData.defaults.whale_song),
    dolphin_calls: cloneCatalog(parsedLocationData.defaults.dolphin_calls),
    ocean_swell: cloneCatalog(parsedLocationData.defaults.ocean_swell),
    storm_outlook: cloneCatalog(parsedLocationData.defaults.storm_outlook),
  };
  let activeForecastCatalog = "ocean_swell";
  let selectedForecastLocation = 0;

  window.addEventListener("systemlocationchange", ({detail}) => {
    if (!detail.sound_locations) return;
    for (const kind of ["birdsong", "storm_outlook"]) {
      forecastLocationCatalogs[kind] = cloneCatalog(detail.sound_locations[kind]);
      defaultForecastLocationCatalogs[kind] = cloneCatalog(detail.default_sound_locations[kind]);
    }
    renderForecastLocationEditor();
  });

  function birdsongLocationsReadOnly() {
    return activeForecastCatalog === "birdsong" && byId("birdsongProvider").value !== "xeno_canto";
  }

  function marineLocationsReadOnly() {
    return MARINE_BACKGROUNDS.includes(activeForecastCatalog);
  }

  function selectedLocationCatalog() {
    return birdsongLocationsReadOnly()
      ? parsedLocationData.current.commons_birdsong
      : forecastLocationCatalogs[activeForecastCatalog];
  }

  function forecastCatalogLabel() {
    return {ocean_swell: "Ocean Swells", storm_outlook: "Storm Outlook", birdsong: "Birdsong", frog_calls: "Frog Calls", whale_song: "Whale Song", dolphin_calls: "Dolphin Calls"}[activeForecastCatalog];
  }

  function movedForecastLocationName(latitude, longitude) {
    const latitudeText = `${Math.abs(latitude).toFixed(2)}°${latitude >= 0 ? "N" : "S"}`;
    const longitudeText = `${Math.abs(longitude).toFixed(2)}°${longitude >= 0 ? "E" : "W"}`;
    return `${latitudeText}, ${longitudeText}`;
  }

  function renderForecastMarkers() {
    const layer = byId("forecastLocationMarkerLayer");
    if (!layer) return;
    layer.replaceChildren();
    selectedLocationCatalog().forEach((location, index) => {
      const position = projectCoordinates(location.longitude, location.latitude);
      const marker = createSvgElement("g", {
        class: `forecast-location-marker${index === selectedForecastLocation ? " is-selected" : ""}`,
        "data-location-marker": index,
        role: "button",
        tabindex: "0",
        "aria-label": `Location ${index + 1}: ${location.name}`,
      });
      const circle = createSvgElement("circle", {cx: position.x, cy: position.y, r: 13});
      const label = createSvgElement("text", {x: position.x, y: position.y + 4, "text-anchor": "middle"});
      label.textContent = String(index + 1);
      const title = createSvgElement("title");
      title.textContent = `${location.name} · ${Number(location.latitude).toFixed(2)}, ${Number(location.longitude).toFixed(2)}`;
      marker.append(circle, label, title);
      marker.addEventListener("click", (event) => {
        event.stopPropagation();
        selectedForecastLocation = index;
        renderForecastLocationEditor();
      });
      marker.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        selectedForecastLocation = index;
        renderForecastLocationEditor();
      });
      layer.append(marker);
    });
  }

  function coordinateInput(label, value, minimum, maximum, onChange) {
    const wrapper = document.createElement("label");
    wrapper.className = "forecast-coordinate-input";
    const caption = document.createElement("span");
    caption.textContent = label;
    const input = document.createElement("input");
    input.type = "number";
    input.min = String(minimum);
    input.max = String(maximum);
    input.step = "0.01";
    input.value = Number(value).toFixed(2);
    input.addEventListener("change", () => {
      const parsed = Number(input.value);
      if (!Number.isFinite(parsed)) {
        input.value = Number(value).toFixed(2);
        return;
      }
      const normalized = Math.max(minimum, Math.min(maximum, parsed));
      input.value = normalized.toFixed(2);
      onChange(normalized);
      renderForecastMarkers();
    });
    wrapper.append(caption, input);
    return wrapper;
  }

  function renderForecastLocationList() {
    const list = byId("forecastLocationList");
    if (!list) return;
    list.replaceChildren();
    const sortedLocations = selectedLocationCatalog()
      .map((location, index) => ({location, index}))
      .sort((left, right) => left.location.name.localeCompare(
        right.location.name, undefined, {sensitivity: "base", numeric: true}
      ));
    sortedLocations.forEach(({location, index}) => {
      const row = document.createElement("div");
      row.className = `forecast-location-row${index === selectedForecastLocation ? " is-selected" : ""}`;
      const selector = document.createElement("button");
      selector.type = "button";
      selector.className = "forecast-location-number";
      selector.textContent = String(index + 1);
      selector.setAttribute("aria-label", `Select location ${index + 1}`);
      selector.addEventListener("click", () => {
        selectedForecastLocation = index;
        renderForecastLocationEditor();
      });
      const fields = document.createElement("div");
      fields.className = "forecast-location-fields";
      const coordinates = document.createElement("div");
      coordinates.className = "forecast-location-coordinates";
      coordinates.append(
        coordinateInput("Lat", location.latitude, -90, 90, (value) => { location.latitude = value; }),
        coordinateInput("Lon", location.longitude, -180, 180, (value) => { location.longitude = value; }),
      );
      const nameField = document.createElement("label");
      nameField.className = "forecast-location-name";
      const nameLabel = document.createElement("span");
      nameLabel.textContent = "Name";
      const name = document.createElement("input");
      name.type = "text";
      name.maxLength = 80;
      name.value = location.name;
      name.setAttribute("aria-label", `Location ${index + 1} name`);
      name.addEventListener("focus", () => {
        selectedForecastLocation = index;
        renderForecastMarkers();
        row.classList.add("is-selected");
      });
      name.addEventListener("input", () => {
        location.name = name.value;
        renderForecastMarkers();
      });
      name.addEventListener("change", renderForecastLocationEditor);
      nameField.append(nameLabel, name);
      fields.append(nameField, coordinates);
      fields.querySelectorAll("input").forEach((input) => { input.readOnly = birdsongLocationsReadOnly() || marineLocationsReadOnly(); });
      if (marineLocationsReadOnly()) {
        const includeLabel = document.createElement("label");
        includeLabel.className = "marine-location-selection";
        const include = document.createElement("input");
        include.type = "checkbox";
        include.checked = location.selected;
        include.setAttribute("aria-label", `Include ${location.name}`);
        include.addEventListener("change", () => {
          location.selected = include.checked;
          renderForecastLocationEditor();
        });
        const recordingCount = Number(location.recording_count || 0);
        includeLabel.append(include, document.createTextNode(`Include in playback · ${recordingCount} recording${recordingCount === 1 ? "" : "s"}`));
        fields.prepend(includeLabel);
      }
      row.append(selector, fields);
      list.append(row);
    });
  }

  function renderForecastLocationEditor() {
    const catalog = selectedLocationCatalog();
    settingsDialog.querySelectorAll("[data-location-catalog]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.locationCatalog === activeForecastCatalog);
    });
    byId("forecastLocationCount").textContent = marineLocationsReadOnly()
      ? `${catalog.filter((location) => location.selected).length} / ${catalog.length} sites selected`
      : `${catalog.length} / 19 locations`;
    byId("restoreForecastLocations").disabled = birdsongLocationsReadOnly();
    byId("forecastLocationReadout").textContent = marineLocationsReadOnly()
      ? "Choose recording sites. Each return to a site plays its next recording. Map points mark documented recording locations or regions."
      : birdsongLocationsReadOnly()
      ? "Commons uses curated locations. Select Xeno-canto in Sound Sources to edit regions."
      : `Location ${selectedForecastLocation + 1} selected. Click the map to move it.${RECORDED_BACKGROUNDS.includes(activeForecastCatalog) ? ` ${forecastCatalogLabel()} searches within 100 km.` : ""}`;
    renderForecastMarkers();
    renderForecastLocationList();
  }

  byId("mapProjection").addEventListener("change", () => {
    const markers = Array.from(document.querySelectorAll(
      "#mapHistoryLayer circle, #mapBackgroundLayer circle, #mapPulseLayer circle, #mapSystemLocationLayer circle"
    )).map((marker) => ({
      marker,
      coordinates: inverseProjectCoordinates(Number(marker.getAttribute("cx")), Number(marker.getAttribute("cy"))),
    }));
    mapProjection = byId("mapProjection").value;
    markers.forEach(({marker, coordinates}) => {
      const position = projectCoordinates(coordinates.longitude, coordinates.latitude);
      marker.setAttribute("cx", position.x);
      marker.setAttribute("cy", position.y);
    });
    const asset = mapProjection === "eckert_iv" ? "world-land-eckert-iv.svg" : "gaia-scape-icon.svg";
    document.querySelectorAll("[data-map-land]").forEach((land) => {
      land.setAttribute("href", `/static/${asset}#realistic-land`);
    });
    byId("worldMapDescription").textContent = `${mapProjection === "eckert_iv" ? "Eckert IV" : "Robinson"} projection with latitude and longitude grid, approximate system location, recent environmental locations, and animated sound cues.`;
    byId("mapCoordinateReadout").textContent = "Move over the map to inspect coordinates";
    renderMapProjection();
    renderMapGrid();
    renderForecastMarkers();
  });

  const forecastLocationMap = byId("forecastLocationMap");
  if (forecastLocationMap) {
    const boundary = mapProjectionBoundary();
    byId("forecastMapClipPath").setAttribute("d", boundary);
    byId("forecastMapOceanPath").setAttribute("d", boundary);
    forecastLocationMap.addEventListener("click", (event) => {
      if (birdsongLocationsReadOnly() || marineLocationsReadOnly()) return;
      const point = forecastLocationMap.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      const mapPoint = point.matrixTransform(forecastLocationMap.getScreenCTM().inverse());
      if (!mapContainsPoint(mapPoint.x, mapPoint.y)) return;
      const coordinates = inverseProjectCoordinates(mapPoint.x, mapPoint.y);
      const location = selectedLocationCatalog()[selectedForecastLocation];
      location.latitude = Number(coordinates.latitude.toFixed(4));
      location.longitude = Number(coordinates.longitude.toFixed(4));
      location.name = movedForecastLocationName(
        location.latitude, location.longitude
      );
      renderForecastLocationEditor();
      byId("forecastLocationReadout").textContent = `Moved location ${selectedForecastLocation + 1} to ${Math.abs(location.latitude).toFixed(2)}°${location.latitude >= 0 ? "N" : "S"}, ${Math.abs(location.longitude).toFixed(2)}°${location.longitude >= 0 ? "E" : "W"}.`;
    });
  }
  settingsDialog.querySelectorAll("[data-location-catalog]").forEach((button) => {
    button.addEventListener("click", () => {
      activeForecastCatalog = button.dataset.locationCatalog;
      selectedForecastLocation = 0;
      renderForecastLocationEditor();
    });
  });
  byId("restoreForecastLocations")?.addEventListener("click", () => {
    forecastLocationCatalogs[activeForecastCatalog] = cloneCatalog(
      defaultForecastLocationCatalogs[activeForecastCatalog]
    );
    selectedForecastLocation = 0;
    renderForecastLocationEditor();
    showSettingsToast(`${forecastCatalogLabel()} defaults restored. Save settings to apply.`);
  });

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
    if (name === "locations") renderForecastLocationEditor();
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
  settingsDialog.querySelectorAll("[data-sound-picker]").forEach((picker) => {
    const select = byId(picker.dataset.select);
    const track = picker.querySelector(".sound-track");
    const options = Array.from(select.options);
    const position = picker.querySelector(".sound-position");
    let scrollTimer;
    const cards = options.map((option) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "sound-choice";
      card.setAttribute("role", "radio");
      card.setAttribute("aria-label", option.textContent);
      const art = document.createElement("img");
      art.src = `/static/${picker.dataset.artPrefix || "sound"}-${option.hasAttribute("data-legacy") ? "none" : option.value}.svg`;
      art.alt = "";
      art.width = 512;
      art.height = 512;
      const caption = document.createElement("span");
      caption.textContent = option.textContent;
      card.append(art, caption);
      track.append(card);
      card.addEventListener("click", () => choose(options.indexOf(option), false));
      return card;
    });
    const render = () => {
      cards.forEach((card, index) => {
        const selected = index === select.selectedIndex;
        card.setAttribute("aria-checked", String(selected));
        card.tabIndex = selected ? 0 : -1;
      });
      position.textContent = `${select.selectedIndex + 1} / ${options.length}`;
    };
    const align = () => { track.scrollLeft = select.selectedIndex * track.clientWidth; };
    const choose = (index, focus) => {
      select.selectedIndex = (index + options.length) % options.length;
      // Keep an existing retired sound until the user explicitly replaces it.
      if (!options[select.selectedIndex].hasAttribute("data-legacy")) {
        const legacyIndex = options.findIndex((option) => option.hasAttribute("data-legacy"));
        if (legacyIndex !== -1) {
          cards.splice(legacyIndex, 1)[0].remove();
          options.splice(legacyIndex, 1)[0].remove();
        }
      }
      render();
      align();
      select.dispatchEvent(new Event("change", {bubbles: true}));
      if (focus) cards[select.selectedIndex].focus({preventScroll: true});
    };
    picker.querySelectorAll("[data-sound-step]").forEach((button) => {
      button.addEventListener("click", () => choose(select.selectedIndex + Number(button.dataset.soundStep), false));
    });
    track.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const index = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
        : select.selectedIndex + (event.key === "ArrowRight" ? 1 : -1);
      choose(index, true);
    });
    track.addEventListener("scroll", () => {
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        if (!track.clientWidth) return;
        const index = Math.round(track.scrollLeft / track.clientWidth);
        if (index !== select.selectedIndex) choose(index, false);
      }, 120);
    });
    select.addEventListener("change", render);
    new ResizeObserver(() => { if (track.clientWidth) align(); }).observe(track);
    render();
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
  const mtgLiToggle = byId("sourceMtgLi");
  const mtgLiCredentials = byId("mtgLiCredentials");
  const eumetsatConsumerKey = byId("eumetsatConsumerKey");
  const eumetsatConsumerSecret = byId("eumetsatConsumerSecret");
  const updateMtgLiCredentials = () => {
    mtgLiCredentials.hidden = !mtgLiToggle.checked;
    const needsInitialCredentials = (
      mtgLiToggle.checked && mtgLiToggle.dataset.credentialsConfigured !== "true"
    );
    eumetsatConsumerKey.required = needsInitialCredentials;
    eumetsatConsumerSecret.required = needsInitialCredentials;
  };
  mtgLiToggle.addEventListener("change", updateMtgLiCredentials);
  updateMtgLiCredentials();
  ["event1Instrument", "event2Instrument", "event3Instrument"].forEach((selectId) => {
    const select = byId(selectId);
    const control = select.parentElement.querySelector("[data-lightning-sample-control]");
    const updateSampleRateVisibility = () => {
      control.hidden = !["lightning_glass", "natural_thunder"].includes(select.value);
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
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      try {
        const instrument = byId(button.dataset.select).value;
        const kind = button.dataset.kind === "background"
          ? instrument
          : (instrument === "tidal_bell"
            ? "tide_turn"
            : (["lightning_glass", "natural_thunder"].includes(instrument)
              ? "lightning_flash"
              : "earthquake"));
        if (!deviceMuted && (localRecordingPlayback || deviceListening)
            && RECORDED_BACKGROUNDS.includes(kind)) {
          await recordingNormalizer.resume();
        }
        const payload = await request("/api/instruments/preview", {
          method: "POST",
          body: JSON.stringify({
            kind,
            instrument,
            volume: Number(byId(button.dataset.volume).value) / 100,
            output_channel: {backgroundVolume: "background", event1Volume: "event_1",
              event2Volume: "event_2", event3Volume: "event_3"}[button.dataset.volume],
          }),
        });
        showSettingsToast("Previewed " + instrumentLabel(payload.instrument) + ".");
        await Promise.all([updateStatus(), updateEvents()]);
      } catch (error) {
        showSettingsToast(error.message, true);
      } finally {
        button.removeAttribute("aria-busy");
        updatePreviewState();
      }
    });
  });
  byId("backgroundInstrument").addEventListener("change", (event) => {
    if (event.target.value !== recordingKind) stopRecordingPlayback();
    updateBackgroundStatus(null);
  });
  updateBackgroundSoundsTitle(byId("backgroundInstrument").value);
  byId("displayUnits").addEventListener("change", () => {
    Promise.all([updateStatus(), updateEvents()]);
  });
  const updateBirdsongCredentials = () => {
    byId("birdsongCredentials").hidden = !byId("sourceBirdsong").checked;
    byId("xenoCantoCredentials").hidden = byId("birdsongProvider").value !== "xeno_canto";
  };
  byId("sourceBirdsong").addEventListener("change", updateBirdsongCredentials);
  byId("birdsongProvider").addEventListener("change", () => {
    updateBirdsongCredentials();
    renderForecastLocationEditor();
  });
  updateBirdsongCredentials();
  const updateFrogCallsCredentials = () => {
    byId("frogCallsCredentials").hidden = !byId("sourceFrogCalls").checked;
  };
  byId("sourceFrogCalls").addEventListener("change", updateFrogCallsCredentials);
  updateFrogCallsCredentials();
  const sharedXenoCantoKeyInputs = [byId("xenoCantoApiKey"), byId("frogCallsApiKey")];
  sharedXenoCantoKeyInputs.forEach((input) => {
    input.addEventListener("input", () => {
      sharedXenoCantoKeyInputs.forEach((other) => { if (other !== input) other.value = input.value; });
    });
  });
  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const saveButton = settingsForm.querySelector('button[type="submit"]');
    saveButton.disabled = true;
    saveButton.textContent = "Saving…";
    try {
      await request("/api/settings/locations", {
        method: "PUT",
        body: JSON.stringify({
          map_projection: mapProjection,
          sound_location_order: byId("soundLocationOrder").value,
          birdsong_locations: forecastLocationCatalogs.birdsong,
          frog_calls_locations: forecastLocationCatalogs.frog_calls,
          whale_song_regions: forecastLocationCatalogs.whale_song.filter((location) => location.selected).map((location) => location.id),
          dolphin_calls_regions: forecastLocationCatalogs.dolphin_calls.filter((location) => location.selected).map((location) => location.id),
          ocean_swell_locations: forecastLocationCatalogs.ocean_swell,
          storm_outlook_locations: forecastLocationCatalogs.storm_outlook,
        }),
      });
      const audioSettings = await request("/api/settings/audio", {
        method: "PUT",
        body: JSON.stringify({
          enabled_sources: [
            ...(byId("sourceUsgs").checked ? ["usgs"] : []),
            ...(byId("sourceMarine").checked ? ["open_meteo_marine"] : []),
            ...(byId("sourceStorm").checked ? ["open_meteo_storm"] : []),
            ...(byId("sourceGlm").checked ? ["noaa_glm"] : []),
            ...(byId("sourceMtgLi").checked ? ["eumetsat_mtg_li"] : []),
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
          eumetsat_consumer_key: eumetsatConsumerKey.value,
          eumetsat_consumer_secret: eumetsatConsumerSecret.value,
          birdsong_enabled: byId("sourceBirdsong").checked,
          frog_calls_enabled: byId("sourceFrogCalls").checked,
          whale_song_enabled: byId("sourceWhaleSong").checked,
          dolphin_calls_enabled: byId("sourceDolphinCalls").checked,
          ...Object.fromEntries(Object.keys(MAMMAL_BACKGROUNDS).map(kind => [`${kind}_enabled`, byId(`source_${kind}`).checked])),
          birdsong_provider: byId("birdsongProvider").value,
          xeno_canto_api_key: byId("xenoCantoApiKey").value,
          units: byId("displayUnits").value,
          announcements_enabled: byId("announcementsEnabled").checked,
          announcement_synthesizer: byId("announcementSynthesizer").value,
          announcement_voice: byId("announcementVoice").value,
          announcement_variant: byId("announcementVariant").value,
          announcement_volume: Number(byId("announcementVolume").value) / 100,
          system_location_enabled: byId("systemLocationEnabled").checked,
        }),
      });
      applyRecordingVolume(audioSettings.instrument_volumes.background);
      globalThis.recordingAnnouncements?.configure(audioSettings);
      if (audioSettings.eumetsat_credentials_configured) {
        mtgLiToggle.dataset.credentialsConfigured = "true";
        eumetsatConsumerKey.value = "";
        eumetsatConsumerSecret.value = "";
        eumetsatConsumerKey.placeholder = "Saved — enter only to replace";
        eumetsatConsumerSecret.placeholder = "Saved — enter only to replace";
        updateMtgLiCredentials();
      }
      if (audioSettings.xeno_canto_credentials_configured) {
        sharedXenoCantoKeyInputs.forEach((input) => {
          input.value = "";
          input.placeholder = "Saved — enter only to replace";
        });
      }
      if (recordingKind && !audioSettings[`${recordingKind}_enabled`]) stopRecordingPlayback();
      await updateSystemLocation();
      showSettingsToast("Settings saved.");
      await updateEvents();
    } catch (error) {
      showSettingsToast(error.message, true);
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = "Save settings";
    }
  });
}

document.querySelectorAll(".status-card").forEach((card) => {
  card.addEventListener("mouseover", () => {
    if (card.querySelector(".status-card-details")?.hidden) {
      card.removeAttribute("title");
      return;
    }
    card.title = Array.from(card.querySelectorAll("[data-status-field]"), (field) =>
      field.getAttribute("aria-label") || field.textContent.trim()
    ).join("\n");
  });
});

Promise.all([updateStatus(), updateEvents(), updateEmittedCues(), updateSystemLocation()]);
setInterval(updateStatus, 3000);
setInterval(updateRecordingCountdown, 250);

// Appearance is local to this browser and does not change installation settings.
const themeInputs = Array.from(document.querySelectorAll('input[name="theme"]'));
function applyTheme(name) {
  const selected = themeInputs.some((input) => input.value === name) ? name : "earth";
  document.documentElement.dataset.theme = selected;
  themeInputs.forEach((input) => { input.checked = input.value === selected; });
}
try {
  applyTheme(window.localStorage.getItem("gaiascapes-theme"));
} catch (_error) {
  applyTheme("earth");
}
themeInputs.forEach((input) => input.addEventListener("change", () => {
  applyTheme(input.value);
  try {
    window.localStorage.setItem("gaiascapes-theme", input.value);
    showSettingsToast("Theme applied.");
  } catch (_error) {
    showSettingsToast("Theme applied. Browser storage is unavailable, so it cannot be remembered after reload.", true);
  }
}));
