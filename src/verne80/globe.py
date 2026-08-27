r"""What the globe reads: the route, the places, the chapters, and the counts.

An orthographic globe wants different things from a Mercator map, and the differences
are load-bearing enough to be worth naming.

**No antimeridian.** ``d3.geoOrthographic`` clips at the horizon, so there is no map
edge for a circumnavigation to fall off. :func:`~verne80.reviewmap.unwrap_eastward` and
:func:`~verne80.reviewmap.split_at_antimeridian` are Web Mercator artefacts and are
deliberately not reused here — worth saying out loud, because the failure would be
silent. ``geoOrthographic`` accepts an unwrapped longitude of ``237.6`` and renders it
correctly, since it wraps mod 360; the machinery would not break, it would simply sit
there being a Mercator assumption in a projection that has no edge.

**``[lon, lat]``, everywhere.** The rest of this package passes ``(lat, lon)`` tuples
about; GeoJSON and d3 both want ``[lon, lat]``. The flip happens once, in
:func:`to_geojson_point`, and never inline. It is the single likeliest bug in this file
and it gets a named function and a doctest rather than vigilance.

**The arcs are great circles, and the page says so.** Fogg's table names eight legs and
the days each is budgeted; it does not trace a path. So the arc between two stops is the
shortest path over a sphere, which is honest about being schematic and wrong about being
a route. The distances are not small: leg 0's arc passes about 450 km from Paris,
700 km from Mont Cenis and 360 km from Brindisi — the three places the table itself
names — and leg 1's midpoint is over central Arabia, some 1,700 km from the Aden the
steamer coaled at. Each leg carries ``arc_is``, so replacing a schematic arc with a
surveyed one is a change to the data and not to any code. ``via_as_written`` travels
as text and never as a bend in the line —
bending leg 0 through Brindisi would assert a straight run from Mont Cenis to Brindisi,
which is more invention than the straight line, not less.

**A number that must not become a percentage.** ``along`` orders pins along a leg. It
is not distance, speed or progress, and :class:`~verne80.position.RoutePoint` says so
at length. It reaches the payload as the input to an interpolation and never as a
figure the page prints.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from verne80.normalize import place_key
from verne80.people import Cast, Folded
from verne80.position import PlaceKind, PositionSource, Track
from verne80.review import is_confirmed, is_rejected
from verne80.reviewmap import LOW_CONFIDENCE
from verne80.route import RouteSpine
from verne80.schema import ChapterExtraction, TransportMode

# A decoded JSON object, or one of this module's own payloads on its way back in. `Any`
# is the honest annotation: these are nested heterogeneous structures whose shape is
# asserted by the tests that read them, not by a type a checker could verify here.
JsonObject = Mapping[str, Any]

__all__ = [
    "ARC_SAMPLES",
    "TIER_BY_KIND",
    "TRANSPORT_STYLE",
    "DRIFT_RATIO",
    "chapters_by_place",
    "chapters_payload",
    "great_circle",
    "great_circle_km",
    "interpolate_great_circle",
    "journey_payload",
    "places_payload",
    "provenance",
    "shortest_rotation",
    "to_geojson_point",
]

# Points per leg. The longest leg is Yokohama to San Francisco, about 8,300 km, so 64
# samples put a waypoint within ~130 km of where it belongs — finer than the radius of
# the dot that marks it. d3 re-samples adaptively between these anyway; the count
# governs where a pin can land and how finely a partial leg can be drawn, not how
# smooth it looks.
ARC_SAMPLES = 64

# Below this, a resolution is one a human should look at rather than take. Imported
# rather than restated so the QA map and the public globe cannot come to disagree about
# what "doubtful" means.
DOUBTFUL_BELOW = LOW_CONFIDENCE

# How far a waypoint may sit from the leg it claims to be on, as a multiple of that
# leg's own length, before it is treated as contradicting the curation rather than
# merely being missed by a schematic arc.  The arcs are great circles, so a waypoint on
# a real sea lane is legitimately a long way off one: Singapore is 2,422 km from the
# Calcutta-Hong Kong arc because the steamer went round the Malay peninsula and the
# great circle cuts across Indochina. Measuring the drift against the leg's length
# rather than in kilometres makes the test scale-free, and the observed values fall
# either side of a real gap — every honest waypoint is at 0.84 of its leg or below, and
# Queenstown is at 3.3, because the gazetteer put it in New Zealand.  This number
# decides what is drawn, so it is a parameter with its default stated here rather than
# a literal buried in a comparison.
DRIFT_RATIO = 1.0

# Mean Earth radius (IUGG). Distances here are only ever compared with one another, so
# the choice of radius changes no decision — it is named rather than inlined so that
# nobody has to wonder whether 6371 was a considered figure or a remembered one.
EARTH_RADIUS_KM = 6371.0088

# The checkout this file sits in — ``src/verne80/globe.py``, so two levels up from the
# package. Used only to write inputs into the provenance record as the repository names
# them; see :func:`_repo_relative`. Installed as a wheel there is no checkout above the
# package and the path lands in site-packages, which is why that helper degrades to the
# file name rather than trusting this.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# How a leg is drawn. Colour carries the mode; the dash pattern carries it a second
# time, because colour alone is not a channel everyone can read and this page may be
# printed in grey. The legend prints the dash, so a reader with no colour at all still
# has the key. Hues are kmdb_dashboard's categorical family, so two Crow pieces share
# one palette.
TRANSPORT_STYLE: dict[str, dict[str, object]] = {
    TransportMode.STEAMER.value: {
        "colour": "--mode-sea",
        "dash": [],
        "width": 2.5,
        "glyph": "~",
    },
    TransportMode.RAILWAY.value: {
        "colour": "--mode-rail",
        "dash": [6, 4],
        "width": 2.5,
        "glyph": "=",
    },
    TransportMode.ELEPHANT.value: {
        "colour": "--mode-beast",
        "dash": [1, 5],
        "width": 3.0,
        "glyph": "●",
    },
    TransportMode.SLEDGE.value: {
        "colour": "--mode-ice",
        "dash": [2, 3, 8, 3],
        "width": 2.5,
        "glyph": "▲",
    },
    TransportMode.CARRIAGE.value: {
        "colour": "--mode-road",
        "dash": [4, 3, 1, 3],
        "width": 2.0,
        "glyph": "·",
    },
    TransportMode.ON_FOOT.value: {
        "colour": "--mode-foot",
        "dash": [1, 4],
        "width": 1.5,
        "glyph": "·",
    },
    TransportMode.OTHER.value: {
        "colour": "--mode-other",
        "dash": [2, 6],
        "width": 1.5,
        "glyph": "?",
    },
}

# Which layer a kind belongs to. `local` and `off_route` are absent on purpose: neither
# has a position of its own, so neither is ever given a pin. A station is inside
# wherever the party already is, and India is a country rather than a place you stand.
TIER_BY_KIND: dict[str, str] = {
    PlaceKind.NODE.value: "itinerary",
    PlaceKind.WAYPOINT.value: "itinerary",
    PlaceKind.MICRO.value: "interior",
    PlaceKind.UNKNOWN.value: "named",
}

# A waypoint whose coordinates put it nowhere near its own leg. Named rather than typed
# out three times, because the payload, the count and the run log have to agree on it.
_CONTRADICTS = "contradicts_its_leg"

# Kinds that are listed but never plotted, and the reason each is held back.
_NOT_A_POSITION = {
    # "floating", not "interior": the `interior` tier is `micro`, a fixed inside with a
    # known parent — the Reform Club is in London, always. A `local` one is an inside
    # whose parent is wherever the party has got to, and "station" is six different
    # places across six chapters. Two ideas one word apart is how they end up merged.
    PlaceKind.LOCAL.value: "floating_interior",
    PlaceKind.OFF_ROUTE.value: "off_route",
}


def to_geojson_point(lat: float, lon: float) -> list[float]:
    """Turn this package's ``(lat, lon)`` into GeoJSON's ``[lon, lat]``.

    A one-line function because the flip is the likeliest error in the whole export and
    a named call site can be grepped, tested and reviewed where an inline reversal
    cannot.

    Args:
        lat: Latitude in degrees.
        lon: Longitude in degrees.

    Returns:
        ``[lon, lat]``, the order GeoJSON and d3 both use.

    Examples:
        London, which is just west of Greenwich and well north of the equator:

        >>> to_geojson_point(51.50722, -0.1275)
        [-0.1275, 51.50722]
    """
    return [float(lon), float(lat)]


def interpolate_great_circle(
    start: Sequence[float], end: Sequence[float], fraction: float
) -> list[float]:
    """A point a given fraction of the way along the great circle between two points.

    The endpoints are returned verbatim rather than recomputed, so an arc meets the pins
    it was drawn between exactly instead of within a rounding error of them.

    Args:
        start: ``[lon, lat]`` in degrees.
        end: ``[lon, lat]`` in degrees.
        fraction: ``0.0`` at ``start``, ``1.0`` at ``end``.

    Returns:
        ``[lon, lat]`` in degrees, longitude in ``[-180, 180]``.

    Contract:
        - ``fraction`` of ``0.0`` returns ``start`` and ``1.0`` returns ``end``,
          exactly.
        - Never raises. Coincident points return that point; antipodal points, which
          have no unique great circle, take a deterministic one rather than dividing by
          zero.

    Examples:
        Halfway from London to Suez is over the Adriatic, far north of any sea route
        — a great circle bends poleward on a north-up map:

        >>> interpolate_great_circle([-0.1275, 51.50722], [32.53333, 29.96667], 0.5)
        [18.951111, 41.874104]

        The ends are the ends:

        >>> interpolate_great_circle([-0.1275, 51.50722], [32.53333, 29.96667], 0.0)
        [-0.1275, 51.50722]
    """
    if fraction <= 0.0:
        return [float(start[0]), float(start[1])]
    if fraction >= 1.0:
        return [float(end[0]), float(end[1])]

    first = _to_vector(start)
    second = _to_vector(end)
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second, strict=True))))
    omega = math.acos(dot)
    sine = math.sin(omega)

    if sine < 1e-9:
        if dot > 0.0:
            # The same point twice. Every fraction of no distance is that point.
            return [float(start[0]), float(start[1])]
        # Antipodal: every great circle through both is equally short, so there is no
        # right answer, only a consistent one. Take the pole furthest from `first` as
        # the third point and swing through it. No leg of this route is antipodal; this
        # exists because a property test will generate one and "never raises" is the
        # house rule.
        second = _orthogonal(first)
        omega = math.pi / 2.0
        sine = 1.0
        fraction *= 2.0

    scale_first = math.sin((1.0 - fraction) * omega) / sine
    scale_second = math.sin(fraction * omega) / sine
    blended = tuple(
        scale_first * a + scale_second * b for a, b in zip(first, second, strict=True)
    )
    return _to_degrees(blended)


def great_circle(
    start: Sequence[float], end: Sequence[float], samples: int = ARC_SAMPLES
) -> list[list[float]]:
    """Sample the great circle between two points, evenly in fraction.

    Built by calling :func:`interpolate_great_circle` rather than by inlining the same
    arithmetic, so a waypoint placed at ``along`` lands on the drawn line by
    construction and not by two implementations agreeing.

    Args:
        start: ``[lon, lat]`` in degrees.
        end: ``[lon, lat]`` in degrees.
        samples: How many points, at least two. Default :data:`ARC_SAMPLES`.

    Returns:
        ``samples`` points of ``[lon, lat]``, from ``start`` to ``end``.

    Contract:
        - The first point is ``start`` and the last is ``end``, exactly.
        - ``great_circle(a, b, n)[k]`` equals
          ``interpolate_great_circle(a, b, k / (n - 1))``.
        - Never raises; ``samples`` below two is raised to two.

    Examples:
        >>> arc = great_circle([-0.1275, 51.50722], [32.53333, 29.96667], 3)
        >>> arc[0], arc[-1]
        ([-0.1275, 51.50722], [32.53333, 29.96667])
        >>> arc[1]
        [18.951111, 41.874104]
    """
    count = max(2, samples)
    last = count - 1
    return [
        interpolate_great_circle(start, end, index / last) for index in range(count)
    ]


def shortest_rotation(current: float, target: float) -> float:
    """How far to turn, taking the short way round.

    The globe is rotated by two angles with the roll pinned at zero, so stepping
    between chapters means interpolating longitude and latitude separately. Longitude
    wraps, and a naive subtraction sends the globe 340 degrees east rather than 20 west
    — which does not look like a bug, it looks like the page is showing off.

    Slerping the great circle between the two viewpoints instead, and deriving the
    rotation from that, spins the third angle and rolls the horizon. For an atlas that
    should read north-up, two angles is the correct choice rather than the lazy one.

    Args:
        current: Where the globe is, in degrees.
        target: Where it should be, in degrees.

    Returns:
        The signed change in degrees, in ``[-180, 180)``.

    Contract:
        - ``current + shortest_rotation(current, target)`` equals ``target`` mod 360.
        - The magnitude never exceeds 180.
        - Never raises.

    Examples:
        Crossing the date line the short way, not the long way:

        >>> shortest_rotation(170.0, -170.0)
        20.0
        >>> shortest_rotation(-170.0, 170.0)
        -20.0

        And staying put is no rotation at all:

        >>> shortest_rotation(45.0, 45.0)
        0.0
    """
    return (target - current + 540.0) % 360.0 - 180.0


def great_circle_km(start: Sequence[float], end: Sequence[float]) -> float:
    """How far apart two points are over the surface, in kilometres.

    Used to ask whether a waypoint is anywhere near the leg it claims to be on, which is
    the one question a schematic arc can still answer honestly.

    Args:
        start: ``[lon, lat]`` in degrees.
        end: ``[lon, lat]`` in degrees.

    Returns:
        The great-circle distance in kilometres, on a sphere of mean Earth radius.

    Contract:
        - Symmetric, and zero for a point and itself.
        - Never raises.

    Examples:
        London to Suez, which the itinerary budgets seven days for:

        >>> round(great_circle_km([-0.1275, 51.50722], [32.53333, 29.96667]))
        3596
        >>> great_circle_km([10.0, 10.0], [10.0, 10.0])
        0.0
    """
    # Haversine rather than the arc-cosine of a dot product. The two agree at this
    # scale, but acos loses its precision exactly where the angle is small — which is
    # the case a "is this waypoint near its leg?" test spends most of its time in.
    lon1, lat1 = math.radians(float(start[0])), math.radians(float(start[1]))
    lon2, lat2 = math.radians(float(end[0])), math.radians(float(end[1]))
    half = (
        math.sin((lat2 - lat1) / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(half)))


def journey_payload(
    spine: RouteSpine, rows: Mapping[str, Mapping[str, str]]
) -> dict[str, object]:
    """The route as the globe draws it: nine stops, eight arcs, eighty days.

    Args:
        spine: The parsed :class:`~verne80.route.RouteSpine`.
        rows: ``places.csv``, keyed by place key.

    Returns:
        The journey payload.

    Contract:
        - Nodes are in itinerary order and never sorted; London appears twice, at index
          ``0`` and index ``8``, because the route is a cycle and that is its shape.
        - A node whose row is rejected, or which never resolved, carries ``None`` for
          both coordinates rather than a guess.
        - A leg between two located nodes carries an arc of :data:`ARC_SAMPLES` points;
          a leg missing an endpoint carries an empty arc and a null ``arc_is``, so a gap
          in the gazetteer reads as a gap rather than as a straight line to nowhere.
    """
    cumulative = list(spine.cumulative_days())
    nodes = []
    for node in spine.nodes:
        row = rows.get(node.key, {})
        status = _status(row)
        # A rejected row keeps its coordinates in the CSV — the human said "not this
        # place", not "no place" — but it must not reach the globe as a pin. Dropping it
        # here rather than in the CSV is what lets the correction stay a one-cell edit.
        point = None if status == "rejected" else _point(row)
        nodes.append(
            {
                "index": node.index,
                "key": node.key,
                "name_in_text": node.name_in_text,
                "modern_name": row.get("modern_name", "") or node.name_in_text,
                "name_changed": bool(row.get("name_changed", "").strip()),
                "lon": point[0] if point else None,
                "lat": point[1] if point else None,
                "qid": row.get("qid", ""),
                "confidence": _confidence(row),
                "status": status,
                "day": cumulative[node.index] if node.index < len(cumulative) else None,
                "first_chapter": _int_or_none(row.get("first_chapter", "")),
            }
        )

    by_index = {node["index"]: node for node in nodes}
    legs = []
    for leg in spine.legs:
        origin, destination = (
            by_index[leg.origin.index],
            by_index[leg.destination.index],
        )
        ends = _both_points(origin, destination)
        modes = [mode.value for mode in leg.modes]
        legs.append(
            {
                "index": leg.index,
                "origin": leg.origin.index,
                "destination": leg.destination.index,
                "days": leg.days,
                "day_from": cumulative[leg.origin.index],
                "day_to": cumulative[leg.destination.index],
                "mode_as_written": leg.mode_as_written,
                "modes": modes,
                # Drawn in the order the text writes them, never blended. Legs 0 and 7
                # are "rail and steamboats"; picking a colour per half would invent a
                # changeover point Fogg's table does not give.
                "primary_mode": modes[0] if modes else TransportMode.OTHER.value,
                "via_as_written": list(leg.via_as_written),
                "arc_is": "great_circle" if ends else None,
                "arc": great_circle(*ends) if ends else [],
                "waypoints": _waypoints_on(rows, leg.index),
            }
        )

    return {
        "generated_by": "scripts/08_dashboard.py",
        "source": {
            "chapter": spine.source_chapter,
            "sha256": spine.source_sha256,
            "note": "Fogg's own itinerary, as he reads it out in chapter 3",
        },
        "total_days_printed": spine.total_days_printed,
        "cumulative_days": cumulative,
        "transport_style": TRANSPORT_STYLE,
        "nodes": nodes,
        "legs": legs,
    }


def places_payload(
    rows: Mapping[str, Mapping[str, str]],
    chapters: Mapping[str, Sequence[int]] | None = None,
    legs: Sequence[JsonObject] = (),
    drift_ratio: float = DRIFT_RATIO,
) -> dict[str, object]:
    """Every place the book names, sorted into the ones that can be drawn and the rest.

    Tiered rather than gated. Only ``node`` and ``waypoint`` are shown by default — the
    nineteen places Fogg's own table and the curation vouch for. The rest are exported
    with their doubts attached and their layer turned off, because the alternative to
    showing an unreviewed pin behind a switch is either publishing it as though it were
    the journey or pretending the book never named it.

    A waypoint whose coordinates contradict the leg the curation puts it on is held
    back too. That is not a matter of review: the curation says Queenstown is six-tenths
    of the way from New York to London, the gazetteer says it is in New Zealand, and
    those two committed files cannot both be right. Withholding the pin needs no opinion
    about which of them is wrong — only the observation that they disagree — and it is
    what stops the default layer opening with a dot in the South Pacific.

    Args:
        rows: ``places.csv``, keyed by place key.
        chapters: Which chapters name each place, from :func:`chapters_by_place`.
        legs: The legs from :func:`journey_payload`. Without them the drift check cannot
            run, and is skipped rather than silently passing.
        drift_ratio: How far a waypoint may sit from its leg, as a multiple of that
            leg's length. Default :data:`DRIFT_RATIO`.

    Returns:
        ``places`` (drawable), ``listed`` (named but not placeable, with a reason) and
        ``counts``.

    Contract:
        - Every input row appears in exactly one of ``places`` and ``listed``.
        - A rejected row is never drawn, whatever else is true of it: ``n`` with no
          correction means nobody is vouching for this, and an unvouched-for pin does
          not move.
        - A ``local`` or ``off_route`` row is never drawn even when it has coordinates.
          A station is inside wherever the party already is, and a country is not a
          position.
        - A drawn waypoint is within ``drift_ratio`` leg-lengths of its own leg.
    """
    known = chapters or {}
    drift = _drift_by_key(rows, legs)
    places: list[dict[str, object]] = []
    listed: list[dict[str, object]] = []

    for key, row in rows.items():
        kind = row.get("corrected_kind") or row.get("kind") or PlaceKind.UNKNOWN.value
        status = _status(row)
        entry = {
            "key": key,
            "name_in_text": row.get("name_in_text", key),
            "modern_name": row.get("modern_name", ""),
            "name_changed": bool(row.get("name_changed", "").strip()),
            "kind": kind,
            "status": status,
            "first_chapter": _int_or_none(row.get("first_chapter", "")),
            "chapters": list(known.get(key, ())),
            # On the shared entry rather than only the drawn one: a place held back for
            # contradicting its leg has to be able to name the leg it contradicts.
            "leg": _int_or_none(row.get("corrected_leg") or row.get("leg", "")),
            "along": _float_or_none(row.get("corrected_along") or row.get("along", "")),
        }
        point = _point(row)
        strayed = drift.get(key)
        reason = _held_back(row, kind, status, point, strayed, drift_ratio)
        if reason:
            note = {"detail": _drift_detail(strayed)} if reason == _CONTRADICTS else {}
            listed.append({**entry, "reason": reason, **note})
            continue
        if point is None:  # pragma: no cover - _held_back returns a reason for this
            continue
        confidence = _confidence(row)
        places.append(
            {
                **entry,
                "tier": TIER_BY_KIND.get(kind, "named"),
                "lon": point[0],
                "lat": point[1],
                "qid": row.get("qid", ""),
                "country": row.get("country", ""),
                "entity_type": row.get("entity_type", ""),
                "confidence": confidence,
                "doubtful": confidence is not None and confidence < DOUBTFUL_BELOW,
                # A place that puts somebody somewhere, as against one the book merely
                # names. The merely-named ones are a layer of their own, so a reader can
                # look at what moves the map and nothing else.
                "positional": _is_positional(row),
                "km_from_leg": round(strayed[0]) if strayed else None,
                "why": row.get("gazetteer_why") or row.get("why", ""),
            }
        )

    tiers = {tier: 0 for tier in ("itinerary", "interior", "named")}
    for place in places:
        tiers[str(place["tier"])] += 1
    return {
        "generated_by": "scripts/08_dashboard.py",
        "places": places,
        "listed": listed,
        "counts": {
            "total": len(rows),
            "plotted": len(places),
            "listed": len(listed),
            "confirmed": sum(1 for p in places if p["status"] == "confirmed"),
            "doubtful": sum(1 for p in places if p["doubtful"]),
            "by_tier": tiers,
            "by_reason": _tally(str(entry["reason"]) for entry in listed),
        },
    }


def chapters_by_place(
    extractions: Iterable[ChapterExtraction],
) -> dict[str, list[int]]:
    """Which chapters name each place.

    ``places.csv`` records the *first* chapter a name appears in and how many times it
    is used, but not which chapters those were — so a place's panel could not say
    "chapters 7 and 11" without this. Rebuilt from the extractions rather than added as
    a column, because it is derivable and a derived column is one more thing to keep in
    step.

    Both ``places_visited`` and ``places_mentioned`` count. Being named is the relation
    here; whether the party went there is what ``kind`` is for.

    Args:
        extractions: The loaded :class:`~verne80.schema.ChapterExtraction` objects.

    Returns:
        Place key to the chapter numbers naming it, ascending and without repeats.

    Contract:
        - Keys are :func:`~verne80.normalize.place_key` output, so they join to
          ``places.csv`` without further folding.
        - Sound and total: a chapter is listed for a place if and only if that chapter
          names it.
    """
    found: dict[str, set[int]] = {}
    for extraction in extractions:
        named = list(extraction.places_visited) + list(extraction.places_mentioned)
        for place in named:
            key = place_key(place.name_in_text)
            if key:
                found.setdefault(key, set()).add(extraction.chapter)
    return {key: sorted(numbers) for key, numbers in sorted(found.items())}


def chapters_payload(
    extractions: Mapping[int, ChapterExtraction],
    positions: JsonObject,
    legs: Sequence[JsonObject],
    tracks: Sequence[Track],
    cast: Cast,
    nodes: Sequence[JsonObject] = (),
    drawn: Mapping[str, JsonObject] | None = None,
    held: Mapping[str, JsonObject] | None = None,
) -> dict[str, object]:
    """One entry per chapter: what happens, where, and who is there.

    The track pins are placed here, in Python, by the same interpolation that sampled
    the arcs — so a pin is on the line by construction, and the join is checkable in a
    test rather than only by looking at a browser. The two name joins are here for the
    same reason: :func:`~verne80.normalize.place_key` and
    :func:`~verne80.normalize.match_key` are a sixty-codepoint typography fold apiece,
    and a second copy of either in JavaScript would drift silently — a dot quietly
    missing rather than an exception.

    Coordinates are *not* copied in. A chapter's place carries its key, and the page
    looks the position up in ``places.json``, which it has already loaded. Duplicating
    266 coordinate pairs costs twenty kilobytes and buys nothing.

    Args:
        extractions: Chapter number to :class:`~verne80.schema.ChapterExtraction`.
        positions: ``positions.json``, as loaded.
        legs: The legs from :func:`journey_payload`, for their arcs.
        tracks: The roster from :func:`~verne80.position.load_tracks`.
        cast: The display roster from :func:`~verne80.people.load_cast`.
        nodes: The nodes from :func:`journey_payload`, so a chapter's place can say
            whether it is one of the nine stops rather than a place beside them.
        drawn: ``places_payload()["places"]``, keyed by place key.
        held: ``places_payload()["listed"]``, keyed by place key.

    Returns:
        The chapters payload.

    Contract:
        - Every chapter present in ``extractions`` appears exactly once, in order.
        - A track whose source is ``unknown`` carries no coordinates at all. Fix has not
          appeared before chapter 6, and absent is not the same as being in London.
        - Summaries are flat. There is one language, and a nesting level kept for a
          translation nobody is writing is a hole in the shape of a feature.
        - ``focus`` is Fogg's own position or ``None``. It is never a mean of the
          chapter's places: the midpoint of Pillaji and Saville Row is a viewpoint
          nobody chose.
        - Every place a chapter names appears in ``places``, plotted or not, with the
          reason attached when not — the same rule ``places_payload`` follows.
        - A person's printed spelling always survives, in ``name_in_text`` and, where a
          chapter prints two, in ``also_printed``.
    """
    by_chapter = {
        int(entry["chapter"]): entry
        for entry in (positions.get("chapters") or ())
        if entry.get("chapter") is not None
    }
    arcs = {int(leg["index"]): leg for leg in legs}
    on_route = {str(node["key"]) for node in nodes}
    roster: dict[str, dict[str, str]] = {}

    out = []
    for number in sorted(extractions):
        extraction = extractions[number]
        resolved = by_chapter.get(number, {})
        track_rows = [_track_entry(row, arcs) for row in resolved.get("tracks") or ()]
        present = _folded(
            (item.name_in_text for item in extraction.narrative.on_stage), cast, roster
        )
        elsewhere = _folded(
            (item.name_in_text for item in extraction.narrative.named_but_not_present),
            cast,
            roster,
        )
        places = _chapter_places(
            resolved.get("mentions") or {}, on_route, drawn or {}, held or {}
        )
        out.append(
            {
                "chapter": number,
                "title": extraction.title,
                "summary": {
                    "hover": extraction.summary_hover,
                    "detail": extraction.summary_detail,
                },
                "focus": _focus(track_rows),
                "transport": [
                    {
                        "mode": item.mode.value,
                        "vessel": item.vessel_or_line_name,
                        "from": item.from_,
                        "to": item.to,
                    }
                    for item in extraction.transport
                ],
                "schedule": {
                    "status": extraction.time.schedule_status.value,
                    "detail": extraction.time.schedule_detail,
                },
                "scene_places": list(resolved.get("scene_places") or ()),
                "places": places,
                "place_counts": {
                    "named": len(places),
                    "plotted": sum(1 for place in places if place["plotted"]),
                    "by_class": _tally(str(place["class"]) for place in places),
                },
                "present": present,
                "named_elsewhere": elsewhere,
                "people_counts": {
                    "present": len(present),
                    "present_named": sum(
                        1 for one in present if one["kind"] == "person"
                    ),
                    "present_roles": sum(1 for one in present if one["kind"] == "role"),
                    "named_elsewhere": len(elsewhere),
                },
                "tracks": track_rows,
            }
        )

    return {
        "generated_by": "scripts/08_dashboard.py",
        "tracks": [{"key": track.key, "display": track.display} for track in tracks],
        "cast": [roster[key] for key in sorted(roster)],
        "chapters": out,
    }


def _folded(
    names: Iterable[str], cast: Cast, roster: dict[str, dict[str, str]]
) -> list[dict[str, object]]:
    """Fold a chapter's printed names, keeping the order and every spelling.

    ``on_stage`` holds one row per person *per place*, so a chapter that moves somebody
    about names them several times — chapter 4 puts Fogg in four places. Deduped by
    identity, in the order the chapter first names them.

    Where one chapter prints a person two ways, both survive: chapter 29 has Colonel
    Proctor and Stamp Proctor, and dropping either would be tidying a quotation.
    """
    first: dict[str, Folded] = {}
    extra: dict[str, list[str]] = {}
    for name in names:
        one = cast.fold(name)
        roster.setdefault(
            one.key, {"key": one.key, "display": one.display, "kind": one.kind}
        )
        if one.key not in first:
            first[one.key] = one
            extra[one.key] = []
        elif one.name_in_text != first[one.key].name_in_text:
            if one.name_in_text not in extra[one.key]:
                extra[one.key].append(one.name_in_text)
    return [
        {
            "key": one.key,
            "display": one.display,
            "name_in_text": one.name_in_text,
            "kind": one.kind,
            "also_printed": extra[key],
        }
        for key, one in first.items()
    ]


def _chapter_places(
    mentions: Mapping[str, str],
    on_route: set[str],
    drawn: Mapping[str, JsonObject],
    held: Mapping[str, JsonObject],
) -> list[dict[str, object]]:
    """One entry per place a chapter names, plotted or not.

    ``class`` is where the place sits relative to the party — behind them, ahead of
    them, where they are, or off the route entirely. That is a *temporal* judgement and
    is not the same thing as :attr:`~verne80.position.PlaceKind.OFF_ROUTE`: Aden is
    temporally off-route in most chapters and still has a pin.
    """
    out = []
    for name, temporal in mentions.items():
        key = place_key(name)
        entry = drawn.get(key)
        withheld = held.get(key)
        out.append(
            {
                "key": key,
                "name_in_text": name,
                "class": temporal,
                "plotted": entry is not None,
                "on_route": key in on_route,
                "reason": None if entry else (withheld or {}).get("reason"),
            }
        )
    return out


def _focus(track_rows: Sequence[JsonObject]) -> dict[str, object] | None:
    """Where to turn the globe for a chapter: Fogg's own position, or nowhere.

    Not an average of the chapter's places. A mean of Pillaji and Saville Row is a
    viewpoint nobody chose, and a globe that swings to it is asserting something the
    text does not say. When Fogg has no position the globe simply does not move.
    """
    for row in track_rows:
        if row.get("track") == "fogg" and row.get("lon") is not None:
            return {"lon": row["lon"], "lat": row["lat"], "from": "fogg"}
    return None


def provenance(
    inputs: Sequence[Path],
    places_counts: JsonObject,
    journey: JsonObject,
    warnings: Sequence[str],
) -> dict[str, object]:
    """The record that says what this build was made from and how much of it is checked.

    Carries no timestamp. Nothing else in ``data/processed/`` carries one, and a clock
    reading in a committed artefact makes every rebuild a diff even when nothing
    changed. A build date, if one is ever wanted, is the git commit's.

    Args:
        inputs: The files this build read. Recorded by their repository-relative
            path, not the absolute one this machine happens to use — the record
            is published, so see :func:`_repo_relative` for what that guarantees.
        places_counts: The ``counts`` from :func:`places_payload`.
        journey: The payload from :func:`journey_payload`.
        warnings: Anything the reader of the page should be told.

    Returns:
        The provenance record. An input that does not exist is still listed, with
        ``sha256`` and ``bytes`` of ``None`` — a missing input is a fact about the
        build, not a reason to leave a gap in the record.
    """
    located = sum(1 for node in journey["nodes"] if node["lat"] is not None)
    return {
        "generated_by": "scripts/08_dashboard.py",
        "inputs": [
            {
                "path": _repo_relative(path),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size if path.exists() else None,
            }
            for path in inputs
        ],
        "route": {
            "nodes": len(journey["nodes"]),
            "nodes_located": located,
            "legs": len(journey["legs"]),
            "legs_drawn": sum(1 for leg in journey["legs"] if leg["arc"]),
            "total_days_printed": journey["total_days_printed"],
        },
        "places": dict(places_counts),
        "doubtful_below": DOUBTFUL_BELOW,
        "attribution": {
            "text": "Project Gutenberg #103",
            "gazetteer": "Wikidata",
            "coastline": "Natural Earth (public domain)",
        },
        "warnings": list(warnings),
    }


def _track_entry(row: JsonObject, arcs: Mapping[int, JsonObject]) -> dict[str, object]:
    """One track's row for one chapter, with a pin only where there is one to place."""
    entry = {
        "track": row.get("track"),
        "leg": row.get("leg"),
        "along": row.get("along"),
        "at_node": row.get("at_node"),
        "source": row.get("source"),
        "place_name_in_text": row.get("place_name_in_text"),
        "stated_at_chapter": row.get("stated_at_chapter"),
        "evidence": row.get("evidence"),
        "flags": list(row.get("flags") or ()),
        "lon": None,
        "lat": None,
    }
    if row.get("source") == PositionSource.UNKNOWN.value:
        # Not yet in the story. Placing this at the route's start would put Fix in
        # London for five chapters he is not in.
        return entry
    leg = arcs.get(row.get("leg")) if row.get("leg") is not None else None
    if not leg or not leg.get("arc"):
        return entry
    arc = leg["arc"]
    point = interpolate_great_circle(arc[0], arc[-1], float(row.get("along") or 0.0))
    entry["lon"], entry["lat"] = point[0], point[1]
    return entry


