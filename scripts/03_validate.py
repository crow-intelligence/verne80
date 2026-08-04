"""Validate the extractions: schema first, then every evidence quotation.

This is where the LLM half of the pipeline gets checked by the deterministic half. Each
extraction is parsed against the schema, run past the editorial checks, and then every
evidence quotation it carries is grepped back against the chapter it claims to come
from.

By default only a genuinely absent quotation fails the run. Capitalisation changes,
elisions and near misses reach the review queue as warnings but do not block: a report
that fails on punctuation is a report people learn to ignore. ``--strict`` blocks on
anything short of a clean match, for when you want the hard guarantee.

Run: ``uv run python scripts/03_validate.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verne80.chapters import chapter_path
from verne80.evidence import NormalisedChapter, check_chapter_quotes
from verne80.extractions import load_all
from verne80.report import (
    build_report,
    count_blocking,
    print_run_log,
    write_json_report,
    write_markdown,
)
from verne80.schema import check_extraction, is_stale

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_EXTRACTIONS_DIR = Path("data/extractions")
DEFAULT_REVIEW_DIR = Path("data/review")


def parse_chapter_selection(spec: str) -> list[int]:
    """Expand a selection like ``1-5,12`` into chapter numbers.

    Args:
        spec: A comma-separated list of numbers and inclusive ranges.

    Returns:
        The numbers, sorted and deduplicated.

    Raises:
        ValueError: If a piece is not a number or a range.

    Examples:
        >>> parse_chapter_selection("1-3,12")
        [1, 2, 3, 12]
    """
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the chapter extractions.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_REVIEW_DIR)
    parser.add_argument("--chapters", help="a selection like 1-5,12 (default: all)")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="just list the chapters not yet pasted, and stop",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="just list the chapters pasted before the narrative block existed",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on anything short of an exact or normalised match",
    )
    args = parser.parse_args(argv)

    index_path = args.chapters_dir / "index.json"
    if not index_path.exists():
        print(
            f"  FAIL  {index_path} not found — "
            "run `uv run python scripts/01_chapters.py` first",
            file=sys.stderr,
        )
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))
    titles = {int(entry["number"]): str(entry["title"]) for entry in index["chapters"]}

    wanted = parse_chapter_selection(args.chapters) if args.chapters else sorted(titles)
    unknown = [number for number in wanted if number not in titles]
    if unknown:
        print(f"  FAIL  no such chapter: {unknown}", file=sys.stderr)
        return 1

    if args.missing_only:
        return _report_missing(args.extractions_dir, wanted)

    if args.stale_only:
        return _report_stale(args.extractions_dir, wanted)

    extractions, problems = load_all(args.extractions_dir, wanted)
    checks = []
    for number in sorted(extractions):
        extraction = extractions[number]
        problems.extend(check_extraction(extraction, number, titles.get(number)))
        chapter = NormalisedChapter.from_text(
            number, chapter_path(args.chapters_dir, number).read_text(encoding="utf-8")
        )
        checks.extend(check_chapter_quotes(extraction, chapter))

    report = build_report(checks, problems)
    print_run_log(report)

    json_path = args.out_dir / "evidence_report.json"
    md_path = args.out_dir / "evidence_queue.md"
    write_json_report(report, json_path)
    write_markdown(report, md_path, args.chapters_dir)
    print(f"  wrote {md_path} ({len(report.unresolved)} items to fix)")
    print(f"  wrote {json_path}")

    for problem in problems:
        print(f"  FAIL  {problem}", file=sys.stderr)

    blocking = count_blocking(checks, strict=args.strict)
    if blocking:
        what = (
            "did not match cleanly" if args.strict else "do not appear in their chapter"
        )
        print(f"  FAIL  {blocking} quotes {what} — see {md_path}", file=sys.stderr)
    return 1 if problems or blocking else 0


def _report_stale(extractions_dir: Path, wanted: list[int]) -> int:
    """List the chapters extracted before the prompt carried a narrative block.

    Only files that exist are considered. A chapter nobody has pasted yet is not stale,
    it is absent, and ``--missing-only`` already answers that question — reporting both
    here would bury the five rows that matter under thirty-two that do not.
    """
    present = [
        number
        for number in wanted
        if (extractions_dir / f"chapter_{number:02d}.json").exists()
    ]
    loaded, problems = load_all(extractions_dir, present)
    for problem in problems:
        print(f"  skip  {problem}")
    stale = sorted(number for number, ex in loaded.items() if is_stale(ex))
    if not stale:
        print(f"  all {len(loaded)} pasted extractions carry a narrative block")
        return 0
    print(f"  {len(stale)} of {len(loaded)} pasted extractions predate the block:")
    for number in stale:
        print(
            f"    chapter {number:02d}   re-paste data/prompts/chapter_{number:02d}.txt"
        )
    return 1


def _report_missing(extractions_dir: Path, wanted: list[int]) -> int:
    """List the chapters whose extraction has not been pasted yet."""
    missing = [
        number
        for number in wanted
        if not (extractions_dir / f"chapter_{number:02d}.json").exists()
    ]
    if not missing:
        print(f"  all {len(wanted)} extractions are present")
        return 0
    print(f"  {len(missing)} of {len(wanted)} extractions not yet pasted:")
    for number in missing:
        print(f"    chapter {number:02d}   data/prompts/chapter_{number:02d}.txt")
    return 1


if __name__ == "__main__":
    sys.exit(main())
