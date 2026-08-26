"""The coastline: winding, rounding, and the one mistake that inks the ocean."""

from __future__ import annotations

import json
import math
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from verne80.basemap import (
    SPHERE_AREA,
    land_payload,
    normalise_winding,
    ring_area,
    round_coords,
)
from verne80.sources import LAND

REPO_ROOT = Path(__file__).resolve().parent.parent
COASTLINE = REPO_ROOT / LAND.path

# A one-degree square, counter-clockwise on a north-up map: RFC 7946's exterior winding.
CCW = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
CW = list(reversed(CCW))


def collection(*polygons):
    return {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "Polygon", "coordinates": list(rings)}}
            for rings in polygons
        ],
    }


# --------------------------------------------------------------------- ring_area


def test_counter_clockwise_is_positive_and_clockwise_is_negative():
    assert ring_area(CCW) > 0
    assert ring_area(CW) < 0


def test_a_hemisphere_is_half_the_sphere():
    equator = [[float(lon), 0.0] for lon in range(180, -181, -30)]
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


def test_normalising_turns_an_esri_exterior_the_right_way():
    assert ring_area(normalise_winding([CW])[0]) > 0


def test_a_hole_is_wound_against_its_exterior():
    exterior, hole = normalise_winding([CW, CCW])
    assert ring_area(exterior) > 0
    assert ring_area(hole) < 0


def test_normalising_never_adds_or_drops_a_point():
    rings = normalise_winding([CW, CCW])
    assert [len(ring) for ring in rings] == [len(CW), len(CCW)]


# -------------------------------------------------------------------- round_coords


def test_rounding_keeps_every_ring_even_a_collapsed_one():
    speck = [[0.0, 0.0], [0.001, 0.0], [0.0, 0.001], [0.0, 0.0]]
    assert len(round_coords([CCW, speck])) == 2


def test_a_rounded_ring_is_still_closed():
    for ring in round_coords([[[0.0, 0.0], [1.004, 0.0], [1.0, 1.0], [0.0, 0.0]]]):
        assert ring[0] == ring[-1]


# --------------------------------------------------------------------- land_payload


def test_an_empty_collection_is_an_error_not_a_blank_globe():
    with pytest.raises(ValueError, match="no drawable polygon"):
        land_payload({"type": "FeatureCollection", "features": []})


def test_a_speck_that_rounds_away_is_dropped_not_drawn():
    speck = [[0.0, 0.0], [0.001, 0.0], [0.0, 0.001], [0.0, 0.0]]
    payload = land_payload(collection([CCW], [speck]))
    assert len(payload["coordinates"]) == 1


def test_a_ring_that_survives_backwards_is_refused():
    """A ring still covering half the sphere after normalising would fill the ocean.

    Normalising picks the positive winding. When that pick goes the wrong way the
    result is not subtly off, it is the complement — so the size is the giveaway.
    """
    # A ring circling the north pole at 80 degrees. The cap inside it is tiny, but read
    # the other way round it is everything south of 80 — which is 12.5 of the sphere's
    # 12.6 steradians. This is a small polar island digitised backwards.
    polar = [[float(lon), 80.0] for lon in range(0, 361, 20)]
    with pytest.raises(ValueError, match="more than half the sphere"):
        land_payload(collection([polar]))


def test_a_multipolygon_feature_is_unpacked():
    payload = land_payload(
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

    Natural Earth ships clockwise exterior rings. Drawn as-is by d3-geo they would fill
    the sea and leave the land blank, and the giveaway is arithmetic rather than visual:
    afterwards the rings must add up to Earth's land fraction, not to its ocean's.
    """
    payload = land_payload(json.loads(COASTLINE.read_text(encoding="utf-8")))
    exteriors = [ring_area(rings[0]) for rings in payload["coordinates"]]

    assert all(area > 0 for area in exteriors)
    assert max(exteriors) < SPHERE_AREA / 2
    land_fraction = sum(exteriors) / SPHERE_AREA
    assert 0.27 < land_fraction < 0.31, f"{land_fraction:.3f} is not Earth's land"


@pytest.mark.skipif(
    not COASTLINE.exists(), reason="run scripts/00_fetch.py --only land"
)
def test_every_committed_ring_is_closed_and_has_an_inside():
    payload = land_payload(json.loads(COASTLINE.read_text(encoding="utf-8")))
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
