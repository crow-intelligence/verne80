"""The coastline: winding, rounding, and the one mistake that inks the ocean."""

from __future__ import annotations

import json
import math
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from verne80.basemap import (
    BORDER_PLACES,
    SPHERE_AREA,
    normalise_winding,
    outline_payload,
    ring_area,
    round_coords,
    unnamed_features,
)
from verne80.sources import BORDERS_1880, BORDERS_MODERN, LAND

REPO_ROOT = Path(__file__).resolve().parent.parent
COASTLINE = REPO_ROOT / LAND.path
BORDER_FILES = {
    "1880": REPO_ROOT / BORDERS_1880.path,
    "modern": REPO_ROOT / BORDERS_MODERN.path,
}

# A one-degree square. CW is clockwise on a north-up map: what d3-geo reads as an
# exterior ring, and what Natural Earth ships. CCW is RFC 7946's convention, and the
# one that floods the ocean if it reaches the canvas unturned.
CW = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
CCW = list(reversed(CW))


def collection(*polygons):
    return {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "Polygon", "coordinates": list(rings)}}
            for rings in polygons
        ],
    }


# --------------------------------------------------------------------- ring_area


def test_positive_is_the_area_d3_will_fill():
    """Clockwise, not counter-clockwise. This is the fact the module exists for.

    Checked against d3-geo itself, the only authority that matters here::

        node --input-type=module -e "
          import {geoArea} from './web/vendor/d3-geo-3.1.1.js';
          const sq = [[0,0],[0,1],[1,1],[1,0],[0,0]];
          console.log(geoArea({type:'Polygon', coordinates:[sq]}));
          console.log(geoArea({type:'Polygon', coordinates:[[...sq].reverse()]}));
        "
        0.000304602...      <- clockwise: the square
        12.566066...        <- counter-clockwise: the rest of the world
    """
    assert ring_area(CW) == pytest.approx(0.000304602, rel=1e-6)
    assert ring_area(CCW) == pytest.approx(-0.000304602, rel=1e-6)


def test_a_hemisphere_is_half_the_sphere():
    equator = [[float(lon), 0.0] for lon in range(-180, 181, 30)]
    assert ring_area(equator) == pytest.approx(SPHERE_AREA / 2, rel=1e-9)


def test_the_area_is_spherical_and_not_planar():
    """A planar shoelace gives the same answer at both latitudes. A sphere does not.

    Two squares of identical extent in degrees, one at the equator and one at 60 north.
    On the ground the second is half the size, because the meridians have converged.
    """
    high = [[lon, lat + 60.0] for lon, lat in CCW]
    assert ring_area(high) == pytest.approx(
        ring_area(CCW) * math.cos(math.radians(60.5)), rel=0.01
    )


def test_a_ring_crossing_the_antimeridian_is_not_a_ring_round_the_world():
    """The short way round: a 4-degree box at the date line is not 356 degrees wide."""
    box = [[178.0, 0.0], [-178.0, 0.0], [-178.0, 1.0], [178.0, 1.0], [178.0, 0.0]]
    assert abs(ring_area(box)) < 0.01


# ---------------------------------------------------------------- normalise_winding


def test_normalising_turns_an_rfc_7946_exterior_round_for_d3():
    """Which is the state the historic-borders layer will arrive in."""
    assert ring_area(normalise_winding([CCW])[0]) > 0


def test_natural_earths_own_winding_is_left_exactly_alone():
    """It is already what d3 wants. Turning it is what floods the ocean."""
    assert normalise_winding([CW])[0] == CW


def test_a_hole_is_wound_against_its_exterior():
    exterior, hole = normalise_winding([CCW, CW])
    assert ring_area(exterior) > 0
    assert ring_area(hole) < 0


def test_normalising_never_adds_or_drops_a_point():
    rings = normalise_winding([CCW, CW])
    assert [len(ring) for ring in rings] == [len(CCW), len(CW)]


# -------------------------------------------------------------------- round_coords


def test_rounding_keeps_every_ring_even_a_collapsed_one():
    speck = [[0.0, 0.0], [0.001, 0.0], [0.0, 0.001], [0.0, 0.0]]
    assert len(round_coords([CCW, speck])) == 2


def test_a_rounded_ring_is_still_closed():
    for ring in round_coords([[[0.0, 0.0], [1.004, 0.0], [1.0, 1.0], [0.0, 0.0]]]):
        assert ring[0] == ring[-1]


# --------------------------------------------------------------------- outline_payload


def test_an_empty_collection_is_an_error_not_a_blank_globe():
    with pytest.raises(ValueError, match="no drawable polygon"):
        outline_payload({"type": "FeatureCollection", "features": []})