def _waypoints_on(
    rows: Mapping[str, Mapping[str, str]], leg_index: int
) -> list[dict[str, object]]:
    """The waypoints sitting on one leg, in the order they are passed."""
    # Collected as tuples and sorted before becoming dictionaries, so the sort key is
    # two comparable values rather than two lookups into a heterogeneous mapping.
    found: list[tuple[float, str, str]] = []
    for key, row in rows.items():
        kind = row.get("corrected_kind") or row.get("kind")
        if kind != PlaceKind.WAYPOINT.value or _status(row) == "rejected":
            continue
        leg = _int_or_none(row.get("corrected_leg") or row.get("leg", ""))
        along = _float_or_none(row.get("corrected_along") or row.get("along", ""))
        if leg != leg_index or along is None:
            continue
        found.append((along, key, row.get("name_in_text", key)))
    return [
        {"key": key, "name_in_text": name, "along": along}
        for along, key, name in sorted(found)
    ]


def _held_back(
    row: Mapping[str, str],
    kind: str,
    status: str,
    point: list[float] | None = None,
    strayed: tuple[float, float] | None = None,
    drift_ratio: float = DRIFT_RATIO,
) -> str | None:
    """Why a row gets no pin, or ``None`` if it gets one.

    Order matters. A human's rejection outranks everything, then the kinds that have no
    position by definition, and only then the question of whether a coordinate exists —
    because "asked and nothing came back" is a fact about the world and "never asked" is
    a fact about how far this pipeline has got, and reporting them together sends a
    reviewer hunting for a gazetteer failure that never happened.
    """
    if status == "rejected":
        return "rejected"
    if kind in _NOT_A_POSITION:
        return _NOT_A_POSITION[kind]
    if point is None:
        return (
            "none_found" if row.get("gazetteer_source", "").strip() else "not_queried"
        )
    # Last, because it takes coordinates to measure a contradiction.
    if strayed and strayed[1] and strayed[0] / strayed[1] > drift_ratio:
        return _CONTRADICTS
    return None


