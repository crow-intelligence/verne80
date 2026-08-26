r"""Coastline geometry, wound and rounded so an orthographic globe can draw it.

Three jobs, each a distinct way the same file can be wrong.

**Winding, and d3 does not do what the standard says.** d3-geo treats a polygon as
*spherical*, so a ring wound the wrong way does not draw a mirrored shape — it fills its
own complement, and the ocean floods while the continents become holes punched in it.

The trap is that **d3-geo wants clockwise exterior rings**, which is the opposite of
RFC 7946. Ask it and it says so:

.. code-block:: javascript

    const square = [[0,0], [0,1], [1,1], [1,0], [0,0]];   // clockwise, one degree
    geoArea({type: "Polygon", coordinates: [square]});                //  0.000305
    geoArea({type: "Polygon", coordinates: [square.reverse()]});      // 12.566066

Natural Earth follows the ESRI shapefile convention, which is clockwise, so
``ne_110m_land`` is **already right for d3**, and :func:`normalise_winding` leaves all
127 of its rings alone. The function still earns its place twice over: it makes "wound
the way d3 reads it" a checked fact rather than a lucky one, and the historic-boundary
layer that comes next is RFC 7946 GeoJSON, wound the other way, where every ring will
need turning. :func:`ring_area` is signed so that **positive is the area d3 will fill**
— the number that decides what you see, rather than the one a standard prefers.

**Rounding.** 1:110m resolves nothing finer than a few kilometres, so coordinates past
two decimal places are noise that costs bytes. :func:`round_coords` drops them, and is
deliberately *only* a rounding: it never changes the number of rings, so the property
that it moves no vertex more than half a step is testable on its own.

**Hygiene.** Rounding can collapse a small island onto a single point. Those rings are
left in place by :func:`round_coords` and discarded by :func:`land_payload`, so
"shrinking coordinates" and "discarding shapes" stay two separate, separately checkable
decisions rather than one function that quietly does both.

The output is land, not countries. The first phase of the globe draws no borders, so one
dissolved MultiPolygon is the entire requirement — and a file with no country in it
cannot be read as making a claim about which country anything is in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "Ring",
    "SPHERE_AREA",
    "land_payload",
    "normalise_winding",
    "ring_area",
    "round_coords",
]

# Decoded GeoJSON. `Any` is the honest annotation for a structure whose shape is
# checked at run time by the very functions below, rather than promised by a type.
GeoJSON = Mapping[str, Any]

# A ring is a closed list of [lon, lat] pairs. GeoJSON order, not the (lat, lon) the
# rest of this package uses — see verne80.globe.to_geojson_point for that boundary.
Ring = list[list[float]]

# The area of a unit sphere, in steradians. An exterior ring larger than half of this is
# the tell that it is wound backwards and is describing everything it does not enclose.
SPHERE_AREA = 4.0 * math.pi

# Below this a ring bounds nothing — under a square metre on Earth. Such a ring has no
# winding to speak of, and reversing it on the sign of its own rounding error would make
# normalisation flip it back and forth for ever instead of settling.
_FLAT = 1e-12


def ring_area(ring: Sequence[Sequence[float]]) -> float:
    """The signed spherical area of a ring, in steradians.

    **Positive is the area d3-geo will fill**, which is the number that decides what
    appears on screen. That means positive is *clockwise* on a north-up map — the
    interior on the right of travel — because that is d3's convention for an exterior
    ring, and it is the opposite of RFC 7946's. Negative is counter-clockwise: d3's
    convention for a hole.

    A negative result is not "a small area, backwards". Read the way d3 reads it, such a
    ring encloses ``SPHERE_AREA + area`` — the complement of what was almost certainly
    meant. That is the failure mode that inks the oceans, and it is why this returns a
    signed number rather than a magnitude and a flag.

    The sum is the spherical excess (Chamberlain & Duquette 2007), not a planar
    shoelace. A planar formula would be wrong by a factor that grows with latitude, and
    would call Antarctica — a ring that walks the ``-90`` parallel — degenerate.

    Args:
        ring: A closed ring of ``[lon, lat]`` pairs, in degrees.

    Returns:
        The signed area in steradians, within ``[-SPHERE_AREA, SPHERE_AREA]``.

    Contract:
        - Reversing a ring negates the result.
        - A ring of fewer than three distinct points has area ``0.0``.
        - For a ring that does not cross itself the magnitude is at most
          :data:`SPHERE_AREA`. One that winds round the world twice accumulates more
          than that, which is arithmetic rather than a defect — but it is why the bound
          is not promised.
        - Never raises. A ring crossing the antimeridian is handled, because each edge's
          longitude step is taken the short way round.

    Examples:
        A one-degree square walked clockwise — the way d3 wants an exterior — encloses
        about ``(pi/180)**2`` steradians, and ``d3.geoArea`` agrees to six places:

        >>> clockwise = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
        >>> round(ring_area(clockwise), 9)
        0.000304602

        Walk it the other way and only the sign changes:

        >>> round(ring_area(list(reversed(clockwise))), 9)
        -0.000304602

        A degenerate ring encloses nothing:

        >>> ring_area([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
        0.0
    """
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:], strict=False):
        # The short way round, so an edge spanning the antimeridian contributes its real
        # width rather than the 358 degrees the raw subtraction would give.
        step = math.radians(lon2 - lon1)
        wrapped = (step + math.pi) % (2.0 * math.pi) - math.pi
        # An edge spanning exactly 180 degrees is the same length either way round, and
        # the modulo above resolves both directions to -pi — which would make a ring and
        # its reverse disagree by 2*pi rather than by a sign. Keep the original heading.
        step = math.pi if wrapped == -math.pi and step > 0.0 else wrapped
        sines = math.sin(math.radians(lat1)) + math.sin(math.radians(lat2))
        total += step * (2.0 + sines)
    # Not negated. The sum integrates with the interior on the *right*, which is exactly
    # d3's reading — so positive is the area that will actually be filled, and no caller
    # has to hold two conventions at once to know what it will see.
    return total / 2.0


def normalise_winding(polygon: Sequence[Sequence[Sequence[float]]]) -> list[Ring]:
    """Wind a polygon's rings the way d3-geo reads them.

    Exterior ring clockwise, every hole counter-clockwise — d3's convention, and the
    reverse of RFC 7946's. The first ring is taken to be the exterior, which is what
    GeoJSON says it is. Containment is not re-derived: a file with its rings in the
    wrong order is broken in a way that reordering them here would hide, not fix.

    Args:
        polygon: A GeoJSON ``Polygon``'s coordinates: exterior ring first, then holes.

    Returns:
        The same rings, each possibly reversed.

    Contract:
        - Idempotent: normalising twice is the same as normalising once. A ring with
          no area is left alone, since it has no winding to get wrong.
        - Ring count, and the point count of every ring, are unchanged.
        - Afterwards the exterior ring's :func:`ring_area` is non-negative and every
          hole's is non-positive — that is, the exterior encloses what it looks like it
          encloses when d3 draws it.

    Examples:
        An RFC 7946 exterior — counter-clockwise — is turned round for d3:

        >>> counter = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        >>> round(ring_area(counter), 9)
        -0.000304602
        >>> round(ring_area(normalise_winding([counter])[0]), 9)
        0.000304602

        Natural Earth's own winding is already what d3 wants, and is left untouched:

        >>> clockwise = list(reversed(counter))
        >>> normalise_winding([clockwise])[0] == clockwise
        True
    """
    out: list[Ring] = []
    for index, ring in enumerate(polygon):
        points = [list(point) for point in ring]
        area = ring_area(points)
        wants_positive = index == 0
        if abs(area) > _FLAT and ((area < 0.0) if wants_positive else (area > 0.0)):
            points.reverse()
        out.append(points)
    return out


def round_coords(
    polygon: Sequence[Sequence[Sequence[float]]], places: int = 2
) -> list[Ring]:
    """Shed coordinate precision the source never had, and nothing else.

    At 1:110m a coordinate's third decimal place is smaller than the error already in
    it. Two places is about 1.1 km at the equator, well under a pin's radius on any
    globe this page will draw.

    Consecutive duplicates left behind by the rounding are dropped and the ring is
    re-closed, so the result stays a ring. What this does *not* do is discard a ring
    that has collapsed — that is :func:`land_payload`'s decision. Keeping the two
    apart is what lets "no vertex moved far" be asserted with no survivorship caveat.

    Args:
        polygon: A GeoJSON ``Polygon``'s coordinates.
        places: Decimal places to keep. Default ``2``.

    Returns:
        The rounded rings, in the same order, one per input ring.

    Contract:
        - The ring count is unchanged, degenerate results included.
        - No vertex moves more than ``0.5 * 10**-places`` in either coordinate.
        - Every returned ring with two or more points is closed.
        - Never raises.

    Examples:
        >>> ring = [[0.0, 0.0], [0.004, 0.0], [1.0, 1.0], [0.0, 0.0]]
        >>> round_coords([ring])
        [[[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]

        A ring that collapses is kept, not dropped:

        >>> round_coords([[[0.0, 0.0], [0.001, 0.0], [0.0, 0.0]]])
        [[[0.0, 0.0]]]
    """
    out: list[Ring] = []
    for ring in polygon:
        points: Ring = []
        for lon, lat in ring:
            point = [round(float(lon), places), round(float(lat), places)]
            if not points or point != points[-1]:
                points.append(point)
        if len(points) > 1 and points[0] != points[-1]:
            points.append(list(points[0]))
        out.append(points)
    return out


def land_payload(geojson: Mapping[str, Any], places: int = 2) -> dict[str, object]:
    """Dissolve a coastline FeatureCollection into one MultiPolygon the globe can draw.

    Natural Earth's land layer arrives as 127 separate features, each carrying the same
    three properties, all of which say only that it is land. Nothing on the globe tells
    them apart, so they are merged: one geometry, one fill, and no per-feature
    bookkeeping to imply a distinction the data does not make.

    Args:
        geojson: A GeoJSON ``FeatureCollection`` of ``Polygon`` features.
        places: Decimal places to keep. Default ``2``.

    Returns:
        A GeoJSON ``MultiPolygon`` geometry — a valid standalone file, so it opens in a
        GIS as well as feeding ``d3.geoPath``.

    Raises:
        ValueError: If the collection holds no drawable polygon, or if a ring survives
            normalisation still covering more than half the sphere. The first would
            render as a blank globe and the second as an inked one; both look like
            styling problems and neither is.

    Contract:
        - Every ring is closed and has at least four points.
        - Exterior rings are clockwise and holes counter-clockwise, which is what
          d3-geo reads as "the inside is in here".
        - No exterior ring exceeds ``SPHERE_AREA / 2``.

    Examples:
        >>> square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        >>> payload = land_payload({
        ...     "type": "FeatureCollection",
        ...     "features": [
        ...         {"geometry": {"type": "Polygon", "coordinates": [square]}}
        ...     ],
        ... })
        >>> payload["type"], len(payload["coordinates"])
        ('MultiPolygon', 1)

        A collection with nothing drawable in it is an error, not an empty globe:

        >>> land_payload({"type": "FeatureCollection", "features": []})
        Traceback (most recent call last):
        ValueError: no drawable polygon in the coastline — 0 features, 0 rings survived
    """
    features = list(geojson.get("features") or ())
    polygons: list[list[Ring]] = []
    kept = 0
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        if kind == "Polygon":
            parts: list[Sequence[Sequence[Sequence[float]]]] = [
                geometry.get("coordinates") or []
            ]
        elif kind == "MultiPolygon":
            parts = list(geometry.get("coordinates") or ())
        else:
            continue
        for part in parts:
            rings = [ring for ring in round_coords(part, places) if _is_drawable(ring)]
            if not rings:
                continue
            kept += len(rings)
            polygons.append(normalise_winding(rings))

    if not polygons:
        raise ValueError(
            f"no drawable polygon in the coastline — {len(features)} features, "
            f"{kept} rings survived"
        )

    half = SPHERE_AREA / 2.0
    for rings in polygons:
        area = ring_area(rings[0])
        if area > half:
            raise ValueError(
                f"an exterior ring covers {area:.2f} of {SPHERE_AREA:.2f} steradians, "
                "more than half the sphere — it is wound backwards and would fill the "
                "ocean instead of the land"
            )
    return {"type": "MultiPolygon", "coordinates": polygons}


def _is_drawable(ring: Sequence[Sequence[float]]) -> bool:
    """Whether a ring still bounds an area after rounding.

    Four points is the minimum for a closed ring around a triangle. Below that the
    rounding has collapsed an island to a line or a dot, and drawing it would put a
    zero-area smudge on the globe.
    """
    return len(ring) >= 4 and ring[0] == ring[-1]
