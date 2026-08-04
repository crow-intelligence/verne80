"""Resolve every place name to a modern entity, coordinates and a modern name.

Spec §2.3: store both names plus coordinates plus ``name_changed``, because the change
itself is the content. Wikidata answers, and its entity type does most of the
classification for free — it knows Nebraska is a state and Ogden is a city, which is the
work that would otherwise be three hundred hand decisions.

**The nine itinerary nodes bootstrap everything else.** Route proximity is the strongest
signal for telling one Ogden from another, and it needs coordinates to exist. So run the
nodes first — ``--only London --only Suez …``, nine requests — check them on the map,
and
every later name is scored against a route that is known rather than assumed.

Answers are cached and the cache is committed, so a re-run costs nothing and
``--offline``
works. The cache holds what Wikidata said, never what we concluded, so re-ranking after
the route improves is free.

Run: ``uv run python scripts/07_gazetteer.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verne80.gazetteer import (
    GazetteerCache,
    GazetteerClient,
    OfflineError,
    Resolution,
    resolve_place,
)
from verne80.normalize import place_key
from verne80.position import PlaceKind
from verne80.review import MergeRefusedError, merge_rows, read_table
from verne80.review import summarise as summarise_table
from verne80.review import write_table
from verne80.reviewmap import MapNode, map_payload, render_map
from verne80.route import parse_itinerary

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_PLACES = Path("data/review/places.csv")
DEFAULT_CACHE = Path("data/processed/gazetteer_cache.json")
DEFAULT_MAP = Path("data/review/places_map.html")
CURATED = (
    Path(__file__).resolve().parent.parent / "src" / "verne80" / "route_places.json"
)

# The columns the gazetteer adds. Everything else in the table belongs to 05_places.py or
# to a human, and merge_rows keeps both intact.
GAZETTEER_COLUMNS = (
    "modern_name",
    "name_changed",
    "qid",
    "lat",
    "lon",
    "entity_type",
    "country",
    "confidence",
    "n_gazetteer_candidates",
    "gazetteer_source",
    "gazetteer_why",
    "corrected_qid",
)

# Kinds that have no coordinate of their own by definition. Looking them up would spend a
# request to learn what the curation already recorded.
SKIP_KINDS = frozenset({PlaceKind.LOCAL.value, PlaceKind.OFF_ROUTE.value})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve places against Wikidata.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="resolve just this place; repeatable",
    )
    parser.add_argument(
        "--nodes", action="store_true", help="resolve the nine itinerary nodes"
    )
    parser.add_argument("--limit", type=int, help="stop after this many fetches")
    parser.add_argument(
        "--offline", action="store_true", help="use the cache only; never open a socket"
    )
    parser.add_argument(
        "--refresh", action="append", default=[], help="drop this key before resolving"
    )
    parser.add_argument(
        "--map",
        type=Path,
        nargs="?",
        const=DEFAULT_MAP,
        help="also write the review map, which is how errors actually get caught",
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

    table = read_table(args.places, "key")
    if not table.rows:
        print(
            f"  FAIL  {args.places} is empty — "
            "run `uv run python scripts/05_places.py` first",
            file=sys.stderr,
        )
        return 1

    cache = GazetteerCache.load(args.cache)
    for key in args.refresh:
        cache.entries.pop(key, None)
    client = GazetteerClient(cache=cache, offline=args.offline)

    wanted = _wanted(table, spine, args.only, args.nodes)
    if not wanted:
        print("  nothing to resolve with those filters", file=sys.stderr)
        return 1

    # Anchors come from whatever is already resolved, so the nine-node pass runs with
    # none and every pass after it is scored against a route that exists.
    anchors = _anchors(table)
    print(f"  {len(wanted)} places to resolve, {len(anchors)} route anchors known")

    resolutions: dict[str, Resolution] = {}
    for key in wanted:
        row = table.rows[key]
        if args.limit is not None and client.fetched >= args.limit:
            print(f"  stopped at --limit {args.limit}; re-run to continue")
            break
        try:
            answer = _resolve_row(client, row, anchors)
        except OfflineError as error:
            print(f"  FAIL  {error}", file=sys.stderr)
            cache.save()
            return 1
        resolutions[key] = answer
        print(f"  {_describe(row, answer)}")

    cache.save()
    print(f"  wrote {args.cache} ({client.fetched} requests made)")

    proposed = [
        {**table.rows[key], **_columns(resolutions[key])}
        if key in resolutions
        else dict(table.rows[key])
        for key in table.rows
    ]
    columns = tuple(table.columns) + tuple(
        column for column in GAZETTEER_COLUMNS if column not in table.columns
    )
    try:
        merged = merge_rows(table, proposed, "key", columns)
    except MergeRefusedError as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1
    write_table(merged, args.places)

    resolved = sum(1 for answer in resolutions.values() if answer.resolved)
    doubtful = sum(
        1
        for answer in resolutions.values()
        if answer.resolved and answer.confidence < 0.7
    )
    print("  ---")
    print(
        f"  {resolved} of {len(resolutions)} resolved, {doubtful} below 0.7 confidence"
    )
    print(f"  wrote {args.places} ({summarise_table(merged)})")

    if args.map:
        nodes = [
            MapNode(
                index=node.index,
                name=node.name_in_text,
                lat=_coord(merged.rows.get(node.key), "lat"),
                lon=_coord(merged.rows.get(node.key), "lon"),
            )
            for node in spine.nodes
        ]
        payload = map_payload(list(merged.rows.values()), nodes)
        args.map.parent.mkdir(parents=True, exist_ok=True)
        args.map.write_text(render_map(payload), encoding="utf-8")
        print(f"  wrote {args.map} — open it and look")
    return 0


def _coord(row, field: str) -> float | None:
    """One coordinate off a review row, or None when it never resolved."""
    if not row:
        return None
    value = row.get(field, "").strip()
    return float(value) if value else None


def _wanted(table, spine, only: list[str], nodes_only: bool) -> list[str]:
    """Which rows to resolve, in the order they should be done."""
    if only:
        keys = {place_key(name) for name in only}
        return [key for key in table.rows if key in keys]
    if nodes_only:
        node_keys = {node.key for node in spine.nodes}
        return [key for key in table.rows if key in node_keys]
    return [
        key
        for key, row in table.rows.items()
        if (row.get("corrected_kind") or row.get("kind")) not in SKIP_KINDS
    ]


def _anchors(table) -> list[tuple[float, float]]:
    """Coordinates already known, which is what later proximity is measured against."""
    out: list[tuple[float, float]] = []
    for row in table.rows.values():
        lat, lon = row.get("lat", ""), row.get("lon", "")
        if lat.strip() and lon.strip():
            out.append((float(lat), float(lon)))
    return out


def _resolve_row(client, row, anchors) -> Resolution:
    """Resolve one row, searching for the curated modern spelling when there is one."""
    hint = row.get("modern_hint", "").strip() or None
    candidates = client.lookup(hint or row["name_in_text"])
    return resolve_place(
        row["key"],
        row["name_in_text"],
        candidates,
        near=anchors,
        modern_hint=hint,
    )


def _columns(answer: Resolution) -> dict[str, str]:
    """The gazetteer's cells for one row."""
    return {
        "modern_name": answer.modern_name or "",
        "name_changed": "y" if answer.name_changed else "",
        "qid": answer.qid or "",
        "lat": f"{answer.lat:.5f}" if answer.lat is not None else "",
        "lon": f"{answer.lon:.5f}" if answer.lon is not None else "",
        "entity_type": answer.entity_type or "",
        "country": answer.country or "",
        "confidence": f"{answer.confidence:.2f}" if answer.resolved else "",
        "n_gazetteer_candidates": str(answer.n_candidates),
        "gazetteer_source": answer.source,
        "gazetteer_why": answer.why,
    }


def _describe(row, answer: Resolution) -> str:
    """One run-log line per place."""
    name = row["name_in_text"][:24]
    if not answer.resolved:
        return f"{name:<26} —          {answer.why[:60]}"
    renamed = " → " + answer.modern_name if answer.name_changed else ""
    return (
        f"{name:<26} {answer.confidence:.2f}  {answer.qid:<9} "
        f"{answer.lat:8.3f},{answer.lon:9.3f}{renamed}"
    )


if __name__ == "__main__":
    sys.exit(main())