def _drift_by_key(
    rows: Mapping[str, Mapping[str, str]], legs: Sequence[JsonObject]
) -> dict[str, tuple[float, float]]:
    """For each waypoint, how far it is from its leg and how long that leg is.

    Both numbers rather than the ratio, because the run log wants to print kilometres
    and the decision wants a ratio. Dividing at the point of use beats storing a figure
    whose units are a matter of memory.
    """
    out: dict[str, tuple[float, float]] = {}
    for leg in legs:
        arc = leg.get("arc") or []
        if len(arc) < 2:
            continue
        span = great_circle_km(arc[0], arc[-1])
        for waypoint in leg.get("waypoints") or ():
            row = rows.get(str(waypoint["key"]))
            point = _point(row) if row else None
            if point is None:
                continue
            claimed = interpolate_great_circle(
                arc[0], arc[-1], float(waypoint["along"])
            )
            out[str(waypoint["key"])] = (great_circle_km(claimed, point), span)
    return out


def _drift_detail(strayed: tuple[float, float] | None) -> str:
    """Say how badly a waypoint misses its leg, in the units a person would use."""
    if not strayed:
        return ""
    distance, span = strayed
    ratio = distance / span if span else 0.0
    return (
        f"{distance:,.0f} km from the leg it is placed on, which is only "
        f"{span:,.0f} km long — {ratio:.1f} times its length"
    )


