/* The globe: a canvas for the sphere, an SVG overlay for the things you can click.
 *
 * Canvas for the base because the coastline is a few thousand vertices and redrawing it as
 * SVG means making the browser re-parse every path's `d` on every frame of a drag. Canvas
 * streams straight into path commands and touches no DOM at all.
 *
 * SVG for the stops because nine circles get :focus-visible, role, aria-label and a real
 * touch target for nothing, and moving nine `cx` attributes per frame costs nothing either.
 * So there is no hit-testing on the canvas anywhere.
 *
 * The drag moves two angles and pins the roll at zero. A minimal-rotation drag (versor) is
 * lovely on a free-tumbling globe and wrong on an atlas: it spins the third angle and tilts
 * the horizon. Same decision, same reason, as globe.shortest_rotation on the Python side.
 *
 * ---------------------------------------------------------------------------------------
 * What a test cannot check here, so look at the page:
 *   - Antarctica is white and the ocean is not. A backwards ring fills its own complement.
 *   - The far side of the globe has no clickable dots on it.
 *   - Dragging is smooth, and never rolls the horizon.
 *   - Auto-rotate stops the moment you touch it, and never starts under reduced motion.
 *   - Old-style figures in the prose; lining, tabular figures in the day column.
 * ---------------------------------------------------------------------------------------
 */

import {
  geoDistance,
  geoGraticule10,
  geoOrthographic,
  geoPath,
} from "./vendor/d3-geo-3.1.1.js";

const DEGREES_PER_SECOND = 6;
const IDLE_BEFORE_ROTATING = 20000;
const SPHERE = { type: "Sphere" };
const GRATICULE = geoGraticule10();

