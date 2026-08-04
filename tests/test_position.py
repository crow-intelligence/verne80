import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.position import (
    Containment,
    PlaceKind,
    PositionSource,
    RoutePoint,
    TemporalClass,
    Track,
    check_positions,
    classify_mentions,
    coverage,
    load_tracks,
    resolve_positions,
)
from verne80.route import spine_from_nodes
from verne80.schema import ChapterExtraction

SPINE = spine_from_nodes(["London", "Suez", "Bombay", "London"], [7, 13, 60])

TRACKS = (
    Track("fogg", "Phileas Fogg", ("Phileas Fogg", "Mr. Fogg", "Fogg")),
    Track("passepartout", "Passepartout", ("Passepartout",)),
    Track("fix", "Fix", ("Fix", "Detective Fix")),
)

CONTAINMENT = {
    "london": Containment("london", "London", PlaceKind.NODE, (0, 3), confirmed=True),
    "suez": Containment("suez", "Suez", PlaceKind.NODE, (1,), confirmed=True),
    "bombay": Containment("bombay", "Bombay", PlaceKind.NODE, (2,), confirmed=True),
    "reform club": Containment(
        "reform club",
        "Reform Club",
        PlaceKind.MICRO,
        parent_key="london",
        confirmed=True,
    ),
    "saville row": Containment(
        "saville row",
        "Saville Row",
        PlaceKind.MICRO,
        parent_key="london",
        confirmed=True,
    ),
    "sydenham": Containment(
        "sydenham", "Sydenham", PlaceKind.WAYPOINT, leg=0, along=0.05, confirmed=True
    ),
    "india": Containment("india", "India", PlaceKind.OFF_ROUTE, confirmed=True),
}


def chapter(number, on_stage=(), mentioned=(), visited=()):
    return ChapterExtraction(
        chapter=number,
        summary_hover="Something happens.",
        summary_detail="Something happens. Then something else does.",
        places_visited=[
            {"name_in_text": n, "role": r, "evidence": "x"} for n, r in visited
        ],
        places_mentioned=[{"name_in_text": n, "evidence": "x"} for n in mentioned],
        narrative={
            "on_stage": [
                {"name_in_text": who, "evidence": f"{who} was there", **where}
                for who, where in on_stage
            ]
        },
    )


def resolve(extractions, chapters=None):
    return resolve_positions(extractions, SPINE, CONTAINMENT, TRACKS, chapters)


def row(entry, track):
    return next(r for r in entry.tracks if r.track == track)