def _status(row: Mapping[str, str]) -> str:
    """What a human has said about a row. Blank is not agreement."""
    cell = row.get("confirmed", "")
    if is_confirmed(cell):
        return "confirmed"
    if is_rejected(cell):
        return "rejected"
    return "unconfirmed"


def _is_positional(row: Mapping[str, str]) -> bool:
    """Whether this place puts somebody somewhere, or is merely named."""
    used = row.get("used_as", "")
    return "on_stage" in used or "visited" in used


def _point(row: Mapping[str, str]) -> list[float] | None:
    """A row's coordinates as ``[lon, lat]``, or ``None`` when it has none."""
    lat, lon = row.get("lat", "").strip(), row.get("lon", "").strip()
    if not lat or not lon:
        return None
    return to_geojson_point(float(lat), float(lon))


def _both_points(
    origin: JsonObject, destination: JsonObject
) -> tuple[list[float], list[float]] | None:
    """Both ends of a leg, or ``None`` if either is unlocated."""
    if origin["lat"] is None or destination["lat"] is None:
        return None
    return (
        [float(origin["lon"]), float(origin["lat"])],
        [float(destination["lon"]), float(destination["lat"])],
    )


def _confidence(row: Mapping[str, str]) -> float | None:
    """A row's gazetteer confidence, or ``None`` when it never resolved."""
    return _float_or_none(row.get("confidence", ""))