export function createGlobe(stage, { land, journey, onIdleChange }) {
  const canvas = stage.querySelector("canvas");
  const svg = stage.querySelector("svg");
  const context = canvas.getContext("2d");
  const projection = geoOrthographic().precision(0.4);
  const path = geoPath(projection, context);

  // Open on London's meridian, but tilted to the route's own mean latitude rather than to
  // London's. Centring on London itself points the globe at the Arctic and puts most of
  // the journey over the horizon: the wager is made at 51 degrees north and run at about
  // 34, so that is where the camera sits.
  const start = journey.nodes[0];
  const located = journey.nodes.filter((node) => node.lat !== null);
  const meanLat = located.reduce((sum, node) => sum + node.lat, 0) / located.length;
  let rotation = [-start.lon, -meanLat, 0];
  let size = 0;
  let spinning = false;
  let lastIdle = performance.now();
  let paused = prefersReducedMotion();

  const stops = mergeRepeats(journey.nodes).map(buildStop);
  for (const stop of stops) svg.append(stop.group);

  /* Canvas cannot read `var(--ocean)`, so the colours are resolved from the stylesheet at
   * draw time rather than written twice. This is also the whole of what a dark mode would
   * need later: change the CSS, change nothing here. */
  function colours() {
    const style = getComputedStyle(document.documentElement);
    const read = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
    return {
      ocean: read("--ocean", "#eae5d8"),
      land: read("--land", "#fffdf8"),
      landEdge: read("--land-edge", "#cfc9ba"),
      graticule: read("--graticule", "rgba(90,83,70,.16)"),
      sphereEdge: read("--sphere-edge", "#b5ad9b"),
      modes: Object.fromEntries(
        Object.entries(journey.transport_style).map(([mode, style_]) => [
          mode,
          read(style_.colour, "#5a5346"),
        ]),
      ),
    };
  }

  function resize() {
    const rect = stage.getBoundingClientRect();
    size = Math.max(240, Math.min(rect.width, rect.height));
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(size * ratio);
    canvas.height = Math.round(size * ratio);
    canvas.style.width = canvas.style.height = `${size}px`;
    // The backing store is in device pixels and everything else is in CSS pixels; setting
    // the transform once here is what keeps the rest of the file from knowing that.
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
    projection.translate([size / 2, size / 2]).scale(size / 2 - 8);
    draw();
  }

  function draw() {
    const ink = colours();
    projection.rotate(rotation);
    context.clearRect(0, 0, size, size);

    context.beginPath();
    path(SPHERE);
    context.fillStyle = ink.ocean;
    context.fill();

    context.beginPath();
    path(GRATICULE);
    context.strokeStyle = ink.graticule;
    context.lineWidth = 0.6;
    context.stroke();

    context.beginPath();
    path(land);
    context.fillStyle = ink.land;
    context.fill();
    context.strokeStyle = ink.landEdge;
    context.lineWidth = 0.7;
    context.stroke();

    for (const leg of journey.legs) {
      if (!leg.arc.length) continue;
      const style = journey.transport_style[leg.primary_mode] || {};
      context.beginPath();
      path({ type: "LineString", coordinates: leg.arc });
      context.strokeStyle = ink.modes[leg.primary_mode] || "#5a5346";
      context.lineWidth = style.width || 2;
      context.setLineDash(style.dash || []);
      context.lineCap = "round";
      context.stroke();
      context.setLineDash([]);
    }

    context.beginPath();
    path(SPHERE);
    context.strokeStyle = ink.sphereEdge;
    context.lineWidth = 1;
    context.stroke();

    placeStops();
  }

  /* With the roll pinned at zero, the centre of the visible hemisphere is exactly the
   * negated rotation — so "is this stop on the near side?" is one distance comparison. */
  function placeStops() {
    const centre = [-rotation[0], -rotation[1]];
    for (const stop of stops) {
      const node = stop.node;
      if (node.lat === null) {
        stop.group.classList.add("behind");
        continue;
      }
      const visible = geoDistance([node.lon, node.lat], centre) < Math.PI / 2;
      stop.group.classList.toggle("behind", !visible);
      if (!visible) continue;
      const [x, y] = projection([node.lon, node.lat]);
      stop.group.setAttribute("transform", `translate(${x.toFixed(1)},${y.toFixed(1)})`);
      // Labels flip to the inside near the rim so they never run off the disc.
      const flip = x > size * 0.72;
      stop.label.setAttribute("x", flip ? -12 : 12);
      stop.label.setAttribute("text-anchor", flip ? "end" : "start");
    }
  }

  /* Pointer events rather than d3-drag: about twenty lines, and pointer capture is what
   * makes a drag survive the cursor leaving the canvas. */
  let dragging = null;
  canvas.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY };
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add("dragging");
    interacted();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    // Degrees per pixel, scaled so a drag across the disc turns the globe about half round
    // whatever size it is being shown at.
    const perPixel = 180 / size;
    rotation = [
      rotation[0] + (event.clientX - dragging.x) * perPixel,
      clamp(rotation[1] - (event.clientY - dragging.y) * perPixel, -90, 90),
      0,
    ];
    dragging = { x: event.clientX, y: event.clientY };
    interacted();
    draw();
  });
  const release = (event) => {
    if (!dragging) return;
    dragging = null;
    canvas.classList.remove("dragging");
    canvas.releasePointerCapture?.(event.pointerId);
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);

  function interacted() {
    lastIdle = performance.now();
    if (spinning) {
      spinning = false;
      onIdleChange?.(false);
    }
  }

  let previous = performance.now();
  function frame(now) {
    const elapsed = now - previous;
    previous = now;
    const idle = now - lastIdle > IDLE_BEFORE_ROTATING;
    const wanted = idle && !paused && !document.hidden && !dragging;
    if (wanted !== spinning) {
      spinning = wanted;
      onIdleChange?.(spinning);
    }
    if (spinning) {
      // Eastward, the way Fogg went: the centre longitude increases, so the rotation
      // angle decreases.
      rotation = [rotation[0] - (DEGREES_PER_SECOND * elapsed) / 1000, rotation[1], 0];
      draw();
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  new ResizeObserver(resize).observe(stage);
  resize();

  return {
    redraw: draw,
    isPaused: () => paused,
    setPaused(value) {
      paused = value;
      if (!value) lastIdle = 0;
      interactedIfResuming(value);
    },
    turnTo(node) {
      rotation = [-node.lon, -node.lat, 0];
      interacted();
      draw();
    },
  };

  function interactedIfResuming(value) {
    if (value) interacted();
  }
}

/* London is index 0 and index 8 — the route is a cycle, and that is its shape rather than a
 * duplicate. Drawn as two dots they sit exactly on top of each other and the labels collide
 * into nonsense, so the repeats become one dot carrying both days. */
function mergeRepeats(nodes) {
  const byKey = new Map();
  for (const node of nodes) {
    const seen = byKey.get(node.key);
    if (seen) seen.days.push(node.day);
    else byKey.set(node.key, { ...node, days: [node.day] });
  }
  return [...byKey.values()];
}

function buildStop(node) {
  const svgNS = "http://www.w3.org/2000/svg";
  const group = document.createElementNS(svgNS, "g");
  group.setAttribute("class", `stop ${node.status === "confirmed" ? "" : "unchecked"}`);

  // An invisible larger circle underneath, so a 7px dot still has a 28px touch target.
  const hit = document.createElementNS(svgNS, "circle");
  hit.setAttribute("class", "hit");
  hit.setAttribute("r", "14");

  const pin = document.createElementNS(svgNS, "circle");
  pin.setAttribute("class", "pin");
  // The stop that is both the start and the finish is drawn larger, because it is.
  pin.setAttribute("r", node.days.length > 1 ? "7.5" : "5.5");

  const label = document.createElementNS(svgNS, "text");
  label.setAttribute("dy", "0.34em");
  label.append(document.createTextNode(node.name_in_text));
  const day = document.createElementNS(svgNS, "tspan");
  day.setAttribute("class", "day tabular");
  day.textContent = `  ${node.days.join(" · ")}`;
  label.append(day);

  group.append(hit, pin, label);
  return { node, group, label };
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}
