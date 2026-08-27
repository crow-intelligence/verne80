"""The globe's payloads: the arcs, the joins, and what is deliberately not drawn."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from verne80.globe import (
    ARC_SAMPLES,
    TRANSPORT_STYLE,
    chapters_by_place,
    chapters_payload,
    great_circle,
    great_circle_km,
    interpolate_great_circle,
    journey_payload,
    places_payload,
    provenance,
    shortest_rotation,
    to_geojson_point,
)
from verne80.people import PEOPLE_JSON, load_cast
from verne80.position import TRACKS_JSON
from verne80.route import spine_from_nodes
from verne80.schema import TransportMode

LONDON = [-0.1275, 51.50722]
SUEZ = [32.53333, 29.96667]
BOMBAY = [72.8775, 19.07583]

COORDS = {"london": LONDON, "suez": SUEZ, "bombay": BOMBAY}


def row(key, **cells):
    """A places.csv row with everything blank unless the test cares about it."""
    point = COORDS.get(key)
    base = {
        "key": key,
        "name_in_text": key.title(),
        "kind": "node",
        "used_as": "visited:1",
        "first_chapter": "1",
        "confirmed": "",
        "lat": f"{point[1]}" if point else "",
        "lon": f"{point[0]}" if point else "",
        "confidence": "0.9",
        "gazetteer_source": "wikidata",
        "leg": "",
        "along": "",
    }
    return {**base, **cells}


def rows(*entries):
    return {entry["key"]: entry for entry in entries}


THREE_STOPS = spine_from_nodes(["London", "Suez", "Bombay"], [7, 13])


@dataclass(frozen=True)
class FakePlace:
    name_in_text: str


@dataclass(frozen=True)
class FakeTime:
    schedule_status: object = TransportMode.OTHER
    schedule_detail: str | None = None


@dataclass(frozen=True)
class FakeOnStage:
    name_in_text: str
    at_name_in_text: str | None = None


@dataclass(frozen=True)
class FakeNarrative:
    on_stage: tuple = ()
    named_but_not_present: tuple = ()


@dataclass(frozen=True)
class FakeExtraction:
    """Only the fields the payload reads, so a test states its own inputs."""

    chapter: int
    places_visited: tuple = ()
    places_mentioned: tuple = ()
    transport: tuple = ()
    title: str = "A CHAPTER"
    summary_hover: str = "One sentence."
    summary_detail: str = "Rather more than one sentence."
    time: object = FakeTime()
    narrative: object = FakeNarrative()


@dataclass(frozen=True)
class FakeNamedElsewhere:
    name_in_text: str


@dataclass(frozen=True)
class FakeTrack:
    key: str
    display: str


# ------------------------------------------------------------------ the lat/lon flip


def test_the_flip_happens_once_and_is_named():
    assert to_geojson_point(51.50722, -0.1275) == [-0.1275, 51.50722]


# ------------------------------------------------------------------------- the arcs


class TestTheArcs:
    def test_an_arc_meets_the_pins_it_is_drawn_between(self):
        arc = great_circle(LONDON, SUEZ)
        assert arc[0] == LONDON
        assert arc[-1] == SUEZ

    def test_an_arc_has_the_number_of_points_it_was_asked_for(self):
        assert len(great_circle(LONDON, SUEZ)) == ARC_SAMPLES
        assert len(great_circle(LONDON, SUEZ, 5)) == 5

    def test_two_points_is_the_floor(self):
        assert len(great_circle(LONDON, SUEZ, 0)) == 2

    def test_a_great_circle_bends_poleward_of_the_straight_line(self):
        """Which is why it cannot be drawn as a straight line on a flat map."""
        middle = interpolate_great_circle(LONDON, SUEZ, 0.5)
        flat = (LONDON[1] + SUEZ[1]) / 2
        assert middle[1] > flat

    def test_the_same_point_twice_is_not_a_division_by_zero(self):
        assert interpolate_great_circle(LONDON, LONDON, 0.5) == LONDON

    def test_antipodal_points_pick_a_circle_rather_than_raising(self):
        far = [LONDON[0] + 180.0, -LONDON[1]]
        point = interpolate_great_circle(LONDON, far, 0.5)
        assert all(math.isfinite(value) for value in point)

    def test_distance_is_symmetric_and_zero_at_a_point(self):
        assert great_circle_km(LONDON, SUEZ) == pytest.approx(
            great_circle_km(SUEZ, LONDON)
        )
        assert great_circle_km(LONDON, LONDON) == 0.0


# ------------------------------------------------------------------ the rotation


class TestSteppingTheGlobe:
    def test_the_date_line_is_crossed_the_short_way(self):
        assert shortest_rotation(170.0, -170.0) == 20.0
        assert shortest_rotation(-170.0, 170.0) == -20.0

    def test_staying_put_is_no_rotation(self):
        assert shortest_rotation(45.0, 45.0) == 0.0


# ------------------------------------------------------------------------ the route


class TestTheJourney:
    def test_the_route_is_a_cycle_and_london_appears_twice(self):
        spine = spine_from_nodes(["London", "Suez", "London"], [7, 73])
        payload = journey_payload(spine, rows(row("london"), row("suez")))
        indices = [n["index"] for n in payload["nodes"] if n["key"] == "london"]
        assert indices == [0, 2]

    def test_the_days_come_from_foggs_own_table(self):
        payload = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez"), row("bombay"))
        )
        assert [node["day"] for node in payload["nodes"]] == [0, 7, 20]
        assert payload["legs"][1]["day_from"] == 7
        assert payload["legs"][1]["day_to"] == 20

    def test_a_leg_between_two_located_stops_is_drawn(self):
        payload = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez"), row("bombay"))
        )
        assert all(len(leg["arc"]) == ARC_SAMPLES for leg in payload["legs"])
        assert all(leg["arc_is"] == "great_circle" for leg in payload["legs"])

    def test_a_leg_with_an_unlocated_end_is_a_gap_not_a_guess(self):
        payload = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez", lat="", lon=""))
        )
        assert payload["legs"][0]["arc"] == []
        assert payload["legs"][0]["arc_is"] is None

    def test_a_rejected_stop_keeps_no_coordinates(self):
        """`n` with no correction means nobody vouches for it. A pin needs one."""
        payload = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez", confirmed="n"))
        )
        suez = payload["nodes"][1]
        assert suez["status"] == "rejected"
        assert suez["lat"] is None

    def test_a_two_mode_leg_is_drawn_in_the_first_mode_and_quoted_in_full(self):
        """Blending would invent a changeover point the itinerary does not give."""
        spine = spine_from_nodes(["London", "Suez"], [7])
        leg = spine.legs[0]
        both = type(leg)(
            index=leg.index,
            origin=leg.origin,
            destination=leg.destination,
            origin_as_written=leg.origin_as_written,
            days=leg.days,
            mode_as_written="rail and steamboats",
            modes=(TransportMode.RAILWAY, TransportMode.STEAMER),
            via_as_written=("Brindisi",),
        )
        spine = type(spine)(
            nodes=spine.nodes, legs=(both,), total_days_printed=spine.total_days_printed
        )
        drawn = journey_payload(spine, rows(row("london"), row("suez")))["legs"][0]
        assert drawn["primary_mode"] == "railway"
        assert drawn["mode_as_written"] == "rail and steamboats"
        assert drawn["via_as_written"] == ["Brindisi"]

    def test_via_places_are_text_and_never_a_bend_in_the_line(self):
        payload = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez"), row("bombay"))
        )
        leg = payload["legs"][0]
        assert leg["arc"][0] == LONDON and leg["arc"][-1] == SUEZ

    def test_every_transport_mode_has_a_style(self):
        """So the legend and the drawing cannot come to disagree."""
        assert set(TRANSPORT_STYLE) == {mode.value for mode in TransportMode}

    def test_no_two_modes_share_both_a_colour_and_a_dash(self):
        """Colour alone is not a channel everyone can read. The dash is the second."""
        seen = {(s["colour"], tuple(s["dash"])) for s in TRANSPORT_STYLE.values()}
        assert len(seen) == len(TRANSPORT_STYLE)


# ----------------------------------------------------------------------- the places


class TestThePlaces:
    def test_every_row_lands_in_exactly_one_bucket(self):
        table = rows(
            row("london"), row("kholby", lat="", lon=""), row("station", kind="local")
        )
        payload = places_payload(table)
        keys = [p["key"] for p in payload["places"]] + [
            entry["key"] for entry in payload["listed"]
        ]
        assert sorted(keys) == sorted(table)

    def test_a_rejected_place_is_listed_and_not_drawn(self):
        payload = places_payload(rows(row("suez", confirmed="n")))
        assert payload["places"] == []
        assert payload["listed"][0]["reason"] == "rejected"

    def test_a_floating_interior_never_gets_a_pin_even_with_coordinates(self):
        """`station` is six places across six chapters. One dot would be five lies."""
        payload = places_payload(rows(row("suez", kind="local")))
        assert payload["places"] == []
        assert payload["listed"][0]["reason"] == "floating_interior"

    def test_a_country_is_not_a_position(self):
        payload = places_payload(
            rows(row("india", kind="off_route", lat="21.0", lon="78.0"))
        )
        assert payload["listed"][0]["reason"] == "off_route"

    def test_kholby_is_listed_rather_than_dropped(self):
        """It has no modern referent. A blank is the right answer; silence is not."""
        payload = places_payload(rows(row("kholby", lat="", lon="")))
        assert [entry["key"] for entry in payload["listed"]] == ["kholby"]
        assert payload["listed"][0]["reason"] == "none_found"

    def test_asked_and_never_asked_are_different_facts(self):
        payload = places_payload(
            rows(
                row("asked", lat="", lon="", gazetteer_source="wikidata"),
                row("never", lat="", lon="", gazetteer_source=""),
            )
        )
        reasons = {entry["key"]: entry["reason"] for entry in payload["listed"]}
        assert reasons == {"asked": "none_found", "never": "not_queried"}

    def test_a_low_confidence_place_is_marked_doubtful(self):
        payload = places_payload(rows(row("suez", confidence="0.54")))
        assert payload["places"][0]["doubtful"] is True

    def test_the_tiers_separate_the_route_from_everything_else(self):
        payload = places_payload(
            rows(
                row("suez", kind="node"),
                row("london", kind="waypoint", leg="0", along="0.2"),
                row("bombay", kind="micro"),
            )
        )
        assert payload["counts"]["by_tier"] == {
            "itinerary": 2,
            "interior": 1,
            "named": 0,
        }

    def test_a_waypoint_that_contradicts_its_leg_is_not_drawn(self):
        """The two sources disagree. Withholding needs no view on which is wrong."""
        # Placed halfway along London-Suez, but resolved to the far side of the world.
        strayed = row(
            "queenstown",
            kind="waypoint",
            leg="0",
            along="0.5",
            lat="-45.03111",
            lon="168.6625",
        )
        table = rows(row("london"), row("suez"), row("bombay"), strayed)
        journey = journey_payload(THREE_STOPS, table)
        payload = places_payload(rows(strayed), legs=journey["legs"])
        assert payload["places"] == []
        entry = payload["listed"][0]
        assert entry["reason"] == "contradicts_its_leg"
        assert entry["leg"] == 0
        assert "times its length" in entry["detail"]

    def test_a_waypoint_a_schematic_arc_merely_misses_is_still_drawn(self):
        """Aden is 1,700 km off the Suez-Bombay arc and is an entirely correct place."""
        spine = spine_from_nodes(["Suez", "Bombay"], [13])
        aden = row(
            "aden", kind="waypoint", leg="0", along="0.5", lat="12.8", lon="45.0333"
        )
        journey = journey_payload(spine, rows(row("suez"), row("bombay"), aden))
        payload = places_payload(rows(aden), legs=journey["legs"])
        assert [p["key"] for p in payload["places"]] == ["aden"]
        assert payload["places"][0]["km_from_leg"] > 1000

    def test_the_drift_check_is_skipped_rather_than_passed_when_there_are_no_legs(self):
        strayed = row(
            "queenstown",
            kind="waypoint",
            leg="0",
            along="0.5",
            lat="-45.03111",
            lon="168.6625",
        )
        assert places_payload(rows(strayed))["counts"]["plotted"] == 1


# ------------------------------------------------------------- the chapter join


class TestTheChapterJoin:
    def test_both_visited_and_mentioned_count_as_naming(self):
        found = chapters_by_place(
            [
                FakeExtraction(1, places_visited=(FakePlace("London"),)),
                FakeExtraction(2, places_mentioned=(FakePlace("London"),)),
            ]
        )
        assert found == {"london": [1, 2]}

    def test_a_name_is_folded_to_the_key_places_csv_uses(self):
        found = chapters_by_place(
            [FakeExtraction(3, places_visited=(FakePlace("Hong Kong"),))]
        )
        assert "hong kong" in found


# ---------------------------------------------------------------- the chapters


class TestTheChapters:
    def build(self, tracks, extraction=None, mentions=None):
        journey = journey_payload(
            THREE_STOPS, rows(row("london"), row("suez"), row("bombay"))
        )
        positions = {
            "chapters": [
                {
                    "chapter": 1,
                    "scene_places": [],
                    "mentions": mentions or {},
                    "tracks": tracks,
                }
            ]
        }
        return chapters_payload(
            {1: extraction or FakeExtraction(1)},
            positions,
            journey["legs"],
            [FakeTrack("fogg", "Fogg")],
            load_cast(),
            journey["nodes"],
            {"suez": {"key": "suez"}},
            {"kholby": {"key": "kholby", "reason": "none_found"}},
        )

    def test_a_track_that_has_not_appeared_gets_no_pin(self):
        """Fix is absent before chapter 6. Absent is not the same as being in London."""
        payload = self.build(
            [{"track": "fix", "leg": None, "along": None, "source": "unknown"}]
        )
        entry = payload["chapters"][0]["tracks"][0]
        assert entry["lon"] is None and entry["lat"] is None

    def test_a_pin_lands_on_the_arc_that_was_drawn(self):
        payload = self.build(
            [{"track": "fogg", "leg": 0, "along": 0.5, "source": "stated"}]
        )
        entry = payload["chapters"][0]["tracks"][0]
        assert [entry["lon"], entry["lat"]] == interpolate_great_circle(
            LONDON, SUEZ, 0.5
        )

    def test_the_summary_is_flat_because_there_is_one_language(self):
        payload = self.build([])
        assert payload["chapters"][0]["summary"]["hover"] == "One sentence."

    def test_the_globe_turns_to_foggs_own_position(self):
        payload = self.build(
            [{"track": "fogg", "leg": 0, "along": 0.5, "source": "stated"}]
        )
        focus = payload["chapters"][0]["focus"]
        assert focus["from"] == "fogg"
        assert [focus["lon"], focus["lat"]] == interpolate_great_circle(
            LONDON, SUEZ, 0.5
        )

    def test_with_fogg_unplaced_the_globe_does_not_move(self):
        """Not the mean of the chapter's places: that is a viewpoint nobody chose."""
        payload = self.build(
            [{"track": "fix", "leg": 0, "along": 0.5, "source": "stated"}]
        )
        assert payload["chapters"][0]["focus"] is None

    def test_a_person_named_in_several_places_is_listed_once(self):
        """One `on_stage` row per person per place: chapter 4 moves Fogg four times."""
        extraction = FakeExtraction(
            1,
            narrative=FakeNarrative(
                on_stage=(
                    FakeOnStage("Phileas Fogg"),
                    FakeOnStage("Phileas Fogg"),
                    FakeOnStage("Passepartout"),
                )
            ),
        )
        present = self.build([], extraction)["chapters"][0]["present"]
        assert [one["key"] for one in present] == ["fogg", "passepartout"]

    def test_two_printed_spellings_in_one_chapter_are_both_kept(self):
        """Chapter 29 really does print Colonel Proctor and Stamp Proctor."""
        extraction = FakeExtraction(
            1,
            narrative=FakeNarrative(
                on_stage=(
                    FakeOnStage("Colonel Proctor"),
                    FakeOnStage("Stamp Proctor"),
                )
            ),
        )
        present = self.build([], extraction)["chapters"][0]["present"]
        assert len(present) == 1
        assert present[0]["name_in_text"] == "Colonel Proctor"
        assert present[0]["also_printed"] == ["Stamp Proctor"]

    def test_a_role_is_never_folded_onto_a_person(self):
        """Chapter 26 has Fix and a detective on stage, and they are two men."""
        extraction = FakeExtraction(
            1,
            narrative=FakeNarrative(
                on_stage=(FakeOnStage("Fix"), FakeOnStage("detective"))
            ),
        )
        present = self.build([], extraction)["chapters"][0]["present"]
        assert [one["kind"] for one in present] == ["person", "role"]
        assert len({one["key"] for one in present}) == 2

    def test_who_is_talked_about_is_kept_apart_from_who_is_there(self):
        extraction = FakeExtraction(
            1,
            narrative=FakeNarrative(
                on_stage=(FakeOnStage("Phileas Fogg"),),
                named_but_not_present=(FakeNamedElsewhere("Byron"),),
            ),
        )
        chapter = self.build([], extraction)["chapters"][0]
        assert [one["display"] for one in chapter["present"]] == ["Phileas Fogg"]
        assert [one["display"] for one in chapter["named_elsewhere"]] == ["Byron"]

    def test_a_place_the_chapter_names_carries_the_key_places_json_uses(self):
        chapter = self.build([], None, {"Suez": "here"})["chapters"][0]
        assert chapter["places"][0]["key"] == "suez"
        assert chapter["places"][0]["plotted"] is True

    def test_an_unplottable_place_is_carried_with_its_reason(self):
        """Kholby has no modern referent. Missing is the answer; silence is not."""
        chapter = self.build([], None, {"Kholby": "off_route"})["chapters"][0]
        place = chapter["places"][0]
        assert place["plotted"] is False
        assert place["reason"] == "none_found"

    def test_a_place_that_is_a_route_stop_says_so(self):
        """So the class marks the existing dot instead of a second one on top of it."""
        chapter = self.build([], None, {"Suez": "here"})["chapters"][0]
        assert chapter["places"][0]["on_route"] is True

    def test_the_counts_agree_with_the_lists(self):
        chapter = self.build([], None, {"Suez": "here", "Kholby": "off_route"})[
            "chapters"
        ][0]
        assert chapter["place_counts"]["named"] == 2
        assert chapter["place_counts"]["plotted"] == 1


