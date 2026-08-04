r"""Render the gazetteer as a map you can look at, which is how errors get caught.

A place resolved to the wrong continent is one glance on a map and invisible in a
spreadsheet row. So this plots everything — the doubtful, the unconfirmed and the
unresolved included — and draws each as what it is, rather than gating the map on a
review that has not happened yet.

Three decisions carry the whole thing.

**The route line follows node index, never a sort.** Ordering errors are exactly what the
map is for, and they show up as a zigzag only if the line is drawn in the order the
itinerary states.

**Longitudes are unwrapped eastward, then split.** Leaflet draws straight lines in Web
Mercator, so Yokohama at 139°E to San Francisco at −122° would draw *backwards across
Asia* — an artefact that looks exactly like the ordering error this map exists to detect.
:func:`unwrap_eastward` runs the route past 180° instead. But a line spanning a full 360°
makes Leaflet render the Americas three times over, so :func:`split_at_antimeridian` then
cuts it into pieces that each fit on one world.

**Never asked is not the same as nothing found.** A place the pipeline has not reached
yet and a place Wikidata was asked about and had nothing for are different facts — one
about this repository, one about the world — and reporting them together sends a reviewer
hunting for a gazetteer failure that never happened.

The page is self-contained apart from tiles: all the data is inline, so it opens from
``file://``. Tiles are the one thing it genuinely needs the network for at view time —
without them "wrong continent" is invisible, which is the entire point.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Template

__all__ = [
    "MapNode",
    "map_payload",
    "render_map",
    "split_at_antimeridian",
    "unwrap_eastward",
]

# Below this, a resolution is one a human should look at rather than take.
LOW_CONFIDENCE = 0.7

# How a kind is drawn. Colour carries the kind; radius and dash carry a second channel,
# because colour alone is not a channel everyone can read.
KIND_STYLE = {
    "node": {"colour": "--text-primary", "radius": 9, "dash": None, "fill": 0.9},
    "waypoint": {"colour": "--series-1", "radius": 7, "dash": None, "fill": 0.7},
    "micro": {"colour": "--series-3", "radius": 5, "dash": None, "fill": 0.6},
    "off_route": {"colour": "--text-muted", "radius": 4, "dash": "3,4", "fill": 0.0},
    "unknown": {"colour": "--diverge-warm", "radius": 6, "dash": "5,4", "fill": 0.2},
}


@dataclass(frozen=True, slots=True)
class MapNode:
    """One itinerary node as the map needs it: its place in the order, and where it is.

    Typed rather than a loose mapping because ``lon`` is arithmetic — it goes through
    :func:`unwrap_eastward` — and a dict of ``object`` would let a string reach that
    unnoticed.

    Attributes:
        index: Position in the route. The line is drawn in this order and never sorted.
        name: What to call it.
        lat: Latitude, or ``None`` when the node never resolved.
        lon: Longitude, likewise.
    """

    index: int
    name: str
    lat: float | None = None
    lon: float | None = None


def unwrap_eastward(lons: Sequence[float]) -> list[float]:
    """Make a westward-looking step eastward, so the route does not double back.

    Fogg travels east the whole way round. Any step that appears to go west by more than
    half the world is the antimeridian, not a change of direction — so it gains 360°.

    Args:
        lons: Longitudes in route order.

    Returns:
        The same points, monotonically eastward where the original wrapped.

    Contract:
        - The first value is unchanged.
        - No consecutive step decreases by more than 180°.
        - Every value differs from its input by a whole multiple of 360.

    Examples:
        Yokohama to San Francisco, which would otherwise draw across Asia:

        >>> unwrap_eastward([139.6, -122.4])
        [139.6, 237.6]

        A route that never crosses the line is left alone:

        >>> unwrap_eastward([-0.1, 32.5, 72.9])
        [-0.1, 32.5, 72.9]
    """
    if not lons:
        return []
    out = [lons[0]]
    for value in lons[1:]:
        # Compared against the last *emitted* point, not the last input one. Comparing
        # against the input was wrong for a route that wraps more than once — which this
        # one does not, so only a property test was ever going to find it.
        current = value
        while current < out[-1] - 180.0:
            current += 360.0
        out.append(round(current, 6))
    return out


def split_at_antimeridian(
    points: Sequence[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    r"""Cut an unwrapped route into pieces that each fit on one world.

    :func:`unwrap_eastward` runs the route past 180° so it never doubles back, which is
    right for knowing the direction and wrong for drawing: a line spanning 360° makes
    Leaflet render the Americas three times over. So the unwrapped line is cut wherever it
    crosses the antimeridian and every point is folded back into ``[-180, 180]``.

    One leg of a circumnavigation has to cross the edge of any flat map. Splitting makes
    that a line leaving the right edge and entering at the left, which is what a Mercator
    map honestly does — as against a line drawn backwards across Asia, which is the
    artefact that looks exactly like the ordering error this map exists to find.

    Args:
        points: ``(lat, lon)`` in route order, longitudes already unwrapped.

    Returns:
        One list of points per piece, each with longitudes in ``[-180, 180]``.

    Contract:
        - Every longitude in the result is within ``[-180, 180]``.
        - A route that never crosses comes back as a single piece.
        - The crossing latitude is interpolated, not copied from either end.
        - Never raises.

    Examples:
        Yokohama to San Francisco, unwrapped to 237.6, crosses once:

        >>> pieces = split_at_antimeridian([(35.4, 139.6), (37.8, 237.6)])
        >>> [len(piece) for piece in pieces]
        [2, 2]
        >>> round(pieces[0][-1][1]), round(pieces[1][0][1])
        (180, -180)

        A route inside one world is left alone:

        >>> split_at_antimeridian([(51.5, -0.1), (30.0, 32.5)])
        [[(51.5, -0.1), (30.0, 32.5)]]
    """

    def wrap(lon: float) -> float:
        return round(((lon + 180.0) % 360.0) - 180.0, 6)

    if not points:
        return []
    pieces: list[list[tuple[float, float]]] = [[(points[0][0], wrap(points[0][1]))]]
    for (lat_a, lon_a), (lat_b, lon_b) in zip(points, points[1:], strict=False):
        # Each crossing is an odd multiple of 180 strictly between the two longitudes.
        edges = [
            edge
            for edge in _edges_between(lon_a, lon_b)
            if lon_a < edge < lon_b or lon_b < edge < lon_a
        ]
        for edge in edges:
            share = (edge - lon_a) / (lon_b - lon_a)
            lat_at = round(lat_a + share * (lat_b - lat_a), 6)
            leaving = 180.0 if lon_b > lon_a else -180.0
            pieces[-1].append((lat_at, leaving))
            pieces.append([(lat_at, -leaving)])
        pieces[-1].append((lat_b, wrap(lon_b)))
    return [piece for piece in pieces if len(piece) > 1]


def _edges_between(lon_a: float, lon_b: float) -> list[float]:
    """The antimeridian crossings a step passes, in the order it passes them."""
    low, high = sorted((lon_a, lon_b))
    first = math.floor((low + 180.0) / 360.0)
    last = math.ceil((high + 180.0) / 360.0)
    edges = [180.0 + 360.0 * turn for turn in range(first, last + 1)]
    return edges if lon_b >= lon_a else list(reversed(edges))


def map_payload(
    rows: Sequence[Mapping[str, str]],
    nodes: Sequence[MapNode],
) -> dict[str, object]:
    """Assemble everything the page needs, inline.

    Args:
        rows: The review table's rows, as read from ``places.csv``.
        nodes: The route nodes, in index order, each with a ``name`` and its coordinates
            where known.

    Returns:
        The payload.

    Contract:
        - ``route`` is in node-index order, and ``segments`` is the same line cut so
          each piece fits on one world.
        - A ``local`` place is listed but never given a pin: it has no coordinate of its
          own, and plotting one would be the lie the kind exists to prevent.
        - Every row appears in exactly one of ``places``, ``locals``, ``unresolved`` or
          ``unqueried`` — and the last two are different states, not one.
    """
    places, locals_, unresolved, unqueried = [], [], [], []
    for row in rows:
        kind = row.get("corrected_kind") or row.get("kind") or "unknown"
        entry = {
            "key": row["key"],
            "name": row.get("name_in_text", row["key"]),
            "kind": kind,
            "modern": row.get("modern_name", ""),
            "renamed": bool(row.get("name_changed", "").strip()),
            "qid": row.get("qid", ""),
            "country": row.get("country", ""),
            "type": row.get("entity_type", ""),
            "confidence": float(row["confidence"]) if row.get("confidence") else None,
            "candidates": int(row.get("n_gazetteer_candidates") or 0),
            "why": row.get("gazetteer_why") or row.get("why", ""),
            "uses": row.get("used_as", ""),
            "chapter": row.get("first_chapter", ""),
            "confirmed": bool(row.get("confirmed", "").strip()),
            # A place that puts someone somewhere, as against one the book merely names.
            # The 145 merely-named ones are spec tier +3 and get their own layer, so a
            # review can look at the ones that move the map and nothing else.
            "positional": ("on_stage" in row.get("used_as", ""))
            or ("visited" in row.get("used_as", "")),
        }
        if kind == "local":
            locals_.append(entry)
            continue
        lat, lon = row.get("lat", "").strip(), row.get("lon", "").strip()
        if lat and lon:
            places.append({**entry, "lat": float(lat), "lon": float(lon)})
        elif row.get("gazetteer_source", "").strip():
            # Asked, and the answer was nothing. A fact about the world.
            unresolved.append(entry)
        else:
            # Never asked. A fact about how far the pipeline has got, and reporting it
            # as a gazetteer failure sends a reviewer hunting for one that never happened.
            unqueried.append(entry)

    # Unpacked to concrete floats here rather than filtered in place, so that "this node
    # has coordinates" is a fact about the values from now on and not a condition a reader
    # has to carry forward.
    known: list[tuple[int, str, float, float]] = [
        (node.index, node.name, node.lat, node.lon)
        for node in nodes
        if node.lat is not None and node.lon is not None
    ]
    lons = unwrap_eastward([lon for _, _, _, lon in known])
    route = [
        {
            "index": index,
            "name": name,
            "lat": lat,
            "lon": ((lon + 180.0) % 360.0) - 180.0,
        }
        for (index, name, lat, _), lon in zip(known, lons, strict=True)
    ]
    segments = split_at_antimeridian(
        [(lat, lon) for (_, _, lat, _), lon in zip(known, lons, strict=True)]
    )

    return {
        "route": route,
        "segments": segments,
        "places": places,
        "locals": locals_,
        "unresolved": unresolved,
        "unqueried": unqueried,
        "counts": {
            "total": len(rows),
            "plotted": len(places),
            "local": len(locals_),
            "unresolved": len(unresolved),
            "unqueried": len(unqueried),
            "confirmed": sum(1 for entry in places if entry["confirmed"]),
            "doubtful": sum(
                1
                for entry in places
                if entry["confidence"] is not None
                and entry["confidence"] < LOW_CONFIDENCE
            ),
        },
    }


def render_map(
    payload: Mapping[str, object], *, title: str = "verne80 — places"
) -> str:
    """Render the self-contained review page.

    Uses :class:`string.Template`, **not** ``str.format`` — the template is full of
    ``{``
    from CSS and JavaScript and ``.format`` would raise on every one of them.

    Args:
        payload: From :func:`map_payload`.
        title: The page title.

    Returns:
        The HTML.

    Contract:
        - The result embeds the data; nothing is fetched at build time.
        - Every unconfirmed place is marked.
    """
    return Template(MAP_TEMPLATE).safe_substitute(
        title=title,
        payload=json.dumps(payload, ensure_ascii=False),
        kind_style=json.dumps(KIND_STYLE),
        low_confidence=LOW_CONFIDENCE,
    )


MAP_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>$title</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  :root {
    color-scheme: light;
    --surface-1: #fcfcfb; --plane: #f9f9f7;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --border: rgba(11,11,11,.10);
    --series-1: #2a78d6; --series-3: #1baf7a; --series-4: #eda100;
    --diverge-warm: #e34948;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --surface-1: #17181a; --plane: #101113;
      --text-primary: #f2f2f0; --text-secondary: #b8b7b2; --text-muted: #86857f;
      --border: rgba(242,242,240,.14);
      --series-1: #6ea8f0; --series-3: #4fc79a; --series-4: #f0bd4a;
      --diverge-warm: #f0716f;
    }
  }
  * { box-sizing: border-box; }
  body { margin:0; background: var(--plane); color: var(--text-primary);
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 60px; }
  h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
  h2 { font-size: 1.1rem; margin: 2rem 0 .25rem; }
  p.sub { color: var(--text-secondary); max-width: 74ch; margin: .25rem 0 1rem; }
  #map { height: 68vh; min-height: 460px; border: 1px solid var(--border);
         border-radius: 6px; background: var(--surface-1); }
  .counts { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; margin: 0 0 1rem;
            color: var(--text-secondary); font-size: .9rem; }
  .counts b { color: var(--text-primary); }
  .pop { font: 13px/1.45 system-ui, sans-serif; min-width: 250px; }
  .pop h3 { margin: 0 0 .35rem; font-size: 14px; }
  .pop table { border-collapse: collapse; }
  .pop td { padding: 1px 0; vertical-align: top; }
  .pop td:first-child { color: var(--text-muted); padding-right: .6rem;
                        white-space: nowrap; }
  .pop .warn { color: var(--diverge-warm); }
  .tag { display:inline-block; padding:0 .35rem; border:1px solid var(--border);
         border-radius: 3px; font-size: 11px; color: var(--text-secondary); }
  ul.locals { columns: 3; font-size: .85rem; color: var(--text-secondary);
              padding-left: 1.1rem; }
  .leaflet-container { font: inherit; background: var(--plane); }
  .leaflet-control-layers, .leaflet-bar a { background: var(--surface-1);
    color: var(--text-primary); border-color: var(--border); }
  .leaflet-control-attribution { background: var(--surface-1) !important;
    color: var(--text-muted) !important; font-size: .7rem; }
  footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border);
           color: var(--text-muted); font-size: .8rem; }
  .node-label { color: var(--text-primary); font: 700 11px system-ui, sans-serif;
                text-align: center; text-shadow: 0 0 3px var(--plane); }
</style>
</head>
<body>
<main>
<h1>Where the gazetteer put things</h1>
<p class="sub">Every pin is a guess until you say otherwise. Click one; if it is wrong,
open <code>data/review/places.csv</code>, find the row by its <code>key</code>, put the
right Wikidata QID in <code>corrected_qid</code> (or the right <code>corrected_kind</code>),
write <code>y</code> in <code>confirmed</code> when it is right, and re-run
<code>uv run python scripts/07_gazetteer.py</code>. Nothing you type is overwritten, and
re-running costs nothing — the answers are cached. Pins with a red ring are the ones
nobody has checked yet; the layer switch at the top right turns each group off.</p>

<div class="counts" id="counts"></div>
<div id="map"></div>

<h2>Interiors that travel with the party</h2>
<p class="sub">These have no coordinate of their own — a station is inside whichever city
the party is in, and a ship's position is the leg it is on. They are listed rather than
plotted, because putting a pin on one would be exactly the mistake the category exists to
prevent.</p>
<ul class="locals" id="locals"></ul>

<h2>Named, but nowhere</h2>
<p class="sub">Wikidata was asked about these and had no entity with coordinates under the
name. Some are the translator's inventions — Kholby is where the railway ends and the
elephant begins, and there is no such place.</p>
<ul class="locals" id="unresolved"></ul>

<h2>Not looked up yet</h2>
<p class="sub">Nobody has asked about these. That is a fact about how far the pipeline has
got, not about whether the place exists — so they are kept apart from the section above,
which would otherwise send you hunting for a gazetteer failure that never happened.</p>
<ul class="locals" id="unqueried"></ul>

<footer>
Wikidata (CC0 1.0) · map data © OpenStreetMap contributors (ODbL) ·
text: Project Gutenberg #103 · generated by <code>scripts/07_gazetteer.py</code>
</footer>
</main>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = $payload;
const KIND_STYLE = $kind_style;
const LOW = $low_confidence;

// Leaflet cannot take `var()` colours, so each one is resolved through a probe element.
// Straight out of the house map idiom; it must run after the body exists.
const resolve = (names) => {
  const probe = document.createElement("div");
  document.body.appendChild(probe);
  const out = {};
  for (const name of names) {
    probe.style.color = `var(${name})`;
    out[name] = getComputedStyle(probe).color;
  }
  probe.remove();
  return out;
};
const COLOURS = resolve([...new Set(Object.values(KIND_STYLE).map(s => s.colour)),
                         "--text-primary", "--diverge-warm"]);

// One Earth. noWrap stops the tiles repeating and maxBounds stops you panning into a
// copy that is not there — between them the Americas appear once, as they should.
const WORLD = L.latLngBounds([[-85, -180], [85, 180]]);
const map = L.map("map", {
  worldCopyJump: false, scrollWheelZoom: false,
  maxBounds: WORLD, maxBoundsViscosity: 0.9, minZoom: 1,
});
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18, noWrap: true, bounds: WORLD,
  attribution: '&copy; <a href="https://osm.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

// Node index order, never sorted: a route drawn in the wrong order is precisely the
// error this map exists to show, and sorting would hide it. The line arrives already cut
// at the antimeridian, so the Pacific leg leaves the right edge and enters at the left —
// which is what one leg of a circumnavigation does to any flat map.
const routeLine = L.layerGroup(
  DATA.segments.map(seg => L.polyline(seg,
    { color: COLOURS["--text-primary"], weight: 3, opacity: .75 }))
).addTo(map);
for (const node of DATA.route) {
  L.marker([node.lat, node.lon], {
    icon: L.divIcon({ className: "node-label", html: String(node.index),
                      iconSize: [16, 16] }),
  }).addTo(map).bindPopup(`<div class="pop"><h3>${node.name}</h3>
    <table><tr><td>route node</td><td>${node.index}</td></tr></table></div>`);
}

const escapeHtml = (s) => String(s ?? "").replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function popup(p) {
  const rows = [];
  const add = (k, v, cls) => { if (v) rows.push(
    `<tr><td>${k}</td><td class="${cls || ""}">${v}</td></tr>`); };
  add("modern name", escapeHtml(p.modern) + (p.renamed ? " — renamed" : ""));
  if (p.qid) add("Wikidata",
    `<a href="https://www.wikidata.org/wiki/${p.qid}" target="_blank">${p.qid} &#8599;</a>`);
  add("coordinates", `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`);
  add("country", [p.country, p.type].filter(Boolean).map(escapeHtml).join(" · "));
  add("chapters", `first used in ${escapeHtml(p.chapter)} (${escapeHtml(p.uses)})`);
  if (p.confidence !== null) add("confidence",
    `${p.confidence.toFixed(2)}${p.candidates > 1 ? ` of ${p.candidates} candidates` : ""}`,
    p.confidence < LOW ? "warn" : "");
  add("why", escapeHtml(p.why));
  add("checked", p.confirmed ? "yes" : "not yet", p.confirmed ? "" : "warn");
  return `<div class="pop"><h3>${escapeHtml(p.name)}
    <span class="tag">${p.kind}</span></h3><table>${rows.join("")}</table></div>`;
}

const layers = {};
for (const [kind, style] of Object.entries(KIND_STYLE)) layers[kind] = L.layerGroup();
const doubtful = L.layerGroup();
const unchecked = L.layerGroup();
// The book name-drops far more geography than Fogg visits; conflating the two turns the
// route into mush, so they get a layer you can switch off.
const mentioned = L.layerGroup();

for (const p of DATA.places) {
  const style = KIND_STYLE[p.kind] || KIND_STYLE.unknown;
  const colour = COLOURS[style.colour];
  const conf = p.confidence === null ? 0.5 : p.confidence;
  const marker = L.circleMarker([p.lat, p.lon], {
    radius: style.radius, color: colour, weight: 2,
    dashArray: conf < LOW ? "4,3" : style.dash,
    fillColor: colour, fillOpacity: 0.15 + 0.7 * style.fill * conf,
  }).bindPopup(popup(p));
  (layers[p.kind] || layers.unknown).addLayer(marker);

  if (p.confidence !== null && p.confidence < LOW) {
    doubtful.addLayer(L.circleMarker([p.lat, p.lon],
      { radius: style.radius + 5, color: COLOURS["--diverge-warm"], weight: 1,
        fill: false, dashArray: "2,3" }));
  }
  // The ring is the progress bar: turn this layer off and watch the map get quieter.
  if (!p.positional) {
    mentioned.addLayer(L.circleMarker([p.lat, p.lon],
      { radius: 2, color: COLOURS["--text-muted"], weight: 1, fill: true,
        fillOpacity: .8 }));
  }
  if (!p.confirmed) {
    unchecked.addLayer(L.circleMarker([p.lat, p.lon],
      { radius: style.radius + 2, color: COLOURS["--diverge-warm"], weight: 1,
        opacity: .55, fill: false }));
  }
}

const overlays = { "route": routeLine };
for (const [kind, group] of Object.entries(layers)) {
  overlays[`${kind} (${group.getLayers().length})`] = group;
  if (kind !== "off_route") group.addTo(map);
}
overlays[`mentioned only (${mentioned.getLayers().length})`] = mentioned.addTo(map);
overlays[`low confidence (${doubtful.getLayers().length})`] = doubtful.addTo(map);
overlays[`unchecked (${unchecked.getLayers().length})`] = unchecked.addTo(map);
L.control.layers(null, overlays, { collapsed: false, position: "topright" }).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

map.invalidateSize();
const drawn = L.featureGroup(routeLine.getLayers());
map.fitBounds(drawn.getBounds().pad(0.05), { animate: false, maxZoom: 5 });

const c = DATA.counts;
document.getElementById("counts").innerHTML = [
  [`<b>${c.total}</b> place names`], [`<b>${c.plotted}</b> plotted`],
  [`<b>${c.local}</b> interiors`], [`<b>${c.unresolved}</b> with no coordinate`],
  [`<b>${c.unqueried}</b> not looked up yet`],
  [`<b>${c.doubtful}</b> below ${LOW} confidence`], [`<b>${c.confirmed}</b> checked`],
].map(x => `<span>${x}</span>`).join("");

const list = (id, items) => document.getElementById(id).innerHTML =
  items.map(p => `<li>${escapeHtml(p.name)}</li>`).join("");
list("locals", DATA.locals);
list("unresolved", DATA.unresolved);
list("unqueried", DATA.unqueried);
</script>
</body>
</html>
"""
