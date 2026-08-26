"""The committed payloads: still derivable from the inputs they claim to come from.

``web/data/*.json`` is committed because GitHub Pages serves what is in the repository
and there is no build step at deploy time. That buys a reviewable diff on every
gazetteer change and costs one thing: the files can drift from the CSV they were made
from, and nothing would say so. This is what says so.

It is exactly the failure that bit ``05_places.py`` — a stage quietly wrote a table with
a column missing, everything still ran, and the numbers just got worse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = REPO_ROOT / "web" / "data"
SCRIPTS = REPO_ROOT / "scripts"

PAYLOADS = ("journey", "places", "chapters", "land", "strings", "provenance")

INPUTS = (
    REPO_ROOT / "data" / "chapters" / "chapter_03.txt",
    REPO_ROOT / "data" / "review" / "places.csv",
    REPO_ROOT / "data" / "processed" / "positions.json",
    REPO_ROOT / "data" / "raw" / "ne_110m_land.geojson",
)

needs_data = pytest.mark.skipif(
    not all(path.exists() for path in INPUTS) or not WEB_DATA.exists(),
    reason="run scripts/00_fetch.py --only land and scripts/08_dashboard.py first",
)


@pytest.fixture(scope="module")
def committed():
    return {
        name: json.loads((WEB_DATA / f"{name}.json").read_text(encoding="utf-8"))
        for name in PAYLOADS
        if (WEB_DATA / f"{name}.json").exists()
    }


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    """Run the real script into a scratch directory, so the script is under test too."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        import importlib

        module = importlib.import_module("08_dashboard")
    finally:
        sys.path.remove(str(SCRIPTS))
    out = tmp_path_factory.mktemp("web-data")
    code = module.main(["--out", str(out)])
    assert code == 0, "the export refused to build from the committed inputs"
    return {
        name: json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        for name in PAYLOADS
    }


# ------------------------------------------------------------------- freshness


@needs_data
@pytest.mark.parametrize("name", PAYLOADS)
def test_the_committed_payload_still_matches_its_inputs(name, committed, rebuilt):
    assert name in committed, f"web/data/{name}.json is missing — re-run the export"
    assert committed[name] == rebuilt[name], (
        f"web/data/{name}.json is stale — run `uv run python scripts/08_dashboard.py` "
        "and commit the result alongside the change that caused it"
    )


@needs_data
def test_a_rebuild_with_nothing_changed_is_an_empty_diff(rebuilt):
    """No timestamps anywhere, so the committed files only move when the data does."""
    blob = json.dumps(rebuilt)
    assert "generated_at" not in blob


# ----------------------------------------------------- what the page relies on


@needs_data
class TestTheJourneyAsCommitted:
    def test_the_route_is_nine_stops_and_eight_legs(self, committed):
        journey = committed["journey"]
        assert len(journey["nodes"]) == 9
        assert len(journey["legs"]) == 8
        assert journey["total_days_printed"] == 80

    def test_london_is_both_the_start_and_the_end(self, committed):
        nodes = committed["journey"]["nodes"]
        assert nodes[0]["key"] == nodes[-1]["key"] == "london"
        assert nodes[0]["day"] == 0
        assert nodes[-1]["day"] == 80

    def test_every_stop_is_located_so_the_whole_route_draws(self, committed):
        assert all(node["lat"] is not None for node in committed["journey"]["nodes"])
        assert all(leg["arc"] for leg in committed["journey"]["legs"])

    def test_every_arc_meets_the_stops_it_joins(self, committed):
        journey = committed["journey"]
        by_index = {node["index"]: node for node in journey["nodes"]}
        for leg in journey["legs"]:
            start, end = by_index[leg["origin"]], by_index[leg["destination"]]
            assert leg["arc"][0] == [start["lon"], start["lat"]]
            assert leg["arc"][-1] == [end["lon"], end["lat"]]

    def test_the_arcs_are_labelled_schematic(self, committed):
        """The page has to be able to say what the lines are, and are not."""
        assert {leg["arc_is"] for leg in committed["journey"]["legs"]} == {
            "great_circle"
        }


