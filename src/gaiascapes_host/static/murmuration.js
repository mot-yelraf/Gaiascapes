/** A translucent particle cloud flowing around the map's outline.
 *
 * A shared flow field stretches and folds thousands of tiny flecks into drifting
 * clouds. Sampling the displayed projection anchors them near the map's edge,
 * with a little overlap and room to billow into the surrounding background.
 */
(() => {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const particles = [];
  const palettes = {
    natural: ["#355c55", "#797e58", "#6c8892", "#977b62"],
    aurora: ["#269eaa", "#7954bf", "#2aa579", "#dc73aa", "#4289cf"],
    wildflower: ["#e27e6b", "#d7ab42", "#a38bd2", "#cf7194", "#77a36b"],
    pastel: ["#edb59d", "#a8d5bf", "#c5b4e0", "#a7cce7", "#ead798"],
  };
  let canvas = null, context = null, frame = null, previous = null;
  let resizeObserver = null, outlineObserver = null;
  let width = 1, height = 1, elapsed = 0, included = true;
  let palette = "aurora", boundary = [];
  const count = 5000, samples = 192;
  const flockSpeeds = [-.043, .052, -.038, .047, -.056];

  function measureBoundary() {
    const map = document.getElementById("worldMap");
    const outline = document.getElementById("mapOceanPath");
    const bounds = map?.getBoundingClientRect();
    const cx = bounds?.width ? bounds.left + bounds.width / 2 : width / 2;
    const cy = bounds?.height ? bounds.top + bounds.height / 2 : height * .45;
    const rx = (bounds?.width || width * .8) / 2;
    const ry = (bounds?.height || height * .55) / 2;
    const length = outline?.getTotalLength?.() || 0;
    const matrix = length ? outline.getScreenCTM() : null;
    const points = Array.from({length: samples}, (_, index) => {
      if (matrix) {
        const point = outline.getPointAtLength(index * length / samples);
        return {x: matrix.a * point.x + matrix.c * point.y + matrix.e,
          y: matrix.b * point.x + matrix.d * point.y + matrix.f};
      }
      const angle = index * Math.PI * 2 / samples;
      return {x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle)};
    });
    boundary = points.map((point, index) => {
      const before = points[(index + samples - 1) % samples];
      const after = points[(index + 1) % samples];
      let nx = after.y - before.y, ny = before.x - after.x;
      if (nx * (point.x - cx) + ny * (point.y - cy) < 0) { nx = -nx; ny = -ny; }
      const magnitude = Math.hypot(nx, ny) || 1;
      return {...point, nx: nx / magnitude, ny: ny / magnitude};
    });
  }

  function resize() {
    if (!canvas) return;
    width = Math.max(1, window.innerWidth);
    height = Math.max(1, window.innerHeight);
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    measureBoundary();
    draw();
  }

  function colorAt(position) {
    if (palette === "random") return `hsl(${(position * 72) % 360} 52% 52%)`;
    const colors = palettes[palette];
    const wrapped = ((position % colors.length) + colors.length) % colors.length;
    const index = Math.floor(wrapped), blend = wrapped - index;
    const start = parseInt(colors[index].slice(1), 16);
    const end = parseInt(colors[(index + 1) % colors.length].slice(1), 16);
    const channels = [16, 8, 0].map(shift => Math.round(
      ((start >> shift) & 255) * (1 - blend) + ((end >> shift) & 255) * blend));
    return `rgb(${channels.join(", ")})`;
  }

  function draw() {
    if (!context || !boundary.length) return;
    context.clearRect(0, 0, width, height);
    const thickness = Math.max(48, Math.min(180, Math.min(width, height) * .28));
    const colors = Array.from({length: 12}, (_, index) => colorAt(elapsed / 22 + index / 6));
    particles.forEach(particle => {
      // Clouds circulate independently, with waves that stretch their tails
      // and roll their cross sections. No discrete wing shapes or wingbeats.
      const phase = elapsed * flockSpeeds[particle.group] + particle.group * Math.PI * 2 / flockSpeeds.length;
      const spread = .5 + .24 * Math.sin(elapsed * .17 + particle.group * 2);
      const angle = phase + particle.along * spread
        + .1 * Math.sin(particle.along * 5 + elapsed * .23 + particle.depth * 3);
      const position = ((angle / (Math.PI * 2) % 1 + 1) % 1) * samples;
      const index = Math.floor(position), blend = position - index;
      const a = boundary[index], b = boundary[(index + 1) % samples];
      const roll = Math.sin(particle.along * 6 - elapsed * .55 + particle.phase);
      const envelope = Math.sqrt(Math.max(0, 1 - particle.along * particle.along / 4));
      const offset = -10 + thickness * (.02 + envelope *
        (.05 + particle.depth * .85 + .14 * roll * Math.sin(elapsed * .21 + particle.group)));
      const x = a.x + (b.x - a.x) * blend + (a.nx + (b.nx - a.nx) * blend) * offset;
      const y = a.y + (b.y - a.y) * blend + (a.ny + (b.ny - a.ny) * blend) * offset;
      context.fillStyle = colors[particle.color];
      context.globalAlpha = particle.opacity * (.7 + .3 * envelope);
      context.beginPath();
      context.ellipse(x, y, particle.size * 1.5, particle.size * .65,
        angle + roll * .5, 0, Math.PI * 2);
      context.fill();
    });
    context.globalAlpha = 1;
  }

  function tick(now) {
    frame = null;
    if (!canvas || !included || document.hidden || reducedMotion.matches) return;
    if (previous === null) previous = now;
    if (now - previous >= 1000 / 30) {
      elapsed += Math.min(.05, (now - previous) / 1000);
      previous = now;
      draw();
    }
    frame = requestAnimationFrame(tick);
  }

  function syncMotion() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    previous = null;
    if (!canvas) return;
    draw();
    if (included && !document.hidden && !reducedMotion.matches) frame = requestAnimationFrame(tick);
  }

  /** Preview a palette; each cloud blends through its colors over time. */
  function setPalette(value) {
    palette = value === "random" || Object.hasOwn(palettes, value) ? value : "aurora";
    draw();
  }

  /** Pause the cloud when the display filter excludes background effects. */
  function setVisible(value) {
    included = value;
    syncMotion();
  }

  /** Show the cloud immediately, without needing a sound cue. */
  function start() {
    if (canvas) return;
    const layer = document.getElementById("eventPulseLayer");
    if (!layer) return;
    canvas = document.createElement("canvas");
    canvas.className = "murmuration-canvas";
    canvas.setAttribute("aria-hidden", "true");
    context = canvas.getContext("2d");
    if (!context) {
      canvas = null;
      console.warn("Murmuration needs a browser with Canvas 2D support.");
      return;
    }
    layer.append(canvas);
    for (let index = 0; index < count; index++) {
      particles.push({group: index % flockSpeeds.length,
        along: (Math.random() + Math.random() + Math.random() - 1.5) * 1.3,
        depth: Math.random(), phase: Math.random() * Math.PI * 2,
        size: 1.2 + Math.random() * 1.8, color: index % 12,
        opacity: .18 + Math.random() * .28});
    }
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", resize, {passive: true});
    document.addEventListener("visibilitychange", syncMotion);
    reducedMotion.addEventListener("change", syncMotion);
    const map = document.getElementById("worldMap");
    if (map && typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(map);
    }
    const outline = document.getElementById("mapOceanPath");
    if (outline && typeof MutationObserver !== "undefined") {
      outlineObserver = new MutationObserver(resize);
      outlineObserver.observe(outline, {attributes: true, attributeFilter: ["d"]});
    }
    syncMotion();
  }

  /** Remove the cloud and release its animation and layout observers. */
  function stop() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    previous = null;
    elapsed = 0;
    canvas?.remove();
    canvas = null;
    context = null;
    particles.length = 0;
    boundary = [];
    resizeObserver?.disconnect();
    outlineObserver?.disconnect();
    resizeObserver = null;
    outlineObserver = null;
    window.removeEventListener("resize", resize);
    window.removeEventListener("scroll", resize);
    document.removeEventListener("visibilitychange", syncMotion);
    reducedMotion.removeEventListener("change", syncMotion);
  }

  globalThis.murmuration = {start, stop, setPalette, setVisible};
})();
