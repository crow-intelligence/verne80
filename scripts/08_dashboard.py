"""Join the pipeline's four artefacts into the six files the globe reads.

Every ingredient already exists — Fogg's itinerary, the resolved places, the per-chapter
positions, the extracted summaries — and this is the join that has never been made. It
reads nothing from the network and decides nothing new; it puts things beside each other
and counts what it found.

**It warns, it does not refuse.** No place in ``places.csv`` has been confirmed by a
human yet, and gating the build on that would make the dashboard hostage to a review
that has not happened. So a zero-confirmation build is loud and legal, the counts travel
with the payload, and the page prints them above the fold rather than hiding them in a
footnote. What *does* stop the build is structural: a route with nothing to draw, a
chapter with no extraction, a position off the end of the itinerary. Those produce a
wrong page rather than an unchecked one.

Run: ``uv run python scripts/08_dashboard.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from verne80.basemap import land_payload
from verne80.extractions import load_all
from verne80.globe import (
    chapters_by_place,
    chapters_payload,
    journey_payload,
    places_payload,
    provenance,
)
from verne80.position import load_tracks
from verne80.review import read_table
from verne80.route import parse_itinerary
from verne80.sources import LAND
from verne80.strings import check_strings, strings_payload

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_EXTRACTIONS = Path("data/extractions")
DEFAULT_PLACES = Path("data/review/places.csv")
DEFAULT_POSITIONS = Path("data/processed/positions.json")
DEFAULT_OUT = Path("web/data")

EXPECTED_CHAPTERS = 37


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the globe's data files.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS)
    parser.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    parser.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    parser.add_argument("--land", type=Path, default=LAND.path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    chapter_three = args.chapters_dir / "chapter_03.txt"
    inputs = [chapter_three, args.places, args.positions, args.land]
    for path in inputs:
        if not path.exists():
            print(f"  FAIL  {path} not found — {_who_makes(path)}", file=sys.stderr)
            return 1

    text = chapter_three.read_text(encoding="utf-8")
    digest = hashlib.sha256(chapter_three.read_bytes()).hexdigest()
    spine = parse_itinerary(text, chapter=3, source_sha256=digest)

    table = read_table(args.places, "key")
    if not table.rows:
        print(
            f"  FAIL  {args.places} is empty — run scripts/05_places.py",
            file=sys.stderr,
        )
        return 1

    numbers = sorted(
        int(path.stem.split("_")[1])
        for path in args.extractions_dir.glob("chapter_*.json")
    )
    extractions, problems = load_all(args.extractions_dir, numbers)
    for problem in problems:
        print(f"  FAIL  {problem}", file=sys.stderr)
    missing = sorted(set(range(1, EXPECTED_CHAPTERS + 1)) - set(extractions))
    if problems or missing:
        if missing:
            print(f"  FAIL  no extraction for chapter(s) {missing}", file=sys.stderr)
        return 1

    positions = json.loads(args.positions.read_text(encoding="utf-8"))
    tracks = load_tracks()

    journey = journey_payload(spine, table.rows)
    places = places_payload(
        table.rows, chapters_by_place(extractions.values()), journey["legs"]
    )
    chapters = chapters_payload(extractions, positions, journey["legs"], tracks)
    land = land_payload(json.loads(args.land.read_text(encoding="utf-8")))
    strings = strings_payload()

    blocking = _blocking(journey, chapters, table.rows)
    for line in blocking:
        print(f"  FAIL  {line}", file=sys.stderr)
    if blocking:
        return 1

    warnings = _warnings(places["counts"], journey, places["listed"])
    record = provenance(inputs, places["counts"], journey, warnings)

    written = _write(
        args.out,
        journey=journey,
        places=places,
        chapters=chapters,
        land=land,
        strings=strings,
        provenance=record,
    )

    for name, path, size in written:
        print(f"  wrote {path} ({size:,} bytes)  {name}")

    counts = places["counts"]
    print("  ---")
    print(
        f"  route     {record['route']['nodes_located']} of "
        f"{record['route']['nodes']} stops located, "
        f"{record['route']['legs_drawn']} of {record['route']['legs']} legs drawn"
    )
    print(
        f"  places    {counts['plotted']} plotted of {counts['total']} "
        f"({', '.join(f'{n} {tier}' for tier, n in counts['by_tier'].items())})"
    )
    print(
        f"  held back {counts['listed']} "
        f"({', '.join(f'{n} {why}' for why, n in counts['by_reason'].items())})"
    )
    print(f"  chapters  {len(chapters['chapters'])}, {len(chapters['tracks'])} tracks")

    for problem in check_strings():
        print(f"  strings   {problem}", file=sys.stderr)

    if warnings:
        print("  ---")
        for warning in warnings:
            print(f"  NOTE  {warning}")
    return 0


def _blocking(journey, chapters, rows) -> list[str]:
    """The conditions that make a wrong page rather than an unchecked one."""
    problems = []

    located = [node for node in journey["nodes"] if node["lat"] is not None]
    if len(located) < 2:
        problems.append(
            f"only {len(located)} of {len(journey['nodes'])} stops have coordinates — "
            "there is no route to draw; run scripts/07_gazetteer.py --nodes"
        )

    for node in journey["nodes"]:
        if node["status"] == "rejected":
            problems.append(
                f"stop {node['index']} ({node['name_in_text']}) is marked rejected in "
                "places.csv, so the itinerary has a hole in it — put the right QID in "
                "corrected_qid rather than leaving it at 'n'"
            )

    last_leg = len(journey["legs"]) - 1
    for chapter in chapters["chapters"]:
        for track in chapter["tracks"]:
            leg, along = track["leg"], track["along"]
            if leg is not None and not 0 <= leg <= last_leg:
                problems.append(
                    f"chapter {chapter['chapter']} puts {track['track']} on leg {leg}, "
                    f"outside 0..{last_leg}"
                )
            if along is not None and not 0.0 <= along <= 1.0:
                problems.append(
                    f"chapter {chapter['chapter']} puts {track['track']} at along="
                    f"{along}, outside 0..1"
                )

    for key, row in rows.items():
        leg = (row.get("corrected_leg") or row.get("leg", "")).strip()
        if leg and not leg.lstrip("-").isdigit():
            problems.append(
                f"place {key!r} has a leg of {leg!r}, which is not a number"
            )
    return problems


def _warnings(counts, journey, listed) -> list[str]:
    """What the reader of the page has to be told, in the page's own words."""
    warnings = []
    if not counts["confirmed"]:
        warnings.append(
            f"none of the {counts['total']} place rows has been confirmed by a "
            "human — every pin on the globe is drawn with a broken ring, which is "
            "honest and is meant to be temporary; see data/review/places_to_check.md"
        )
    elif counts["confirmed"] < counts["plotted"]:
        warnings.append(
            f"{counts['plotted'] - counts['confirmed']} of the {counts['plotted']} "
            "drawn places are still unchecked"
        )
    if counts["doubtful"]:
        warnings.append(
            f"{counts['doubtful']} of the {counts['plotted']} drawn places resolved "
            "below the confidence we trust, and are marked as doubtful"
        )
    unlocated = counts["by_reason"].get("none_found", 0) + counts["by_reason"].get(
        "not_queried", 0
    )
    if unlocated:
        warnings.append(
            f"{unlocated} names the book uses have no coordinate — some of them, like "
            "Kholby, have no modern place to match, and a blank is the right answer"
        )
    strayed = [
        entry for entry in listed if entry.get("reason") == "contradicts_its_leg"
    ]
    for entry in strayed:
        warnings.append(
            f"{entry['name_in_text']} is not drawn: the curation puts it on leg "
            f"{entry.get('leg')}, and the gazetteer put it {entry['detail']}. One of "
            "the two is wrong — put the right QID in corrected_qid in places.csv, or "
            "write n in confirmed to drop it for good"
        )
    if any(leg["arc_is"] for leg in journey["legs"]):
        warnings.append(
            "the arcs are great circles between the stops Fogg's table names, not the "
            "routes the ships and trains took — the page has to say so"
        )
    return warnings


def _write(out: Path, **payloads) -> list[tuple[str, Path, int]]:
    """Write each payload, and report what landed where."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in payloads.items():
        path = out / f"{name}.json"
        # Trailing newline and stable key order so a rebuild with nothing changed is an
        # empty diff, which is what makes the committed files reviewable.
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        path.write_text(blob + "\n", encoding="utf-8")
        written.append((name, path, len(blob) + 1))
    return written


def _who_makes(path: Path) -> str:
    """Which stage produces a missing input, so the error names its own fix."""
    stage = {
        "chapter_03.txt": "run scripts/01_chapters.py",
        "places.csv": "run scripts/05_places.py then scripts/07_gazetteer.py",
        "positions.json": "run scripts/06_positions.py",
        "ne_110m_land.geojson": "run scripts/00_fetch.py --only land",
    }
    return stage.get(path.name, "check the path")


if __name__ == "__main__":
    sys.exit(main())