@needs_data
class TestTheChaptersAsCommitted:
    def test_all_thirty_seven_chapters_appear_exactly_once(self, committed):
        numbers = [entry["chapter"] for entry in committed["chapters"]["chapters"]]
        assert numbers == list(range(1, 38))

    def test_every_chapter_carries_both_summary_lengths(self, committed):
        for entry in committed["chapters"]["chapters"]:
            english = entry["summary"]["en"]
            assert english["hover"] and english["detail"]
            assert len(english["hover"]) < len(english["detail"])

    def test_fix_is_absent_rather_than_in_london_before_he_appears(self, committed):
        """positions.json says `unknown`; the panel must not read that as a place."""
        early = [
            track
            for entry in committed["chapters"]["chapters"][:5]
            for track in entry["tracks"]
            if track["track"] == "fix"
        ]
        assert early, "fix should have a row in every chapter"
        assert all(track["source"] == "unknown" for track in early)
        assert all(track["lon"] is None and track["lat"] is None for track in early)

    def test_every_placed_track_sits_on_the_arc_that_was_drawn(self, committed):
        from verne80.globe import interpolate_great_circle

        legs = {leg["index"]: leg for leg in committed["journey"]["legs"]}
        placed = 0
        for entry in committed["chapters"]["chapters"]:
            for track in entry["tracks"]:
                if track["lon"] is None:
                    continue
                arc = legs[track["leg"]]["arc"]
                expected = interpolate_great_circle(arc[0], arc[-1], track["along"])
                assert [track["lon"], track["lat"]] == expected
                placed += 1
        assert placed > 100, "the positions should place most of 37 chapters x 3 tracks"


@needs_data
class TestThePlacesAsCommitted:
    def test_every_row_is_either_drawn_or_listed_with_a_reason(self, committed):
        places = committed["places"]
        assert (
            len(places["places"]) + len(places["listed"]) == places["counts"]["total"]
        )
        assert all(entry["reason"] for entry in places["listed"])

    def test_no_drawn_place_is_missing_its_coordinates(self, committed):
        for place in committed["places"]["places"]:
            assert place["lon"] is not None and place["lat"] is not None

    def test_the_default_layer_is_only_the_route(self, committed):
        """What opens on the page is the nineteen places two sources vouch for."""
        itinerary = [
            place
            for place in committed["places"]["places"]
            if place["tier"] == "itinerary"
        ]
        assert {place["kind"] for place in itinerary} == {"node", "waypoint"}

    def test_no_drawn_waypoint_contradicts_the_leg_it_is_placed_on(self, committed):
        legs = {leg["index"]: leg for leg in committed["journey"]["legs"]}
        from verne80.globe import DRIFT_RATIO, great_circle_km

        for place in committed["places"]["places"]:
            if place["kind"] != "waypoint" or place["leg"] is None:
                continue
            arc = legs[place["leg"]]["arc"]
            span = great_circle_km(arc[0], arc[-1])
            assert place["km_from_leg"] / span <= DRIFT_RATIO, place["name_in_text"]

    def test_queenstown_is_held_back_until_somebody_resolves_it(self, committed):
        """The curation puts it on the Atlantic leg. The gazetteer put it in Otago.

        This test is meant to be deleted. When a human writes the right QID into
        ``corrected_qid``, it will fail, and that failure is the signal that the fix
        landed — at which point the assertion becomes "queenstown is drawn".
        """
        held = {entry["key"]: entry for entry in committed["places"]["listed"]}
        assert held["queenstown"]["reason"] == "contradicts_its_leg"

    def test_kholby_is_listed_rather_than_silently_dropped(self, committed):
        """No modern place matches it. Missing is the right answer; absent is not."""
        keys = {entry["key"] for entry in committed["places"]["listed"]}
        assert "kholby" in keys


@needs_data
class TestTheProvenanceAsCommitted:
    def test_it_records_a_hash_for_every_input(self, committed):
        for entry in committed["provenance"]["inputs"]:
            assert entry["sha256"] and entry["bytes"]

    def test_the_counts_agree_with_the_payloads(self, committed):
        record, places = committed["provenance"], committed["places"]
        assert record["places"]["plotted"] == len(places["places"])
        assert record["route"]["nodes"] == len(committed["journey"]["nodes"])

    def test_it_says_out_loud_that_nothing_is_confirmed_yet(self, committed):
        """While it is true. When the review lands, flip this assertion round."""
        record = committed["provenance"]
        if record["places"]["confirmed"] == 0:
            assert any("confirmed by a" in note for note in record["warnings"])

    def test_it_says_the_arcs_are_schematic(self, committed):
        assert any(
            "great circles" in note for note in committed["provenance"]["warnings"]
        )


@needs_data
def test_the_coastline_is_one_dissolved_multipolygon(committed):
    land = committed["land"]
    assert land["type"] == "MultiPolygon"
    assert len(land["coordinates"]) > 50
