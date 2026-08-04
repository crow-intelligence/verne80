import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.reviewmap import MapNode, map_payload, render_map, unwrap_eastward

NODES = [
    MapNode(0, "London", 51.51, -0.13),
    MapNode(1, "Yokohama", 35.45, 139.63),
    MapNode(2, "San Francisco", 37.77, -122.42),
]


def row(key, **cells):
    base = {
        "key": key,
        "name_in_text": key.title(),
        "kind": "node",
        "used_as": "visited:1",
        "first_chapter": "1",
        "confirmed": "",
        "lat": "",
        "lon": "",
        "confidence": "",
        "n_gazetteer_candidates": "0",
    }
    return {**base, **cells}


def payload_of(html):
    return json.loads(
        re.search(r"const DATA = (\{.*?\});\nconst KIND_STYLE", html, re.S).group(1)
    )


class TestTheRouteLine:
    def test_a_pacific_crossing_does_not_draw_backwards_across_asia(self):
        """The artefact would look exactly like the ordering error the map is for."""
        assert unwrap_eastward([139.6, -122.4]) == [139.6, 237.6]

    def test_a_route_that_never_wraps_is_left_alone(self):
        assert unwrap_eastward([-0.1, 32.5, 72.9]) == [-0.1, 32.5, 72.9]

    def test_going_right_round_ends_a_full_turn_on(self):
        lons = unwrap_eastward([-0.13, 32.53, 139.63, -122.42, -74.01, -0.13])
        assert lons[-1] > 350
        assert all(b >= a for a, b in zip(lons, lons[1:], strict=False))

    def test_the_route_line_follows_node_index_not_sorted_order(self):
        """Sorting would hide the very error the map exists to show."""
        route = map_payload([], NODES)["route"]
        assert [node["index"] for node in route] == [0, 1, 2]
        assert [node["name"] for node in route] == [
            "London",
            "Yokohama",
            "San Francisco",
        ]

    def test_a_node_with_no_coordinate_is_left_out_of_the_line(self):
        nodes = [*NODES, MapNode(3, "Kholby")]
        assert len(map_payload([], nodes)["route"]) == 3

    def test_an_empty_route_does_not_break_the_payload(self):
        assert map_payload([], [])["route"] == []


class TestWhatGetsAPin:
    def test_a_local_place_gets_no_pin(self):
        """It has no coordinate of its own; plotting one would be the lie."""
        payload = map_payload([row("station", kind="local")], NODES)
        assert payload["places"] == []
        assert [entry["name"] for entry in payload["locals"]] == ["Station"]

    def test_a_place_with_coordinates_is_plotted(self):
        payload = map_payload([row("suez", lat="29.97", lon="32.53")], NODES)
        assert payload["places"][0]["lat"] == 29.97

    def test_a_place_with_no_coordinates_is_listed_not_dropped(self):
        """Kholby is a real stop with no modern referent; losing it loses a stop."""
        payload = map_payload([row("kholby", kind="waypoint")], NODES)
        assert [entry["name"] for entry in payload["unresolved"]] == ["Kholby"]

    def test_every_row_lands_in_exactly_one_list(self):
        rows = [
            row("suez", lat="29.97", lon="32.53"),
            row("station", kind="local"),
            row("kholby", kind="waypoint"),
        ]
        payload = map_payload(rows, NODES)
        total = (
            len(payload["places"]) + len(payload["locals"]) + len(payload["unresolved"])
        )
        assert total == len(rows)

    def test_a_correction_overrides_the_proposed_kind(self):
        entry = row("suez", kind="unknown", corrected_kind="local")
        assert map_payload([entry], NODES)["locals"]

    def test_a_rename_is_carried_through(self):
        entry = row(
            "bombay", lat="19.07", lon="72.87", modern_name="Mumbai", name_changed="y"
        )
        place = map_payload([entry], NODES)["places"][0]
        assert place["modern"] == "Mumbai" and place["renamed"]


class TestThePage:
    def test_it_needs_no_network_at_build_time(self):
        """Everything is inline, so it opens from file:// with no server."""
        html = render_map(map_payload([row("suez", lat="29.97", lon="32.53")], NODES))
        assert "const DATA = {" in html
        assert "$payload" not in html and "$title" not in html

    def test_every_unconfirmed_place_is_marked(self):
        rows = [
            row("suez", lat="29.97", lon="32.53"),
            row("aden", lat="12.79", lon="45.03", confirmed="y"),
        ]
        payload = payload_of(render_map(map_payload(rows, NODES)))
        marked = {entry["name"]: entry["confirmed"] for entry in payload["places"]}
        assert marked == {"Suez": False, "Aden": True}

    def test_the_counts_are_in_the_payload(self):
        payload = map_payload([row("suez", lat="1", lon="2", confidence="0.4")], NODES)
        assert payload["counts"]["doubtful"] == 1

    def test_the_attribution_survives_into_the_page(self):
        html = render_map(map_payload([], NODES))
        assert "OpenStreetMap" in html and "Wikidata" in html and "CC0" in html

    def test_the_leaflet_version_is_pinned(self):
        assert "leaflet@1.9.4" in render_map(map_payload([], NODES))


class TestReviewMapProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.lists(st.floats(min_value=-180, max_value=180), max_size=12))
    def test_no_step_ever_goes_more_than_half_the_world_west(self, lons):
        out = unwrap_eastward(lons)
        assert all(b - a >= -180.0 for a, b in zip(out, out[1:], strict=False))

    @settings(max_examples=150, deadline=None)
    @given(st.lists(st.floats(min_value=-180, max_value=180), max_size=12))
    def test_every_point_moves_by_a_whole_number_of_turns(self, lons):
        for original, shifted in zip(lons, unwrap_eastward(lons), strict=True):
            turns = (shifted - original) / 360.0
            assert abs(turns - round(turns)) < 1e-6

    @settings(max_examples=150, deadline=None)
    @given(st.lists(st.floats(min_value=-180, max_value=180), min_size=1, max_size=12))
    def test_the_first_point_never_moves(self, lons):
        assert unwrap_eastward(lons)[0] == lons[0]

    @settings(max_examples=100, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.text(alphabet="abcde", min_size=1, max_size=4),
                st.sampled_from(["node", "waypoint", "micro", "local", "unknown"]),
            ),
            max_size=8,
            unique_by=lambda pair: pair[0],
        )
    )
    def test_rendering_never_raises_and_always_embeds(self, rows):
        entries = [row(key, kind=kind) for key, kind in rows]
        html = render_map(map_payload(entries, NODES))
        assert "const DATA = {" in html