def test_a_speck_that_rounds_away_is_dropped_not_drawn():
    speck = [[0.0, 0.0], [0.001, 0.0], [0.0, 0.001], [0.0, 0.0]]
    payload = outline_payload(collection([CCW], [speck]))
    assert len(payload["coordinates"]) == 1


def test_a_ring_that_survives_backwards_is_refused():
    """A ring still covering half the sphere after normalising would fill the ocean.

    Normalising picks the positive winding. When that pick goes the wrong way the
    result is not subtly off, it is the complement — so the size is the giveaway.
    """
    # A ring circling the north pole at 80 degrees. The cap inside it is tiny, but read
    # the other way round it is everything south of 80 — which is 12.5 of the sphere's
    # 12.6 steradians. This is a small polar island digitised backwards.
    polar = [[float(lon), 80.0] for lon in range(360, -1, -20)]
    with pytest.raises(ValueError, match="more than half the sphere"):
        outline_payload(collection([polar]))


def test_a_multipolygon_feature_is_unpacked():
    payload = outline_payload(
        {
            "type": "FeatureCollection",
            "features": [
                {"geometry": {"type": "MultiPolygon", "coordinates": [[CCW], [CW]]}}
            ],
        }
    )
    assert len(payload["coordinates"]) == 2


# ------------------------------------------------------- the committed coastline


@pytest.mark.skipif(
    not COASTLINE.exists(), reason="run scripts/00_fetch.py --only land"
)
def test_the_committed_coastline_survives_the_winding_trap():
    """The whole reason this module exists.

    The giveaway is arithmetic rather than visual: read the way d3 reads them, the rings
    must add up to Earth's land fraction and not to its ocean's. A file wound the other
    way passes every structural check and then paints the sea instead of the shore.
    """
    payload = outline_payload(json.loads(COASTLINE.read_text(encoding="utf-8")))
    exteriors = [ring_area(rings[0]) for rings in payload["coordinates"]]

    assert all(area > 0 for area in exteriors)
    assert max(exteriors) < SPHERE_AREA / 2
    land_fraction = sum(exteriors) / SPHERE_AREA
    assert 0.27 < land_fraction < 0.31, f"{land_fraction:.3f} is not Earth's land"


@pytest.mark.skipif(
    not COASTLINE.exists(), reason="run scripts/00_fetch.py --only land"
)
def test_natural_earth_needs_no_turning_and_this_records_that():
    """If a future Natural Earth release switches to RFC 7946, this is what says so.

    The pipeline would keep working — normalise_winding would simply start reversing
    rings — but the fact would have changed, and a silently changed fact is how a module
    docstring ends up lying.
    """
    raw = json.loads(COASTLINE.read_text(encoding="utf-8"))
    turned = 0
    for feature in raw["features"]:
        # The whole polygon, not each ring alone: the first ring is the exterior and the
        # rest are holes, and a hole handed in as an exterior is correctly reversed.
        polygon = feature["geometry"]["coordinates"]
        before = [[list(point) for point in ring] for ring in polygon]
        turned += sum(a != b for a, b in zip(normalise_winding(polygon), before))
    assert turned == 0, f"{turned} rings had to be reversed; Natural Earth has changed"


@pytest.mark.skipif(
    not COASTLINE.exists(), reason="run scripts/00_fetch.py --only land"
)
def test_every_committed_ring_is_closed_and_has_an_inside():
    payload = outline_payload(json.loads(COASTLINE.read_text(encoding="utf-8")))
    for rings in payload["coordinates"]:
        for ring in rings:
            assert ring[0] == ring[-1]
            assert len(ring) >= 4
            assert all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in ring)


# ----------------------------------------------------------------- properties

lons = st.floats(-180, 180, allow_nan=False, allow_infinity=False, width=32)
lats = st.floats(-89, 89, allow_nan=False, allow_infinity=False, width=32)
rings = st.lists(st.tuples(lons, lats).map(list), min_size=3, max_size=12).map(
    lambda points: points + [list(points[0])]
)


@given(rings)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_reversing_a_ring_negates_its_area(ring):
    """Including an edge spanning exactly 180 degrees, where the wrap is ambiguous."""
    assert ring_area(list(reversed(ring))) == pytest.approx(
        -ring_area(ring), abs=1e-9, rel=1e-9
    )


@given(rings)
@settings(max_examples=200)
def test_normalising_is_idempotent(ring):
    once = normalise_winding([ring])
    assert normalise_winding(once) == once


@given(rings, st.integers(min_value=0, max_value=4))
@settings(max_examples=200)
def test_rounding_is_a_contraction_that_keeps_the_ring_count(ring, places):
    rounded = round_coords([ring], places)
    assert len(rounded) == 1
    step = 0.5 * 10.0**-places
    # Every kept vertex must be a rounded original — the rounding may drop a duplicate
    # but it may never invent a point or move one further than half a step.
    originals = {(round(lon, places), round(lat, places)) for lon, lat in ring}
    for lon, lat in rounded[0]:
        assert (lon, lat) in originals
        assert min(abs(lon - o) for o, _ in originals) <= step + 1e-9


