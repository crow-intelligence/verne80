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
    REPO_ROOT / "src" / "verne80" / "people.json",
    REPO_ROOT / "src" / "verne80" / "tracks.json",
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
            summary = entry["summary"]
            assert summary["hover"] and summary["detail"]
            assert len(summary["hover"]) < len(summary["detail"])

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
class TestTheCastAsCommitted:
    def test_every_chapter_puts_somebody_on_stage(self, committed):
        for entry in committed["chapters"]["chapters"]:
            assert entry["present"], entry["chapter"]

    def test_the_counts_agree_with_the_lists(self, committed):
        for entry in committed["chapters"]["chapters"]:
            counts = entry["people_counts"]
            assert counts["present"] == len(entry["present"])
            assert counts["named_elsewhere"] == len(entry["named_elsewhere"])
            assert (
                counts["present_named"] + counts["present_roles"] == counts["present"]
            )
            places = entry["place_counts"]
            assert places["named"] == len(entry["places"])
            assert places["plotted"] == sum(1 for p in entry["places"] if p["plotted"])

    def test_chapter_24_prints_john_busby_and_files_him_under_bunsby(self, committed):
        """Gutenberg #103's own inconsistency, reconciled without being erased."""
        chapter = _chapter(committed, 24)
        busby = [one for one in chapter["present"] if one["key"] == "bunsby"]
        assert busby, "the pilot of the Tankadere should be on stage in chapter 24"
        assert busby[0]["name_in_text"] == "John Busby"
        assert busby[0]["display"] == "John Bunsby"

    def test_chapter_29_keeps_both_spellings_of_proctor(self, committed):
        chapter = _chapter(committed, 29)
        proctor = [one for one in chapter["present"] if one["key"] == "proctor"][0]
        assert proctor["also_printed"] == ["Stamp Proctor"]

    def test_chapter_26_lists_fix_and_the_detective_as_two_people(self, committed):
        keys = {one["key"] for one in _chapter(committed, 26)["present"]}
        assert {"fix", "detective"} <= keys

    def test_no_role_is_ever_given_a_persons_key(self, committed):
        """A role folded onto a person would merge nine engineers into one man."""
        kinds: dict[str, set[str]] = {}
        for entry in committed["chapters"]["chapters"]:
            for one in entry["present"] + entry["named_elsewhere"]:
                kinds.setdefault(one["key"], set()).add(one["kind"])
        assert not [key for key, seen in kinds.items() if len(seen) > 1]

    def test_the_globe_has_somewhere_to_turn_for_every_chapter(self, committed):
        for entry in committed["chapters"]["chapters"]:
            assert entry["focus"] is not None, entry["chapter"]
            assert entry["focus"]["from"] == "fogg"


@needs_data
class TestTheChapterPlacesAsCommitted:
    def test_every_plotted_place_exists_in_places_json(self, committed):
        """The join lives in one payload and is consumed against another.

        Nothing else would notice it rotting: a missing key is a dot that quietly
        fails to appear, not an error anybody sees.
        """
        drawn = {place["key"] for place in committed["places"]["places"]}
        for entry in committed["chapters"]["chapters"]:
            for place in entry["places"]:
                if place["plotted"]:
                    assert place["key"] in drawn, (entry["chapter"], place["key"])

    def test_a_held_back_place_gives_the_reason_places_json_gives(self, committed):
        listed = {e["key"]: e["reason"] for e in committed["places"]["listed"]}
        for entry in committed["chapters"]["chapters"]:
            for place in entry["places"]:
                if not place["plotted"] and place["key"] in listed:
                    assert place["reason"] == listed[place["key"]]

    def test_a_place_that_is_a_stop_is_marked_as_one(self, committed):
        nodes = {node["key"] for node in committed["journey"]["nodes"]}
        for entry in committed["chapters"]["chapters"]:
            for place in entry["places"]:
                assert place["on_route"] == (place["key"] in nodes)

    def test_every_class_the_data_uses_is_one_the_page_can_draw(self, committed):
        """Five marks are designed. A sixth class would render as nothing at all."""
        seen = {
            place["class"]
            for entry in committed["chapters"]["chapters"]
            for place in entry["places"]
        }
        assert seen <= {"here", "past", "future", "cyclic", "off_route", "unknown"}


@needs_data
def test_the_provenance_hashes_the_curation_files_too(committed):
    """tracks.json was read and not hashed: an edit without a rebuild was invisible."""
    hashed = {Path(entry["path"]).name for entry in committed["provenance"]["inputs"]}
    assert {"people.json", "tracks.json"} <= hashed


def _chapter(committed, number):
    return next(
        entry
        for entry in committed["chapters"]["chapters"]
        if entry["chapter"] == number
    )


@needs_data
def test_the_coastline_is_one_dissolved_multipolygon(committed):
    land = committed["land"]
    assert land["type"] == "MultiPolygon"
    assert len(land["coordinates"]) > 50