# --------------------------------------------------------------- the provenance


def test_the_provenance_counts_match_what_was_actually_drawn():
    table = rows(
        row("london"), row("suez"), row("bombay"), row("kholby", lat="", lon="")
    )
    journey = journey_payload(THREE_STOPS, table)
    places = places_payload(table, legs=journey["legs"])
    record = provenance([], places["counts"], journey, [])
    assert record["places"]["plotted"] == len(places["places"])
    assert record["route"]["nodes_located"] == 3
    assert record["route"]["legs_drawn"] == 2


def test_the_provenance_carries_no_timestamp():
    """A clock reading in a committed artefact makes every rebuild a diff."""
    record = provenance([], {"total": 0}, journey_payload(THREE_STOPS, {}), [])
    assert "generated_at" not in record
    assert not any("time" in key for key in record)


def test_the_provenance_names_inputs_as_the_repository_does():
    """The record is published, so it must not say where the build ran.

    The curation files are package data, reached through ``Path(__file__)``, so
    they arrive absolute. They have to come out relative like everything else.
    """
    journey = journey_payload(THREE_STOPS, {})
    inputs = [Path("data/raw/ne_110m_land.geojson"), PEOPLE_JSON, TRACKS_JSON]
    record = provenance(inputs, {"total": 0}, journey, [])
    recorded = [entry["path"] for entry in record["inputs"]]

    assert recorded == [
        "data/raw/ne_110m_land.geojson",
        "src/verne80/people.json",
        "src/verne80/tracks.json",
    ]
    assert not any(one.startswith("/") for one in recorded)
    assert not any(str(Path.home()) in one for one in recorded)


