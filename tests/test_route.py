import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.strategies import itinerary_table, typographic_variant
from verne80.route import (
    EXPECTED_LEGS,
    EXPECTED_TOTAL_DAYS,
    check_spine,
    itinerary_block,
    parse_itinerary,
    spine_from_nodes,
    split_via,
)
from verne80.schema import TransportMode

# The printed form, complete with every trap: a wrapped first entry, ditto marks for the
# unit, an italicised via clause with a circumflex, and a parenthetical on one
# destination.
TABLE = """\
From London to Suez _viâ_ Mont Cenis and Brindisi, by rail and
steamboats ................. 7 days
From Suez to Bombay, by steamer .................... 13 ”
From Bombay to Yokohama (Japan), by steamer ......... 3 ”
From Yokohama to London, by steamer and rail ....... 57 ”
--------
Total ............................................ 80 days.”
"""


class TestTheItineraryTable:
    def test_the_ditto_mark_is_read_as_days(self):
        assert [leg.days for leg in parse_itinerary(TABLE).legs] == [7, 13, 3, 57]

    def test_a_wrapped_first_entry_is_joined(self):
        leg = parse_itinerary(TABLE).legs[0]
        assert leg.days == 7
        assert leg.modes == (TransportMode.RAILWAY, TransportMode.STEAMER)

    def test_the_via_clause_does_not_become_a_destination(self):
        leg = parse_itinerary(TABLE).legs[0]
        assert leg.destination.name_in_text == "Suez"
        assert leg.via_as_written == ("Mont Cenis", "Brindisi")

    def test_yokohama_japan_and_yokohama_are_one_node(self):
        spine = parse_itinerary(TABLE)
        assert spine.indices_named("Yokohama") == (3,)
        assert "Yokohama (Japan)" in spine.nodes[3].printed_forms
        # The parenthetical is the only difference, so the chain is intact.
        assert not [p for p in check_spine(spine) if "chain is broken" in p]

    def test_london_appears_twice_at_different_indices(self):
        assert parse_itinerary(TABLE).indices_named("London") == (0, 4)

    def test_a_place_not_on_the_route_returns_no_indices(self):
        assert parse_itinerary(TABLE).indices_named("Timbuktu") == ()

    def test_a_missing_total_line_raises(self):
        with pytest.raises(ValueError, match="no 'Total"):
            parse_itinerary(TABLE.split("--------")[0])

    def test_no_table_at_all_raises(self):
        with pytest.raises(ValueError, match="no itinerary table"):
            parse_itinerary("He said he would go round the world in eighty days.")

    def test_prose_far_from_the_table_is_not_joined_into_it(self):
        padded = TABLE.replace("--------", "x " * 1200 + "\n--------")
        with pytest.raises(ValueError, match="matched across prose"):
            itinerary_block(padded)

    def test_a_tampered_day_count_is_reported_not_swallowed(self):
        """The oracle: the legs must add up to the number printed beneath them."""
        problems = check_spine(parse_itinerary(TABLE.replace("13 ”", "14 ”", 1)))
        assert any("the legs add up to 81 days" in p for p in problems)

    def test_a_broken_chain_is_reported(self):
        problems = check_spine(
            parse_itinerary(TABLE.replace("From Suez to", "From Aden to"))
        )
        assert any("the chain is broken" in p for p in problems)

    def test_a_route_that_does_not_return_home_is_reported(self):
        problems = check_spine(spine_from_nodes(["London", "Suez", "Bombay"], [7, 13]))
        assert any("return to where it began" in p for p in problems)

    def test_a_repeated_interior_stop_is_reported(self):
        spine = spine_from_nodes(["London", "Suez", "Suez", "London"], [7, 0, 13])
        assert any("more than once mid-route" in p for p in check_spine(spine))

    def test_the_wrong_leg_count_is_reported(self):
        assert f"found 4 legs, expected {EXPECTED_LEGS}" in check_spine(
            parse_itinerary(TABLE)
        )