class TestWhatSetsAPosition:
    def test_a_place_sets_the_position(self):
        out = resolve({1: chapter(1, [("Fogg", {"at_name_in_text": "Saville Row"})])})
        assert row(out[0], "fogg").point == RoutePoint(0, 0.0)
        assert row(out[0], "fogg").source is PositionSource.STATED

    def test_three_micro_locations_are_one_position(self):
        """Chapter 1 names a street, a club and a city: one place, three zooms."""
        out = resolve(
            {
                1: chapter(
                    1,
                    [
                        ("Fogg", {"at_name_in_text": "Saville Row"}),
                        ("Fogg", {"at_name_in_text": "Reform Club"}),
                        ("Fogg", {"at_name_in_text": "London"}),
                    ],
                )
            }
        )
        assert row(out[0], "fogg").point == RoutePoint(0, 0.0)

    def test_the_last_on_stage_entry_wins(self):
        """A chapter that moves someone ends where the chapter ends."""
        out = resolve(
            {
                3: chapter(
                    3,
                    [
                        ("Fogg", {"at_name_in_text": "Saville Row"}),
                        ("Fogg", {"at_name_in_text": "Sydenham"}),
                    ],
                )
            }
        )
        assert row(out[0], "fogg").place_name_in_text == "Sydenham"

    def test_a_chapter_the_party_is_absent_from_carries_forward(self):
        """Chapter 5: the scene is London, the party is not."""
        out = resolve(
            {
                4: chapter(4, [("Fogg", {"at_name_in_text": "Sydenham"})]),
                5: chapter(5, [("Rowan", {"at_name_in_text": "London"})]),
            }
        )
        fogg = row(out[1], "fogg")
        assert fogg.source is PositionSource.CARRIED
        assert fogg.point == RoutePoint(0, 0.05)
        assert fogg.stated_at_chapter == 4

    def test_a_detective_ahead_of_the_party_does_not_move_the_party(self):
        """Chapter 6: Fix reaches Suez first. Fogg must not be dragged along."""
        out = resolve(
            {
                4: chapter(4, [("Fogg", {"at_name_in_text": "Sydenham"})]),
                6: chapter(6, [("Fix", {"at_name_in_text": "Suez"})]),
            }
        )
        assert row(out[1], "fogg").point == RoutePoint(0, 0.05)
        assert row(out[1], "fix").point == RoutePoint(1, 0.0)

    def test_a_track_with_no_stated_position_yet_is_unknown_not_london(self):
        out = resolve({1: chapter(1, [("Fogg", {"at_name_in_text": "London"})])})
        fix = row(out[0], "fix")
        assert fix.point is None
        assert fix.source is PositionSource.UNKNOWN

    def test_a_transit_lands_between_its_ends(self):
        out = resolve(
            {
                1: chapter(
                    1, [("Fogg", {"between_from": "London", "between_to": "Bombay"})]
                )
            }
        )
        point = row(out[0], "fogg").point
        assert RoutePoint(0, 0.0) < point < RoutePoint(2, 0.0)

    def test_an_off_route_place_does_not_set_a_position(self):
        out = resolve({1: chapter(1, [("Fogg", {"at_name_in_text": "India"})])})
        assert row(out[0], "fogg").point is None

    def test_the_scene_is_kept_even_when_the_party_is_elsewhere(self):
        out = resolve({5: chapter(5, [("Rowan", {"at_name_in_text": "London"})])})
        assert out[0].scene_places == ("London",)

    def test_every_chapter_yields_a_row_for_every_track(self):
        out = resolve({1: chapter(1), 2: chapter(2)})
        assert [len(entry.tracks) for entry in out] == [3, 3]


class TestTheCycle:
    def test_the_two_londons_are_different_points(self):
        assert RoutePoint.at_node(0, 2) != RoutePoint.at_node(3, 2)

    def test_the_carried_position_disambiguates_london(self):
        """Early on, London is the start; after Bombay, it is the finish."""
        out = resolve(
            {
                1: chapter(1, [("Fogg", {"at_name_in_text": "London"})]),
                2: chapter(2, [("Fogg", {"at_name_in_text": "Bombay"})]),
                3: chapter(3, [("Fogg", {"at_name_in_text": "London"})]),
            }
        )
        assert row(out[0], "fogg").point == RoutePoint(0, 0.0)
        assert row(out[2], "fogg").point == RoutePoint(2, 1.0)

    def test_the_carried_position_never_supplies_a_place(self):
        """An unknown name resolves to nothing, however far along the party is."""
        out = resolve(
            {
                1: chapter(1, [("Fogg", {"at_name_in_text": "Bombay"})]),
                2: chapter(2, [("Fogg", {"at_name_in_text": "Timbuktu"})]),
            }
        )
        assert row(out[1], "fogg").source is PositionSource.CARRIED


class TestMentionedPlaceTime:
    def test_a_place_already_passed_is_past(self):
        extraction = chapter(2, mentioned=["London"])
        classes = classify_mentions(extraction, RoutePoint(1, 0.0), CONTAINMENT, SPINE)
        assert classes["London"] is TemporalClass.CYCLIC

    def test_a_place_still_ahead_is_future(self):
        extraction = chapter(1, mentioned=["Bombay"])
        classes = classify_mentions(extraction, RoutePoint(0, 0.0), CONTAINMENT, SPINE)
        assert classes["Bombay"] is TemporalClass.FUTURE

    def test_where_the_party_is_now_is_here(self):
        extraction = chapter(2, mentioned=["Suez"])
        classes = classify_mentions(extraction, RoutePoint(1, 0.0), CONTAINMENT, SPINE)
        assert classes["Suez"] is TemporalClass.HERE

    def test_london_is_cyclic_rather_than_forced(self):
        """Chapter 3's "due in London" means the return, not where they are standing."""
        extraction = chapter(3, mentioned=["London"])
        classes = classify_mentions(extraction, RoutePoint(1, 0.0), CONTAINMENT, SPINE)
        assert classes["London"] is TemporalClass.CYCLIC

    def test_a_region_is_off_route(self):
        extraction = chapter(9, mentioned=["India"])
        classes = classify_mentions(extraction, RoutePoint(1, 0.0), CONTAINMENT, SPINE)
        assert classes["India"] is TemporalClass.OFF_ROUTE

    def test_everything_is_unknown_before_the_party_is_placed(self):
        extraction = chapter(1, mentioned=["Bombay"])
        classes = classify_mentions(extraction, None, CONTAINMENT, SPINE)
        assert classes["Bombay"] is TemporalClass.UNKNOWN


