"""Propose a route position for every place name the extractions use.

Every place the chapters name is classified — a stop the itinerary lists, somewhere
inside one, somewhere on a leg between two, or not a position at all — and each
proposal carries the one-line reason it was made. Then a human confirms or corrects
the table, because a gazetteer that nobody checked is how a route quietly acquires a
stop in the wrong ocean.

Re-running this after each batch of pasted chapters is safe: confirmations and
corrections are carried across, and if a merge ever looked like losing one the run
refuses to write.

Run: ``uv run python scripts/05_places.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from verne80.extractions import load_all
from verne80.normalize import place_key
from verne80.position import PlaceKind
from verne80.review import (
    MergeRefusedError,
    merge_rows,
    read_table,
    summarise,
    write_table,
)
from verne80.route import RouteSpine, parse_itinerary

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_EXTRACTIONS_DIR = Path("data/extractions")
DEFAULT_OUT = Path("data/review/places.csv")
CURATED = (
    Path(__file__).resolve().parent.parent / "src" / "verne80" / "route_places.json"
)

COLUMNS = (
    "key",
    "name_in_text",
    "first_chapter",
    "n_uses",
    "used_as",
    "kind",
    "node_indices",
    "parent_key",
    "leg",
    "along",
    "n_candidates",
    "modern_hint",
    "why",
    "confirmed",
    "corrected_kind",
    "corrected_node_indices",
    "corrected_parent_key",
    "corrected_leg",
    "corrected_along",
    "note",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose route positions for places.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--curated", type=Path, default=CURATED)
    args = parser.parse_args(argv)

    source = args.chapters_dir / "chapter_03.txt"
    if not source.exists():
        print(
            f"  FAIL  {source} not found — "
            "run `uv run python scripts/01_chapters.py` first",
            file=sys.stderr,
        )
        return 1
    spine = parse_itinerary(source.read_text(encoding="utf-8"))
    curated = json.loads(args.curated.read_text(encoding="utf-8"))

    uses = _collect_uses(args.extractions_dir)
    if not uses:
        print(
            f"  FAIL  no extractions found in {args.extractions_dir}", file=sys.stderr
        )
        return 1

    proposed = [_propose(key, use, spine, curated) for key, use in sorted(uses.items())]

    try:
        merged = merge_rows(read_table(args.out, "key"), proposed, "key", COLUMNS)
    except MergeRefusedError as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1

    counts = Counter(row["kind"] for row in merged.rows.values())
    parts = "   ".join(f"{count} {kind}" for kind, count in sorted(counts.items()))
    print(f"  {len(merged.rows)} place names   {parts}")
    write_table(merged, args.out)
    print(f"  wrote {args.out} ({summarise(merged)})")
    return 0


def _collect_uses(directory: Path) -> dict[str, dict[str, object]]:
    """Gather every place name the extractions use, and how each one was used.

    Loading goes through :func:`~verne80.extractions.load_all`, which already tolerates
    the fences and preamble Gemini sometimes wraps its JSON in, and which validates
    against the schema on the way. A file that will not load is reported and skipped
    rather than stopping the other thirty-six.
    """
    numbers = sorted(
        int(path.stem.split("_")[1]) for path in directory.glob("chapter_*.json")
    )
    loaded, problems = load_all(directory, numbers)
    for problem in problems:
        print(f"  skip  {problem}")

    uses: dict[str, dict[str, object]] = {}

    def note(name: str | None, chapter: int, how: str) -> None:
        if not name or not name.strip():
            return
        entry = uses.setdefault(
            place_key(name),
            {"name_in_text": name.strip(), "first_chapter": chapter, "how": Counter()},
        )
        entry["first_chapter"] = min(int(entry["first_chapter"]), chapter)
        counter = entry["how"]
        assert isinstance(counter, Counter)
        counter[how] += 1

    for number, extraction in sorted(loaded.items()):
        for place in extraction.places_visited:
            note(place.name_in_text, number, "visited")
        for place in extraction.places_mentioned:
            note(place.name_in_text, number, "mentioned")
        for item in extraction.narrative.on_stage:
            note(item.at_name_in_text, number, "on_stage")
            note(item.between_from, number, "on_stage")
            note(item.between_to, number, "on_stage")
    return uses


def _propose(
    key: str, use: dict[str, object], spine: RouteSpine, curated: dict
) -> dict[str, str]:
    """Classify one place name, with the reason recorded beside it."""
    name = str(use["name_in_text"])
    counter = use["how"]
    assert isinstance(counter, Counter)
    row = {
        "key": key,
        "name_in_text": name,
        "first_chapter": str(use["first_chapter"]),
        "n_uses": str(sum(counter.values())),
        "used_as": " ".join(f"{how}:{n}" for how, n in sorted(counter.items())),
        "kind": PlaceKind.UNKNOWN.value,
        "node_indices": "",
        "parent_key": "",
        "leg": "",
        "along": "",
        "n_candidates": "0",
        "modern_hint": "",
        "why": "",
        "confirmed": "",
        "note": "",
    }

    indices = spine.indices_named(name)
    if indices:
        row["kind"] = PlaceKind.NODE.value
        row["node_indices"] = ";".join(str(i) for i in indices)
        row["n_candidates"] = str(len(indices))
        row["why"] = (
            f"names route node {indices[0]}"
            if len(indices) == 1
            else f"names route nodes {' and '.join(map(str, indices))} — "
            "the route is a cycle"
        )
        return row

    # After the node check, so "London" is never local, and before micro, so a name that
    # is both a fixed interior and a generic one resolves as the generic.
    for entry in curated.get("local", []):
        if place_key(entry["name"]) == key:
            row["kind"] = PlaceKind.LOCAL.value
            row["why"] = entry["why"]
            return row

    for entry in curated.get("micro", []):
        if place_key(entry["name"]) == key:
            row["kind"] = PlaceKind.MICRO.value
            row["parent_key"] = place_key(entry["parent"])
            row["why"] = entry["why"]
            return row

    for entry in curated.get("waypoints", []):
        if place_key(entry["name"]) == key:
            row["kind"] = PlaceKind.WAYPOINT.value
            row["leg"] = str(entry["leg"])
            row["along"] = str(entry.get("along", 0.5))
            row["why"] = entry["why"]
            return row

    # Seeded from the oracle itself: the table's own via clause names these, in its
    # printed order, so a human confirms rather than invents.
    for leg in spine.legs:
        for position, via in enumerate(leg.via_as_written):
            if place_key(via) == key:
                row["kind"] = PlaceKind.WAYPOINT.value
                row["leg"] = str(leg.index)
                row["along"] = str(
                    round((position + 1) / (len(leg.via_as_written) + 1), 3)
                )
                row["why"] = (
                    f"named in the chapter-3 table's own via clause for leg {leg.index}"
                )
                return row

    for entry in curated.get("blocked", []):
        if place_key(entry["name"]) == key:
            row["kind"] = PlaceKind.OFF_ROUTE.value
            row["why"] = entry["why"]
            return row

    # A name Verne's translator invented, or transliterated past recognition. Both stay
    # `unknown` — the gazetteer decides what they are — but the note travels with them,
    # and the alias is the string the gazetteer will actually search for.
    for entry in curated.get("invented", []):
        if place_key(entry["name"]) == key:
            row["why"] = f"no modern referent: {entry['why']}"
            return row

    for entry in curated.get("aliases", []):
        if place_key(entry["name"]) == key:
            row["modern_hint"] = entry["modern"]
            row["why"] = f"1872 spelling of {entry['modern']}: {entry['why']}"
            return row

    row["why"] = "not on the route and not in route_places.json — for the gazetteer"
    return row


if __name__ == "__main__":
    sys.exit(main())