def _int_or_none(cell: str) -> int | None:
    """A cell as an integer, or ``None`` when it is blank or not one."""
    try:
        return int(str(cell).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(cell: str) -> float | None:
    """A cell as a float, or ``None`` when it is blank or not one."""
    try:
        return float(str(cell).strip())
    except (TypeError, ValueError):
        return None


def _tally(values: Iterable[str]) -> dict[str, int]:
    """Count each distinct value, in key order."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _sha256(path: Path) -> str | None:
    """The hash of a file, or ``None`` when it is not there to hash."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: Path) -> str:
    """An input's path as the repository sees it, never as this machine sees it.

    ``provenance.json`` is published on the web, so an absolute path in it says
    where the build ran rather than what it read — meaningless to a reader, and
    someone's home directory. Most inputs arrive already relative because they
    come from the scripts' defaults; the curation files do not, because they are
    package data found through ``Path(__file__)``.

    Args:
        path: The file, relative to the working directory or absolute.

    Returns:
        The path relative to the repository root when the file sits inside it —
        ``src/verne80/people.json``, using forward slashes on every platform.
        Otherwise the bare file name, which the neighbouring ``sha256`` and
        ``bytes`` identify well enough. The file need not exist.
    """
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _to_vector(point: Sequence[float]) -> tuple[float, float, float]:
    """A ``[lon, lat]`` in degrees as a unit vector."""
    lon, lat = math.radians(float(point[0])), math.radians(float(point[1]))
    return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))


def _to_degrees(vector: Sequence[float]) -> list[float]:
    """A vector back to ``[lon, lat]`` in degrees, rounded to the metre or so."""
    x, y, z = vector
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z / length))))
    lon = math.degrees(math.atan2(y, x))
    return [round(lon, 6), round(lat, 6)]


def _orthogonal(vector: Sequence[float]) -> tuple[float, float, float]:
    """Some unit vector at right angles to this one, chosen the same way every time."""
    x, y, z = vector
    # Cross with whichever axis this vector leans on least, so the product is never the
    # zero vector and the choice does not depend on how close a call it was.
    axis = (1.0, 0.0, 0.0) if abs(x) <= abs(y) and abs(x) <= abs(z) else (0.0, 0.0, 1.0)
    cross = (
        y * axis[2] - z * axis[1],
        z * axis[0] - x * axis[2],
        x * axis[1] - y * axis[0],
    )
    length = math.sqrt(sum(component * component for component in cross)) or 1.0
    return (cross[0] / length, cross[1] / length, cross[2] / length)