class TestMonotonicityIsACheck:
    def test_a_regression_is_reported_not_corrected(self):
        """Verne doubles back for real; a resolver that fixed it would be lying."""
        out = resolve(
            {
                1: chapter(1, [("Fogg", {"at_name_in_text": "Bombay"})]),
                2: chapter(2, [("Fogg", {"at_name_in_text": "Suez"})]),
            }
        )
        assert row(out[1], "fogg").point == RoutePoint(1, 0.0)
        assert any("moves backwards" in line for line in check_positions(out, SPINE))

    def test_a_split_party_is_reported(self):
        out = resolve(
            {
                1: chapter(
                    1,
                    [
                        ("Fogg", {"at_name_in_text": "Bombay"}),
                        ("Passepartout", {"at_name_in_text": "Suez"}),
                    ],
                )
            }
        )
        assert any("apart from fogg" in line for line in check_positions(out, SPINE))

    def test_fix_running_ahead_is_reported(self):
        out = resolve(
            {
                1: chapter(
                    1,
                    [
                        ("Fogg", {"at_name_in_text": "London"}),
                        ("Fix", {"at_name_in_text": "Suez"}),
                    ],
                )
            }
        )
        assert any("ahead of fogg" in line for line in check_positions(out, SPINE))

    def test_a_clean_forward_run_reports_only_the_never_placed(self):
        out = resolve(
            {
                1: chapter(1, [("Fogg", {"at_name_in_text": "London"})]),
                2: chapter(2, [("Fogg", {"at_name_in_text": "Suez"})]),
            }
        )
        assert not [
            line for line in check_positions(out, SPINE) if "moves backwards" in line
        ]


class TestTheRoster:
    def test_the_committed_roster_has_the_three_tracks(self):
        assert [track.key for track in load_tracks()] == ["fogg", "passepartout", "fix"]

    def test_an_alias_matches_whatever_the_spelling(self):
        fogg = load_tracks()[0]
        assert fogg.matches("Mr. Fogg") and fogg.matches("PHILEAS FOGG")

    def test_someone_else_does_not_match(self):
        assert not load_tracks()[0].matches("Aouda")


class TestPositionProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=3))
    def test_a_node_point_is_always_on_the_spine(self, index, last_leg):
        point = RoutePoint.at_node(index, last_leg)
        assert 0 <= point.leg <= last_leg
        assert 0.0 <= point.along <= 1.0

    @settings(max_examples=150, deadline=None)
    @given(
        st.integers(min_value=0, max_value=2),
        st.floats(min_value=0.0, max_value=1.0),
        st.integers(min_value=0, max_value=2),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_a_midpoint_lies_between_its_ends(self, leg1, along1, leg2, along2):
        """Stated with the rounding tolerance, because `along` is rounded to six places.

        Hypothesis found that exact betweenness fails when the two ends differ by less
        than the rounding — around 1e-85, which is many orders of magnitude below
        anything this represents. Six places is the resolution the review CSV writes,
        so it is also the resolution the property can honestly claim.
        """
        one, other = RoutePoint(leg1, along1), RoutePoint(leg2, along2)
        low, high = sorted((one, other))
        middle = one.midpoint(other)
        scalar = middle.leg + middle.along
        assert low.leg + low.along - 1e-6 <= scalar <= high.leg + high.along + 1e-6

    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.integers(min_value=1, max_value=12), unique=True, max_size=6))
    def test_resolution_emits_a_row_for_every_chapter_and_track(self, numbers):
        out = resolve({n: chapter(n) for n in numbers})
        assert len(out) == len(numbers)
        assert all(len(entry.tracks) == len(TRACKS) for entry in out)

    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.integers(min_value=1, max_value=12), unique=True, max_size=6))
    def test_check_positions_never_raises(self, numbers):
        problems = check_positions(resolve({n: chapter(n) for n in numbers}), SPINE)
        assert all(isinstance(line, str) for line in problems)

    @settings(max_examples=100, deadline=None)
    @given(
        st.lists(
            st.integers(min_value=1, max_value=12), unique=True, min_size=1, max_size=6
        )
    )
    def test_carry_forward_is_idempotent(self, numbers):
        extractions = {
            n: chapter(n, [("Fogg", {"at_name_in_text": "Suez"})]) for n in numbers
        }
        first = resolve(extractions)
        second = resolve(extractions)
        assert [r.point for e in first for r in e.tracks] == [
            r.point for e in second for r in e.tracks
        ]

    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.integers(min_value=1, max_value=12), unique=True, max_size=6))
    def test_a_stated_position_always_names_a_place_the_chapter_used(self, numbers):
        extractions = {
            n: chapter(n, [("Fogg", {"at_name_in_text": "Suez"})]) for n in numbers
        }
        for entry in resolve(extractions):
            fogg = row(entry, "fogg")
            if fogg.source is PositionSource.STATED:
                assert fogg.place_name_in_text == "Suez"

    @settings(max_examples=100, deadline=None)
    @given(st.lists(st.integers(min_value=1, max_value=12), unique=True, max_size=6))
    def test_coverage_never_exceeds_the_chapter_count(self, numbers):
        stated, total = coverage(resolve({n: chapter(n) for n in numbers}), "fogg")
        assert 0 <= stated <= total == len(numbers)


class TestRealExtractions:
    """The five chapters that motivated the whole design, as assertions."""

    def test_chapter_five_does_not_move_fogg_back_to_london(self, real_positions):
        fogg = row(real_positions[4], "fogg")
        assert fogg.source is PositionSource.CARRIED
        assert fogg.stated_at_chapter == 4

    def test_fogg_is_carried_through_chapter_two(self, real_positions):
        assert row(real_positions[1], "fogg").source is PositionSource.CARRIED

    def test_fix_is_unknown_before_he_appears(self, real_positions):
        assert all(
            row(real_positions[n], "fix").source is PositionSource.UNKNOWN
            for n in range(5)
        )

    def test_chapter_four_leaves_london(self, real_positions):
        fogg = row(real_positions[3], "fogg")
        assert fogg.place_name_in_text == "Sydenham"
        assert fogg.point > RoutePoint(0, 0.0)

    def test_chapters_one_to_three_are_all_at_the_start(self, real_positions):
        assert all(
            row(real_positions[n], "fogg").point == RoutePoint(0, 0.0) for n in range(3)
        )


@pytest.fixture
def real_positions(real_spine):
    """Chapters 1-5 resolved against the committed data, skipping if it is not there."""
    from pathlib import Path

    from verne80.extractions import load_all

    loaded, problems = load_all(Path("data/extractions"), range(1, 6))
    if problems or len(loaded) != 5:
        pytest.skip("chapters 1-5 are not all pasted and valid")
    if any(not ex.narrative.on_stage for ex in loaded.values()):
        pytest.skip("chapters 1-5 predate the narrative block")

    containment = dict(CONTAINMENT)
    containment["house"] = Containment(
        "house", "house", PlaceKind.MICRO, parent_key="london", confirmed=True
    )
    containment["office"] = Containment(
        "office", "office", PlaceKind.MICRO, parent_key="london", confirmed=True
    )
    containment["charing cross"] = Containment(
        "charing cross",
        "Charing Cross",
        PlaceKind.MICRO,
        parent_key="london",
        confirmed=True,
    )
    return resolve_positions(loaded, real_spine, containment, TRACKS, sorted(loaded))
