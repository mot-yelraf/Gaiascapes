"use strict";

(() => {
  const SIZE = 512;
  const CENTER = SIZE / 2;
  const RADIANS = Math.PI / 180;
  const SCALE = CENTER / Math.sin(5 * RADIANS);
  const TILE_SIZE = 1350;
  const COLUMNS = 8;
  const ATLAS_WIDTH = COLUMNS * TILE_SIZE;
  const ATLAS_HEIGHT = 4 * TILE_SIZE;
  const ASSETS = "/static/map-magnifier";

  // A local orthographic projection keeps the selected point centered even
  // when the inset straddles the date line or a pole.
  function localProjection(latitude, longitude) {
    const sinCenter = Math.sin(latitude * RADIANS);
    const cosCenter = Math.cos(latitude * RADIANS);
    return {
      project(lat, lon) {
        const sinLat = Math.sin(lat * RADIANS);
        const cosLat = Math.cos(lat * RADIANS);
        const delta = (lon - longitude) * RADIANS;
        const alongMeridian = cosLat * Math.cos(delta);
        if (sinLat * sinCenter + alongMeridian * cosCenter <= 0) return null;
        const x = CENTER + SCALE * cosLat * Math.sin(delta);
        const y = CENTER - SCALE * (sinLat * cosCenter - alongMeridian * sinCenter);
        return Math.hypot(x - CENTER, y - CENTER) < CENTER ? {x, y} : null;
      },
      texturePixel(x, y) {
        const east = (x - CENTER) / SCALE;
        const north = (CENTER - y) / SCALE;
        const up = Math.sqrt(1 - east ** 2 - north ** 2);
        const latitudeSine = north * cosCenter + up * sinCenter;
        const latitudeDegrees = Math.asin(Math.max(-1, Math.min(1, latitudeSine))) / RADIANS;
        const longitudeDelta = Math.atan2(east, up * cosCenter - north * sinCenter) / RADIANS;
        const u = Math.floor(((longitude + longitudeDelta + 540) % 360) * ATLAS_WIDTH / 360);
        const v = Math.min(ATLAS_HEIGHT - 1, Math.floor((90 - latitudeDegrees) * ATLAS_HEIGHT / 180));
        return v * ATLAS_WIDTH + u;
      },
    };
  }

  function loadTile(tile, version) {
    const image = new Image();
    image.src = `${ASSETS}/terrain-${Math.floor(tile / COLUMNS)}-${tile % COLUMNS}.jpg?v=${version}`;
    return image.decode().then(() => image);
  }

  async function drawTerrain(context, projection, version, isCurrent) {
    const samplesByTile = new Map();
    for (let y = 0; y < SIZE; y += 1) {
      const halfRow = Math.sqrt(CENTER ** 2 - (y + 0.5 - CENTER) ** 2);
      for (let x = Math.ceil(CENTER - halfRow - 0.5); x + 0.5 < CENTER + halfRow; x += 1) {
        const address = projection.texturePixel(x + 0.5, y + 0.5);
        const u = address % ATLAS_WIDTH;
        const v = Math.floor(address / ATLAS_WIDTH);
        const tile = Math.floor(v / TILE_SIZE) * COLUMNS + Math.floor(u / TILE_SIZE);
        let samples = samplesByTile.get(tile);
        if (!samples) {
          samples = [];
          samplesByTile.set(tile, samples);
        }
        samples.push((y * SIZE + x) * 4, ((v % TILE_SIZE) * TILE_SIZE + (u % TILE_SIZE)) * 4);
      }
    }
    const tileCanvas = document.createElement("canvas");
    tileCanvas.width = tileCanvas.height = TILE_SIZE;
    const tileContext = tileCanvas.getContext("2d", {willReadFrequently: true});
    const frame = context.createImageData(SIZE, SIZE);
    await Promise.all([...samplesByTile].map(async ([tile, samples]) => {
      const image = await loadTile(tile, version);
      if (!isCurrent()) return;
      tileContext.drawImage(image, 0, 0);
      const source = tileContext.getImageData(0, 0, TILE_SIZE, TILE_SIZE).data;
      for (let i = 0; i < samples.length; i += 2) {
        const target = samples[i];
        const offset = samples[i + 1];
        frame.data[target] = source[offset];
        frame.data[target + 1] = source[offset + 1];
        frame.data[target + 2] = source[offset + 2];
        frame.data[target + 3] = 255;
      }
    }));
    if (isCurrent()) context.putImageData(frame, 0, 0);
  }

  function overlaps(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }

  function withinLens(box) {
    const x = Math.max(Math.abs(box.left - CENTER), Math.abs(box.right - CENTER));
    const y = Math.max(Math.abs(box.top - CENTER), Math.abs(box.bottom - CENTER));
    return Math.hypot(x, y) < CENTER - 5;
  }

  function renderLabels(layer, context, view, occupied, svg, fontSize) {
    context.font = `600 ${fontSize}px system-ui`;
    const labels = [];
    for (const [name, latitude, longitude] of view.places) {
      if (labels.length >= 18) break;
      const point = view.projection.project(latitude, longitude);
      if (!point) continue;
      const {x, y} = point;
      const width = context.measureText(name).width;
      const options = [6, 13].flatMap(gap => [
        {left: x + gap - 2, right: x + gap + width + 4, textX: x + gap, anchor: "start"},
        {left: x - gap - width - 4, right: x - gap + 2, textX: x - gap, anchor: "end"},
      ]).map(option => ({...option, top: y - fontSize, bottom: y + 7}));
      const box = options.find(option => withinLens(option) && !occupied.some(other => overlaps(option, other)));
      if (!box) continue;
      occupied.push(box);
      const dot = svg("circle", {cx: x, cy: y, r: 2.8});
      const text = svg("text", {x: box.textX, y: y + 4,
        "text-anchor": box.anchor, "font-size": fontSize});
      text.textContent = name;
      const label = svg("g");
      label.append(dot, text);
      labels.push(label);
    }
    layer.replaceChildren(...labels);
  }

  globalThis.createMapMagnifier = function ({dialog, worldMap, svg}) {
    const canvas = dialog.querySelector("canvas");
    const context = canvas.getContext("2d");
    const labels = dialog.querySelector("[data-magnifier-labels]");
    const markers = dialog.querySelector("[data-magnifier-markers]");
    const status = dialog.querySelector("[data-magnifier-status]");
    const coordinates = dialog.querySelector("[data-magnifier-coordinates]");
    const version = encodeURIComponent(dialog.dataset.version);
    let placesRequest;
    let currentView;
    let markerRefresh;

    function renderOverlays() {
      if (!currentView || !dialog.open) return;
      const fontSize = Math.max(14, Math.ceil(12 * SIZE / canvas.clientWidth));
      const occupied = [{left: CENTER - 9, right: CENTER + 9, top: CENTER - 9, bottom: CENTER + 9}];
      const seen = new Set();
      const points = [];
      for (const marker of worldMap.querySelectorAll("[data-map-latitude]")) {
        const {mapLatitude, mapLongitude, mapMarkerLabel} = marker.dataset;
        const color = marker.getAttribute("fill");
        const key = `${mapLatitude},${mapLongitude},${color}`;
        if (seen.has(key)) continue;
        const point = currentView.projection.project(Number(mapLatitude), Number(mapLongitude));
        if (!point) continue;
        seen.add(key);
        const {x, y} = point;
        const dot = svg("circle", {cx: x, cy: y, r: 6, fill: color});
        const title = svg("title");
        title.textContent = mapMarkerLabel;
        dot.append(title);
        points.push(dot);
        occupied.push({left: x - 9, right: x + 9, top: y - 9, bottom: y + 9});
      }
      markers.replaceChildren(...points);
      renderLabels(labels, context, currentView, occupied, svg, fontSize);
    }

    function scheduleOverlayRefresh() {
      cancelAnimationFrame(markerRefresh);
      markerRefresh = requestAnimationFrame(renderOverlays);
    }

    const observer = new MutationObserver(scheduleOverlayRefresh);
    function closeFromClick(event) {
      currentView.pointerDismissed = event.detail > 0;
      dialog.close();
    }

    dialog.querySelector("[data-close-magnifier]").addEventListener("click", closeFromClick);
    dialog.addEventListener("click", event => {
      if (event.target === dialog) closeFromClick(event);
    });
    dialog.addEventListener("close", () => {
      if (dialog.open) return;
      const pointerDismissed = currentView?.pointerDismissed;
      currentView = null;
      observer.disconnect();
      window.removeEventListener("resize", scheduleOverlayRefresh);
      cancelAnimationFrame(markerRefresh);
      if (pointerDismissed) worldMap.blur();
      else worldMap.focus({preventScroll: true});
    });

    return {
      open(selection, formattedCoordinates) {
        const view = {projection: localProjection(selection.latitude, selection.longitude), places: []};
        currentView = view;
        const isCurrent = () => currentView === view && dialog.open;
        coordinates.textContent = formattedCoordinates;
        status.textContent = "";
        context.clearRect(0, 0, SIZE, SIZE);
        dialog.showModal();
        renderOverlays();
        for (const layer of worldMap.querySelectorAll("#mapHistoryLayer, #mapBackgroundLayer, #mapPulseLayer")) {
          observer.observe(layer, {childList: true});
        }
        window.addEventListener("resize", scheduleOverlayRefresh);
        const reportUnavailable = (message) => {
          if (isCurrent()) status.textContent += (status.textContent ? " " : "") + message;
        };
        drawTerrain(context, view.projection, version, isCurrent)
          .catch(() => reportUnavailable("Terrain is unavailable."));
        placesRequest ??= fetch(`${ASSETS}/places.json?v=${version}`).then(response => {
          if (!response.ok) throw new Error("Unable to load place names.");
          return response.json();
        }).catch(error => {
          placesRequest = null;
          throw error;
        });
        placesRequest.then(places => {
          if (!isCurrent()) return;
          view.places = places;
          renderOverlays();
        }).catch(() => reportUnavailable("Place names are unavailable."));
      },
    };
  };
})();
