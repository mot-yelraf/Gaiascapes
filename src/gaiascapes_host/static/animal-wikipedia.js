/* Wikipedia companion for the audible recording.
 * Article text is rendered as text, keeping remote markup out of the dashboard.
 */
globalThis.animalWikipedia = (() => {
  const panel = document.getElementById("animalWikipedia");
  const button = document.getElementById("animalImageButton");
  const picture = document.getElementById("animalImage");
  const caption = document.getElementById("animalCaption");
  const credit = document.getElementById("animalImageCredit");
  const dialog = document.getElementById("animalArticle");
  const heading = document.getElementById("animalArticleTitle");
  const content = document.getElementById("animalArticleText");
  const source = document.getElementById("animalArticleSource");
  const cache = new Map();
  let current = "";
  let controller;
  let currentEvent = null;
  let pointerFrame = null;

  function drawPointer() {
    pointerFrame = null;
    const pointer = document.getElementById("animalLocationPointer");
    if (!pointer) return;
    pointer.setAttribute("hidden", "");
    panel.style.transform = "";
    if (panel.hidden || picture.hidden || !currentEvent) return;
    const west = panel.dataset.hemisphere === "west";
    const mapVisible = !document.getElementById("mapView").hidden;
    // Measure from the original grid position so repeated redraws cannot drift.
    if (mapVisible && matchMedia("(min-width: 601px)").matches) {
      const card = panel.getBoundingClientRect();
      const stage = document.querySelector("#mapView .map-stage").getBoundingClientRect();
      const gap = west ? stage.left - card.right : card.left - stage.right;
      const offset = Math.max(0, gap) / 2 * (west ? 1 : -1);
      panel.style.transform = `translateX(${offset}px)`;
    }
    const bounds = picture.getBoundingClientRect();
    const start = {x: west ? bounds.right : bounds.left, y: bounds.top + bounds.height / 2};
    const map = document.getElementById("worldMap");
    let end;
    if (mapVisible) {
      if (!Number.isFinite(currentEvent.longitude) || !Number.isFinite(currentEvent.latitude)
          || typeof projectCoordinates !== "function") return;
      const matrix = map.getScreenCTM();
      if (!matrix) return;
      const projected = projectCoordinates(currentEvent.longitude, currentEvent.latitude);
      const point = map.createSVGPoint();
      point.x = projected.x;
      point.y = projected.y;
      end = point.matrixTransform(matrix);
    } else {
      const location = document.querySelector('#dashboardView [data-status-field="background-location"]');
      if (!location) return;
      const target = location.getBoundingClientRect();
      end = {x: west ? target.left : target.right, y: target.top + target.height / 2};
    }
    const bend = start.x + (west ? 24 : -24);
    const path = `M ${start.x} ${start.y} C ${bend} ${start.y}, ${bend} ${end.y}, ${end.x} ${end.y}`;
    document.getElementById("animalLocationOutline").setAttribute("d", path);
    document.getElementById("animalLocationLine").setAttribute("d", path);
    const dot = document.getElementById("animalLocationDot");
    dot.setAttribute("cx", end.x);
    dot.setAttribute("cy", end.y);
    pointer.removeAttribute("hidden");
  }

  function refreshPointer() {
    if (pointerFrame === null && typeof requestAnimationFrame === "function") {
      pointerFrame = requestAnimationFrame(drawPointer);
    }
  }
  if (typeof ResizeObserver !== "undefined") {
    const observer = new ResizeObserver(refreshPointer);
    observer.observe(panel.closest("main"));
    observer.observe(panel);
    observer.observe(document.getElementById("worldMap"));
  }
  globalThis.addEventListener?.("resize", refreshPointer);
  globalThis.addEventListener?.("scroll", refreshPointer, true);
  picture.addEventListener("load", refreshPointer);

  function subject(event) {
    if (!["birdsong", "frog_calls", "whale_song", "dolphin_calls"].includes(event?.kind)) return "";
    const traits = event.traits || {};
    if (traits.wikipedia_title || traits.scientific_name) return traits.wikipedia_title || traits.scientific_name;
    const title = (traits.title || "").replace(/^File:/, "");
    if (event.kind === "birdsong") return title.match(/^([A-Z][a-z]+ [a-z]+)\b/)?.[1] || "Bird vocalization";
    if (event.kind === "frog_calls") return "Frog";
    // Mixed or unidentified recordings retain a group article instead of guessing a species.
    if (/blue and fin|whale and dolphin/i.test(title)) return "Cetacean vocalization";
    const marine = ["Indo-Pacific bottlenose dolphin", "Indo-Pacific humpback dolphin",
      "Pacific white-sided dolphin", "North Atlantic right whale", "Bottlenose dolphin",
      "Humpback whale", "Blue whale", "Fin whale", "Gray whale", "Killer whale",
      "Minke whale", "Sei whale", "Sperm whale"];
    if (/Amazonian river dolphin/i.test(title)) return "Amazon river dolphin";
    return marine.find(name => title.toLowerCase().startsWith(name.toLowerCase()))
      || (event.kind === "whale_song" ? "Whale" : "Dolphin");
  }

  function close() {
    if (dialog.open) dialog.close();
    button.setAttribute("aria-expanded", "false");
  }
  button.addEventListener("click", () => {
    dialog.showModal();
    button.setAttribute("aria-expanded", "true");
    content.scrollTop = 0;
  });
  dialog.addEventListener("click", event => {
    if (!event.target.closest("a")) close();
  });
  dialog.addEventListener("close", () => button.setAttribute("aria-expanded", "false"));

  async function update(event) {
    currentEvent = event;
    refreshPointer();
    const title = subject(event);
    const longitude = event?.longitude;
    const side = typeof longitude === "number" && longitude < 0 ? "west" : "east";
    panel.dataset.hemisphere = side;
    panel.closest("main").dataset.animalSide = side;
    if (title === current) return;
    current = title;
    controller?.abort();
    close();
    panel.hidden = !title;
    panel.closest("main").classList.toggle("has-animal", Boolean(title));
    picture.hidden = true;
    picture.onerror = null;
    picture.removeAttribute("src");
    credit.hidden = true;
    credit.textContent = "Image credits and license";
    credit.onclick = null;
    button.disabled = true;
    if (!title) return;
    caption.textContent = `${title} · Loading Wikipedia…`;
    const requestController = new AbortController();
    controller = requestController;
    const timeout = setTimeout(() => requestController.abort(), 12000);
    try {
      let page = cache.get(title);
      if (!page) {
        const query = new URLSearchParams({action: "query", format: "json", formatversion: "2",
          origin: "*", redirects: "1", titles: title, prop: "pageimages|extracts|pageprops",
          piprop: "thumbnail|name", pithumbsize: "640", pilicense: "free", explaintext: "1"});
        const response = await fetch(`https://en.wikipedia.org/w/api.php?${query}`, {signal: requestController.signal});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        page = data.query?.pages?.[0];
        if (!page || page.missing || page.pageprops?.disambiguation !== undefined || !page.extract) {
          throw new Error("No matching article");
        }
        cache.set(title, page);
        if (cache.size > 64) cache.delete(cache.keys().next().value);
      }
      if (current !== title || controller !== requestController) return;
      heading.textContent = page.title;
      content.textContent = page.extract;
      source.href = `https://en.wikipedia.org/wiki/${encodeURIComponent(page.title.replaceAll(" ", "_"))}`;
      caption.textContent = `${page.title} · Wikipedia`;
      button.disabled = false;
      button.setAttribute("aria-label", `Read Wikipedia: ${page.title}`);
      // Wikipedia serves images through both its upload and thumbnail hosts.
      if (["https://upload.wikimedia.org/", "https://thumb.wikimedia.org/"]
          .some(prefix => page.thumbnail?.source?.startsWith(prefix))) {
        picture.alt = page.title;
        picture.src = page.thumbnail.source;
        picture.hidden = false;
        picture.onerror = () => {
          picture.hidden = true;
          refreshPointer();
          caption.textContent = `${page.title} · Image unavailable · Read Wikipedia`;
        };
        credit.href = `https://en.wikipedia.org/wiki/${encodeURIComponent(`File:${page.pageimage}`)}`;
        credit.hidden = !page.pageimage;
      } else {
        caption.textContent = `${page.title} · No Wikipedia image · Read article`;
      }
    } catch (error) {
      if (current === title && controller === requestController) {
        caption.textContent = `${title} · Wikipedia unavailable. Click to retry.`;
        button.disabled = true;
        credit.textContent = "Retry Wikipedia";
        credit.href = "#animalWikipedia";
        credit.hidden = false;
        credit.onclick = () => { current = ""; update(event); return false; };
      }
    } finally {
      clearTimeout(timeout);
      refreshPointer();
    }
  }
  return {update, subject, refreshPointer};
})();
