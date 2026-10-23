/** Background animation preferences and persistent color around the map.
 *
 * Paint accumulates for nineteen background location visits. Display choices
 * preview immediately and are saved with the installation by the settings form.
 */
(() => {
  const savedSettings = JSON.parse(document.getElementById("displaySettingsData")?.textContent || "{}");
  const inputs = Array.from(document.querySelectorAll('input[name="backgroundAnimation"]'));
  const paletteInput = document.getElementById("backgroundPalette");
  const shapeInput = document.getElementById("backgroundPaintShape");
  const eventsInput = document.getElementById("backgroundEvents");
  const eventChoices = ["both", "events", "background"];
  let eventSelection = "both";
  const palettes = {
    natural: null,
    aurora: ["#269eaa", "#7954bf", "#2aa579", "#dc73aa", "#4289cf"],
    wildflower: ["#e27e6b", "#d7ab42", "#a38bd2", "#cf7194", "#77a36b"],
    pastel: ["#edb59d", "#a8d5bf", "#c5b4e0", "#a7cce7", "#ead798"],
  };
  const shapes = ["bloom", "watercolor", "ribbon"];
  let palette = "natural";
  let shape = "bloom";
  const paletteChoices = Object.keys(palettes);
  const paints = [];
  const roundLength = 19;
  let mode = "burst";

  function clearPaint() {
    paints.forEach(({wave}) => wave.remove());
    paints.length = 0;
  }

  function applyPalette(wave, index, originalColors, selectedPalette) {
    const colors = palettes[selectedPalette];
    if (!colors) {
      if (originalColors) {
        wave.style.setProperty("--wave-color", originalColors.primary);
        wave.style.setProperty("--wave-inner", originalColors.inner);
      }
      return;
    }
    // Interpolate around the palette to give each of the nineteen visits a shade.
    const position = (index % roundLength) * colors.length / roundLength;
    const lower = Math.floor(position);
    const blend = position - lower;
    const start = parseInt(colors[lower].slice(1), 16);
    const end = parseInt(colors[(lower + 1) % colors.length].slice(1), 16);
    const channels = [16, 8, 0].map(shift => Math.round(
      ((start >> shift) & 255) * (1 - blend) + ((end >> shift) & 255) * blend
    ));
    wave.style.setProperty("--wave-color", `rgb(${channels.join(", ")})`);
    wave.style.setProperty("--wave-inner", colors[(lower + 1) % colors.length]);
  }

  function stylePaint(paint, index) {
    if (palette !== "random") paint.palette = palette;
    if (shape !== "random") paint.shape = shape;
    applyPalette(paint.wave, index, paint.originalColors, paint.palette);
    paint.wave.dataset.paintPalette = paint.palette;
    paint.wave.dataset.paintShape = paint.shape;
    paint.wave.style.setProperty("--paint-angle", `${paint.angle * 180 / Math.PI + 90}deg`);
    // Alternate the irregular outlines and stroke direction between visits.
    paint.wave.style.setProperty("--paint-variation", String(index % 2 ? -1 : 1));
  }

  function positionPaint() {
    const bounds = document.getElementById("worldMap")?.getBoundingClientRect();
    const centerX = bounds?.width ? bounds.left + bounds.width / 2 : window.innerWidth / 2;
    const centerY = bounds?.height ? bounds.top + bounds.height / 2 : window.innerHeight / 2;
    const radiusX = (bounds?.width || window.innerWidth) * .53;
    const radiusY = (bounds?.height || window.innerHeight) * .53;
    paints.forEach(({wave, angle}) => {
      wave.style.setProperty("--wave-x", `${centerX + Math.cos(angle) * radiusX}px`);
      wave.style.setProperty("--wave-y", `${centerY + Math.sin(angle) * radiusY}px`);
    });
  }

  function applyMode(value) {
    const selected = value === "paint" ? "paint" : "burst";
    if (selected !== mode) {
      clearPaint();
      document.querySelectorAll(".event-wave--background").forEach(wave => wave.remove());
      if (!document.querySelector(".event-wave")) {
        document.body.classList.remove("preview-pulse-visible");
      }
    }
    mode = selected;
    document.documentElement.dataset.backgroundAnimation = mode;
    inputs.forEach(input => { input.checked = input.value === mode; });
  }

  /** Style a background wave and retain it at full size in Paint mode. */
  function retain(wave, event) {
    if (mode !== "paint") return false;
    if (paints.length === roundLength) clearPaint();
    const longitude = Number(event?.longitude ?? 0);
    const latitude = Number(event?.latitude ?? 0);
    // Stretch each location out to the map's perimeter, leaving its center clear.
    const angle = Math.atan2(-latitude / 90, longitude / 180);
    wave.classList.add("event-wave--paint");
    const paint = {wave, angle,
      palette: palette === "random" ? paletteChoices[Math.floor(Math.random() * paletteChoices.length)] : palette,
      shape: shape === "random" ? shapes[Math.floor(Math.random() * shapes.length)] : shape,
      originalColors: {
      primary: wave.style.getPropertyValue("--wave-color"),
      inner: wave.style.getPropertyValue("--wave-inner"),
    }};
    paints.push(paint);
    stylePaint(paint, paints.length - 1);
    positionPaint();
    return true;
  }

  applyMode(savedSettings.background_animation);
  inputs.forEach(input => input.addEventListener("change", () => applyMode(input.value)));

  function loadChoice(input, key, valid, fallback) {
    const saved = savedSettings[key];
    const selected = valid.includes(saved) ? saved : fallback;
    if (input) input.value = selected;
    return selected;
  }

  palette = loadChoice(paletteInput, "background_palette", [...paletteChoices, "random"], "natural");
  shape = loadChoice(shapeInput, "background_paint_shape", [...shapes, "random"], "bloom");
  eventSelection = loadChoice(eventsInput, "background_events", eventChoices, "both");
  function applyEventSelection() {
    document.documentElement.dataset.animationEvents = eventSelection;
    document.body.classList.remove("preview-pulse-visible");
  }
  applyEventSelection();
  eventsInput?.addEventListener("change", () => {
    eventSelection = eventChoices.includes(eventsInput.value) ? eventsInput.value : "both";
    applyEventSelection();
  });

  /** Whether a cue's color effect is included in the current display filter. */
  function visible(role) {
    return mode !== "paint" || eventSelection === "both" || (eventSelection === "background" ? role === "background" : role !== "background");
  }

  function updatePaintChoices() {
    palette = [...paletteChoices, "random"].includes(paletteInput?.value) ? paletteInput.value : "natural";
    shape = [...shapes, "random"].includes(shapeInput?.value) ? shapeInput.value : "bloom";
    paints.forEach(stylePaint);
  }
  paletteInput?.addEventListener("change", updatePaintChoices);
  shapeInput?.addEventListener("change", updatePaintChoices);
  window.addEventListener("resize", positionPaint);
  const map = document.getElementById("worldMap");
  if (map && typeof ResizeObserver !== "undefined") new ResizeObserver(positionPaint).observe(map);
  globalThis.backgroundAnimation = {retain, visible};
})();
