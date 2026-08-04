"""Work out where Fogg, Passepartout and Fix are in every chapter.

Reads the confirmed place table and the narrative block of each extraction, and emits
one row per chapter per track — including the chapters where a track is off stage,
which say so and name the chapter their position was last stated in. That explicitness
is the whole point: chapter 5's scene is a police office in London while Fogg is on a
train to Paris, and a row that quietly repeated "London" would be asserting something
nobody wrote down.

Run: ``uv run python scripts/06_positions.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verne80.extractions import load_all
from verne80.position import (
    Containment,
    PlaceKind,
    check_positions,
    classify_mentions,
    coverage,
    format_run_log,
    load_tracks,
    positions_to_dict,
    resolve_positions,
)
from verne80.review import (
    MergeRefusedError,
    is_confirmed,
    is_rejected,
    merge_rows,
    summarise,
    write_table,
)
from verne80.review import read_table as read_review
from verne80.route import parse_itinerary

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_EXTRACTIONS_DIR = Path("data/extractions")
DEFAULT_PLACES = Path("data/review/places.csv")
DEFAULT_JSON = Path("data/processed/positions.json")
DEFAULT_CSV = Path("data/review/positions.csv")

COLUMNS = (
    "key",
    "chapter",
    "track",
    "leg",
    "along",
    "at_node",
    "place_name_in_text",
    "source",
    "stated_at_chapter",
    "flags",
    "evidence",
    "confirmed",
    "corrected_leg",
    "corrected_along",
    "note",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve per-chapter positions.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR)
    parser.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--out-csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--chapters", help="a selection like 1-13 (default: all pasted)"
    )
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

    if not args.places.exists():
        print(
            f"  FAIL  {args.places} not found — "
            "run `uv run python scripts/05_places.py` first",
            file=sys.stderr,
        )
        return 1
    containment = _load_containment(args.places)

    numbers = _wanted(args.chapters, args.extractions_dir)
    extractions, problems = load_all(args.extractions_dir, numbers)
    for problem in problems:
        print(f"  skip  {problem}")
    if not extractions:
        print("  FAIL  no extractions could be loaded", file=sys.stderr)
        return 1

    tracks = load_tracks()
    resolved = resolve_positions(
        extractions, spine, containment, tracks, sorted(extractions)
    )

    mentions = {
        entry.chapter: classify_mentions(
            extractions[entry.chapter],
            next((r.point for r in entry.tracks if r.track == "fogg"), None),
            containment,
            spine,
        )
        for entry in resolved
        if entry.chapter in extractions
    }

    for line in format_run_log(resolved, tracks):
        print(line)

    stated, total = coverage(resolved, "fogg")
    print("  ---")
    print(
        f"  {len(resolved)} chapters x {len(tracks)} tracks = "
        f"{len(resolved) * len(tracks)} rows   fogg stated in {stated} of {total}"
    )

    reported = check_positions(resolved, spine)
    for line in reported:
        print(f"  note  {line}")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        positions_to_dict(resolved, spine, mentions), indent=2, ensure_ascii=False
    )
    args.out_json.write_text(payload + "\n", encoding="utf-8")
    print(f"  wrote {args.out_json}")

    rows = _rows(resolved, spine)
    try:
        merged = merge_rows(read_review(args.out_csv, "key"), rows, "key", COLUMNS)
    except MergeRefusedError as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1
    write_table(merged, args.out_csv)
    print(f"  wrote {args.out_csv} ({summarise(merged)})")

    blocking = [
        line for line in reported if "does not resolve" in line or "cycle" in line
    ]
    for line in blocking:
        print(f"  FAIL  {line}", file=sys.stderr)
    return 1 if blocking else 0


def _wanted(spec: str | None, directory: Path) -> list[int]:
    """Which chapters to resolve: a selection like ``1-13,20``, or everything pasted."""
    if not spec:
        return sorted(
            int(p.stem.split("_")[1]) for p in directory.glob("chapter_*.json")
        )
    numbers: set[int] = set()
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            low, _, high = piece.partition("-")
            numbers.update(range(int(low), int(high) + 1))
        else:
            numbers.add(int(piece))
    return sorted(numbers)


def _load_containment(path: Path) -> dict[str, Containment]:
    """Read the confirmed place table into the map the resolver uses.

    A row rejected with no correction beside it becomes off-route: a place nobody
    vouched for does not get to move a pin.
    """
    table = read_review(path, "key")
    out: dict[str, Containment] = {}
    for key, row in table.rows.items():
        kind_cell = row.get("corrected_kind") or row.get("kind") or "unknown"
        if is_rejected(row.get("confirmed", "")) and not row.get("corrected_kind"):
            kind_cell = PlaceKind.OFF_ROUTE.value
        try:
            kind = PlaceKind(kind_cell)
        except ValueError:
            kind = PlaceKind.UNKNOWN
        indices = row.get("corrected_node_indices") or row.get("node_indices") or ""
        leg = row.get("corrected_leg") or row.get("leg") or ""
        along = row.get("corrected_along") or row.get("along") or ""
        out[key] = Containment(
            key=key,
            name_in_text=row.get("name_in_text", key),
            kind=kind,
            node_indices=tuple(int(i) for i in indices.split(";") if i.strip()),
            parent_key=(row.get("corrected_parent_key") or row.get("parent_key"))
            or None,
            leg=int(leg) if leg.strip() else None,
            along=float(along) if along.strip() else None,
            why=row.get("why", ""),
            confirmed=is_confirmed(row.get("confirmed", "")),
        )
    return out


def _rows(resolved, spine) -> list[dict[str, str]]:
    """Flatten the resolved series into review rows."""
    last_leg = len(spine.legs) - 1
    rows: list[dict[str, str]] = []
    for entry in resolved:
        for row in entry.tracks:
            at_node = ""
            if row.point is not None:
                if row.point.along == 0.0:
                    at_node = spine.nodes[row.point.leg].name_in_text
                elif row.point.leg == last_leg and row.point.along == 1.0:
                    at_node = spine.nodes[-1].name_in_text
            rows.append(
                {
                    "key": f"{entry.chapter:02d}:{row.track}",
                    "chapter": f"{entry.chapter:02d}",
                    "track": row.track,
                    "leg": "" if row.point is None else str(row.point.leg),
                    "along": "" if row.point is None else f"{row.point.along:.3f}",
                    "at_node": at_node,
                    "place_name_in_text": row.place_name_in_text or "",
                    "source": row.source.value,
                    "stated_at_chapter": (
                        ""
                        if row.stated_at_chapter is None
                        else f"{row.stated_at_chapter:02d}"
                    ),
                    "flags": " ".join(row.flags),
                    "evidence": (row.evidence or "")[:160],
                    "confirmed": "",
                    "corrected_leg": "",
                    "corrected_along": "",
                    "note": "",
                }
            )
    return rows


if __name__ == "__main__":
    sys.exit(main())