@given(rings)
@settings(max_examples=200)
def test_area_is_always_a_finite_number(ring):
    """No bound is asserted: a ring crossing itself may wind past the sphere, honestly.

    What must hold is that nothing raises and nothing comes back as a nan, because a
    single nan would poison a winding decision and silently invert a continent.
    """
    area = ring_area(ring)
    assert math.isfinite(area)


# ------------------------------------------------------ the two border layers


needs_borders = pytest.mark.skipif(
    not all(path.exists() for path in BORDER_FILES.values()),
    reason="run scripts/00_fetch.py --only borders-1880 --only borders-modern",
)


@needs_borders
@pytest.mark.parametrize("era", sorted(BORDER_FILES))
def test_the_borders_need_no_turning_either(era):
    """The fact a docstring in this module used to get wrong, now checked instead.

    It predicted that the historic layer would be RFC 7946 and would need every ring
    turned. All 539 exterior rings of ``world_1880`` are clockwise — d3's convention —
    because the file was exported from a shapefile rather than re-wound to the standard.
    If a future release of either source switches convention, this fails rather than
    quietly painting the sea.
    """
    raw = json.loads(BORDER_FILES[era].read_text(encoding="utf-8"))
    backwards = 0
    for feature in raw["features"]:
        geometry = feature.get("geometry") or {}
        parts = (
            [geometry["coordinates"]]
            if geometry.get("type") == "Polygon"
            else list(geometry.get("coordinates") or ())
        )
        for part in parts:
            if part and ring_area(part[0]) < 0:
                backwards += 1
    assert backwards == 0, f"{backwards} exterior rings are wound the other way now"


@needs_borders
@pytest.mark.parametrize("era", sorted(BORDER_FILES))
def test_a_border_layer_covers_the_land_and_not_the_ocean(era):
    """Same giveaway as the coastline: the rings must add up to Earth's land."""
    raw = json.loads(BORDER_FILES[era].read_text(encoding="utf-8"))
    payload = outline_payload(raw, BORDER_PLACES, drop_unnamed=True)
    exteriors = [ring_area(rings[0]) for rings in payload["coordinates"]]
    assert all(area > 0 for area in exteriors)
    assert max(exteriors) < SPHERE_AREA / 2
    # Below the coastline's 29% because the unnamed features are dropped, and in 1880
    # that includes an Antarctica worth about 5% of the sphere.
    assert 0.20 < sum(exteriors) / SPHERE_AREA < 0.31


@needs_borders
def test_the_1880_antarctica_is_dropped_because_it_draws_as_a_straight_rule():
    """The case the unnamed-feature rule exists for.

    The source gives 1880 an Antarctica reaching from the pole to 63 degrees south
    across every longitude, and attributes it to nobody. As a hairline that is a
    straight line right round the globe, which reads as a bug rather than as a border.
    """
    raw = json.loads(BORDER_FILES["1880"].read_text(encoding="utf-8"))
    dropped = unnamed_features(raw)
    assert len(dropped) == 63

    def southern_span(feature):
        lats = [
            point[1]
            for part in feature["geometry"]["coordinates"]
            for ring in part
            for point in ring
        ]
        return min(lats)

    assert min(southern_span(one) for one in dropped) == pytest.approx(-90.0)

    kept = outline_payload(raw, BORDER_PLACES, drop_unnamed=True)
    lowest = min(
        point[1] for rings in kept["coordinates"] for ring in rings for point in ring
    )
    assert lowest > -80, "something still reaches the pole"


def test_an_unnamed_feature_is_only_dropped_when_asked():
    """Off by default.

    Every feature in the coastline is unnamed, and dropping them all would leave an
    empty globe.
    """
    named = {
        "properties": {"NAME": "Luxembourg"},
        "geometry": {"type": "Polygon", "coordinates": [CW]},
    }
    blank = {
        "properties": {"NAME": None},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]
            ],
        },
    }
    collection = {"type": "FeatureCollection", "features": [named, blank]}
    assert len(outline_payload(collection)["coordinates"]) == 2
    assert len(outline_payload(collection, drop_unnamed=True)["coordinates"]) == 1


def test_a_name_of_only_whitespace_counts_as_no_name():
    collection = {"features": [{"properties": {"NAME": "   "}}]}
    assert len(unnamed_features(collection)) == 1


def test_a_feature_with_no_properties_at_all_counts_as_unnamed():
    assert len(unnamed_features({"features": [{}]})) == 1