def test_an_input_from_outside_the_checkout_keeps_only_its_name():
    """No path outside the repository is meaningful to a reader of the record."""
    record = provenance(
        [Path("/etc/hostname")], {"total": 0}, journey_payload(THREE_STOPS, {}), []
    )
    assert record["inputs"][0]["path"] == "hostname"


# -------------------------------------------------------------------- properties

points = st.builds(
    lambda lon, lat: [lon, lat],
    st.floats(-180, 180, allow_nan=False, allow_infinity=False),
    st.floats(-89.9, 89.9, allow_nan=False, allow_infinity=False),
)
angles = st.floats(-720, 720, allow_nan=False, allow_infinity=False)


@given(points, points, st.integers(min_value=2, max_value=40))
@settings(max_examples=250)
def test_an_arc_always_meets_its_endpoints(start, end, samples):
    """Catches the lat/lon flip and the t = i/(n-1) off-by-one at once."""
    arc = great_circle(start, end, samples)
    assert arc[0] == start
    assert arc[-1] == end
    assert len(arc) == samples


@given(points, points, st.integers(min_value=3, max_value=25))
@settings(max_examples=250)
def test_sampling_and_interpolating_agree(start, end, samples):
    """The property that guarantees a waypoint pin lands on the line that was drawn."""
    arc = great_circle(start, end, samples)
    for index, sampled in enumerate(arc):
        direct = interpolate_great_circle(start, end, index / (samples - 1))
        assert sampled == direct


