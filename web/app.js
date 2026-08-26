/* Load the six payloads, wire the page, and say plainly what is not yet checked. */

import { createGlobe } from "./globe.js";
import { chooseLanguage, localise, t } from "./i18n.js";

async function load(name) {
  const response = await fetch(`./data/${name}.json`);
  if (!response.ok) throw new Error(`${name}.json: ${response.status}`);
  return response.json();
}

async function main() {
  const [strings, journey, land, places, provenance] = await Promise.all(
    ["strings", "journey", "land", "places", "provenance"].map(load),
  );

  chooseLanguage(strings);
  localise();

  renderProvenance(provenance);
  renderLegend(journey);
  renderItinerary(journey, places);

  const stage = document.querySelector("#stage");
  const toggle = document.querySelector("#rotate");
  const globe = createGlobe(stage, {
    land,
    journey,
    onIdleChange: () => setToggleLabel(toggle, globe),
  });
  setToggleLabel(toggle, globe);
  toggle.addEventListener("click", () => {
    globe.setPaused(!globe.isPaused());
    setToggleLabel(toggle, globe);
  });
}

/* WCAG 2.2.2 wants a mechanism to stop motion that runs for more than five seconds. A
 * prefers-reduced-motion query is a default, not a control, so this is a real button. */
function setToggleLabel(button, globe) {
  const paused = globe?.isPaused?.() ?? true;
  button.textContent = t(paused ? "globe.rotate.play" : "globe.rotate.pause");
  button.setAttribute("aria-pressed", String(paused));
}

/* Above the fold and not in a <details>. A reader deserves to know what has been checked
 * before they believe a dot, not after they go looking. */
function renderProvenance(record) {
  const box = document.querySelector("#provenance");
  const counts = record.places;
  const unlocated =
    (counts.by_reason?.none_found ?? 0) + (counts.by_reason?.not_queried ?? 0);

  const lines = [
    t("prov.line", {
      plotted: counts.plotted,
      total: counts.total,
      confirmed: counts.confirmed === 0 ? "None" : counts.confirmed,
    }),
    t("prov.doubtful", {
      n: counts.doubtful,
      located: counts.plotted,
      threshold: record.doubtful_below,
    }),
    t("prov.unlocated", { n: unlocated }),
    t("prov.rings"),
  ];
  for (const line of lines) {
    const p = document.createElement("p");
    p.textContent = line;
    box.append(p);
  }
}

/* Every mode gets its dash drawn, not just its colour named — that is what keeps the key
 * readable in greyscale, in print, and to a reader who does not separate these hues. */
function renderLegend(journey) {
  const list = document.querySelector("#legend-modes");
  const used = [...new Set(journey.legs.map((leg) => leg.primary_mode))];
  for (const mode of used) {
    const style = journey.transport_style[mode] || {};
    const item = document.createElement("li");
    item.innerHTML =
      `<svg width="46" height="12" aria-hidden="true">` +
      `<line x1="1" y1="6" x2="45" y2="6" stroke="var(${style.colour})" ` +
      `stroke-width="${style.width || 2}" stroke-linecap="round" ` +
      `stroke-dasharray="${(style.dash || []).join(" ")}"/></svg>`;
    const label = document.createElement("span");
    // The count, not every leg's phrasing run together — the itinerary below already
    // quotes each leg's own words, and repeating them here read as noise.
    const legs = journey.legs.filter((leg) => leg.primary_mode === mode);
    label.textContent = `${t(`mode.${mode}`)} — ${t("leg.count", { n: legs.length })}`;
    item.append(label);
    list.append(item);
  }
}

/* The itinerary as a real, visible list, built from the same journey.json the globe reads.
 * This is the screen-reader experience, the print experience, the "I would rather just read
 * it" experience, and what a search engine sees. It cannot disagree with the globe because
 * there is only one source for both. */
function renderItinerary(journey, places) {
  const list = document.querySelector("#itinerary");
  const named = new Map(places.places.map((place) => [place.key, place]));

  journey.nodes.forEach((node, position) => {
    const item = document.createElement("li");

    const day = document.createElement("span");
    day.className = "day-badge tabular";
    day.textContent = `day ${node.day}`;

    const name = document.createElement("span");
    name.className = "stop-name";
    name.textContent = node.name_in_text;

    item.append(day, name);

    if (node.name_changed && node.modern_name !== node.name_in_text) {
      const modern = document.createElement("span");
      modern.className = "renamed";
      modern.textContent = ` — ${t("place.renamed", {
        old: node.name_in_text,
        new: node.modern_name,
      })}`;
      item.append(modern);
    }

    const leg = journey.legs[position];
    if (leg) {
      const onward = document.createElement("p");
      onward.className = "onward";
      const via = leg.via_as_written.length
        ? ` ${t("leg.via", { places: leg.via_as_written.join(", ") })}.`
        : "";
      const waypoints = leg.waypoints
        .map((point) => named.get(point.key)?.name_in_text)
        .filter(Boolean);
      const drawn = waypoints.length ? ` Drawn through ${waypoints.join(", ")}.` : "";
      onward.textContent =
        `${leg.mode_as_written}, ${t("leg.days", { n: leg.days })}.${via}${drawn}`;
      item.append(onward);
    }
    list.append(item);
  });
}

main().catch((error) => {
  console.error(error);
  const box = document.querySelector("#provenance");
  if (box) box.textContent = `The data would not load: ${error.message}`;
});