class TestSplitVia:
    def test_a_parenthetical_is_dropped(self):
        assert split_via("Yokohama (Japan)") == ("Yokohama", ())

    def test_an_italicised_via_is_recognised(self):
        assert split_via("Suez _viâ_ Mont Cenis") == ("Suez", ("Mont Cenis",))

    def test_a_plain_via_is_recognised(self):
        assert split_via("Suez via Brindisi") == ("Suez", ("Brindisi",))

    def test_a_destination_without_a_via_keeps_its_whole_name(self):
        assert split_via("San Francisco") == ("San Francisco", ())


class TestRealChapterThree:
    """Fogg reads the route out himself; this is the whole spine of the dashboard."""

    def test_the_real_table_yields_eight_legs(self, real_spine):
        assert len(real_spine.legs) == EXPECTED_LEGS
        assert len(real_spine.nodes) == EXPECTED_LEGS + 1

    def test_the_real_leg_days_sum_to_the_printed_eighty(self, real_spine):
        total = sum(leg.days for leg in real_spine.legs)
        assert total == real_spine.total_days_printed == EXPECTED_TOTAL_DAYS

    def test_london_is_at_both_ends(self, real_spine):
        assert real_spine.indices_named("London") == (0, 8)

    def test_the_route_is_the_one_everybody_knows(self, real_spine):
        assert [node.name_in_text for node in real_spine.nodes] == [
            "London",
            "Suez",
            "Bombay",
            "Calcutta",
            "Hong Kong",
            "Yokohama",
            "San Francisco",
            "New York",
            "London",
        ]

    def test_cumulative_days_match_the_printed_column(self, real_spine):
        assert real_spine.cumulative_days() == (0, 7, 20, 23, 36, 42, 64, 71, 80)

    def test_the_first_leg_names_its_own_waypoints(self, real_spine):
        assert real_spine.legs[0].via_as_written == ("Mont Cenis", "Brindisi")

    def test_check_spine_is_clean_on_the_real_text(self, real_spine):
        assert check_spine(real_spine) == []


class TestRouteSpineProperties:
    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(st.data())
    def test_parsing_is_invariant_under_typography(self, data):
        """Proves the ditto-mark and italics handling is deliberate, not lucky."""
        variant = data.draw(typographic_variant(TABLE, vary_space=False))
        assert [leg.days for leg in parse_itinerary(variant).legs] == [7, 13, 3, 57]

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(itinerary_table())
    def test_a_generated_table_round_trips(self, generated):
        text, names, days = generated
        spine = parse_itinerary(text)
        assert [leg.days for leg in spine.legs] == days
        assert [node.name_in_text for node in spine.nodes] == names

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(itinerary_table())
    def test_node_indices_are_unique_and_contiguous(self, generated):
        spine = parse_itinerary(generated[0])
        assert [node.index for node in spine.nodes] == list(range(len(spine.nodes)))

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(itinerary_table())
    def test_the_legs_reference_the_spine_s_own_nodes(self, generated):
        spine = parse_itinerary(generated[0])
        for leg in spine.legs:
            assert leg.origin is spine.nodes[leg.index]
            assert leg.destination is spine.nodes[leg.index + 1]

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(itinerary_table())
    def test_cumulative_days_end_at_the_total(self, generated):
        spine = parse_itinerary(generated[0])
        running = spine.cumulative_days()
        assert running[0] == 0
        assert running[-1] == sum(leg.days for leg in spine.legs)
        assert list(running) == sorted(running)

    @settings(max_examples=150, deadline=None)
    @given(st.lists(st.text(min_size=1, max_size=12), min_size=2, max_size=9))
    def test_a_repeated_name_returns_every_index(self, names):
        """The anti-cycle-collapse property: names never resolve to a single node."""
        spine = spine_from_nodes(names, [1] * (len(names) - 1))
        for name in names:
            found = spine.indices_named(name)
            assert len(found) == sum(1 for n in names if _same(n, name))
            assert list(found) == sorted(found)

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(itinerary_table())
    def test_check_spine_never_raises(self, generated):
        problems = check_spine(parse_itinerary(generated[0]))
        assert all(isinstance(problem, str) for problem in problems)


def _same(one: str, other: str) -> bool:
    from verne80.route import _node_key

    return _node_key(one) == _node_key(other)