@given(points, points, st.integers(min_value=3, max_value=20))
@settings(max_examples=250)
def test_an_arc_never_doubles_back_on_itself(start, end, samples):
    """A sign error in the slerp still hits both ends. It just goes the wrong way."""
    arc = great_circle(start, end, samples)
    walked = [great_circle_km(start, point) for point in arc]
    for earlier, later in zip(walked, walked[1:]):
        assert later >= earlier - 1.0


@given(angles, angles)
@settings(max_examples=300)
def test_the_globe_always_turns_the_short_way(current, target):
    delta = shortest_rotation(current, target)
    assert -180.0 <= delta <= 180.0
    # Compared as a wrapped difference rather than a raw modulo: `x % 360` for a tiny
    # negative x rounds to 360.0, which would fail a test of a function that was right.
    landed = (current + delta - target + 180.0) % 360.0 - 180.0
    assert landed == pytest.approx(0.0, abs=1e-6)


@given(
    st.lists(
        st.tuples(
            st.text(min_size=1, max_size=6, alphabet="abcdef"),
            st.sampled_from(
                ["node", "waypoint", "micro", "local", "off_route", "unknown"]
            ),
            st.sampled_from(["", "y", "n"]),
            st.booleans(),
        ),
        max_size=12,
    )
)
@settings(max_examples=200)
def test_places_always_partition(entries):
    table = {}
    for key, kind, confirmed, located in entries:
        table[key] = row(
            key,
            kind=kind,
            confirmed=confirmed,
            lat="10.0" if located else "",
            lon="20.0" if located else "",
        )
    payload = places_payload(table)
    drawn = [p["key"] for p in payload["places"]]
    held = [entry["key"] for entry in payload["listed"]]
    assert sorted(drawn + held) == sorted(table)
    assert not set(drawn) & set(held)
    assert payload["counts"]["plotted"] == len(drawn)


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=1, max_value=37),
            st.lists(st.sampled_from(["London", "Suez", "Bombay", "Aden"]), max_size=4),
        ),
        max_size=10,
        unique_by=lambda pair: pair[0],
    )
)
@settings(max_examples=200)
def test_the_chapter_join_is_sound_and_total(entries):
    """Both directions. A one-way test misses the half that is interesting."""
    from verne80.normalize import place_key

    extractions = [
        FakeExtraction(number, places_visited=tuple(FakePlace(n) for n in names))
        for number, names in entries
    ]
    found = chapters_by_place(extractions)

    for key, numbers in found.items():
        for number in numbers:
            names = {
                place_key(p.name_in_text)
                for e in extractions
                if e.chapter == number
                for p in e.places_visited
            }
            assert key in names, "sound: a listed chapter really names the place"

    for extraction in extractions:
        for place in extraction.places_visited:
            key = place_key(place.name_in_text)
            if key:
                assert extraction.chapter in found[key], "total: no naming is missed"


@given(st.floats(0.0, 1.0, allow_nan=False, width=32))
@settings(max_examples=200)
def test_a_waypoint_on_its_own_arc_is_always_drawn(along):
    """A waypoint that really is on its leg survives the check, wherever it sits.

    The drift rule must only ever catch a contradiction. If some value of ``along``
    made a place fail its own arc, the rule would be silently deleting good pins.
    """
    spine = spine_from_nodes(["London", "Suez"], [7])
    lon, lat = interpolate_great_circle(LONDON, SUEZ, along)
    honest = row(
        "somewhere",
        kind="waypoint",
        leg="0",
        along=repr(along),
        lat=repr(lat),
        lon=repr(lon),
    )
    journey = journey_payload(spine, rows(row("london"), row("suez"), honest))
    payload = places_payload(rows(honest), legs=journey["legs"])
    assert [place["key"] for place in payload["places"]] == ["somewhere"]
    assert payload["places"][0]["km_from_leg"] == 0
