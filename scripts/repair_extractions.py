"""Recover extraction files a language model wrote slightly wrong.

Two failures turn up in practice: a quotation mark the model left unescaped inside a
string, so the document stops being JSON partway through; and a field the schema
forbids,
which ``extra="forbid"`` catches on purpose.

**Dry run by default.** This edits hand-verified data, so the default is to show you
the change and let you decide. Pass ``--write`` to apply it. Because the extractions
are committed, ``git diff`` afterwards is the real review — and the evidence validator
is the independent check that a repaired quotation still matches its chapter, which is
the thing worth confirming rather than assuming.

Files that already parse and validate are never rewritten.

Run: ``uv run python scripts/repair_extractions.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verne80.repair import RepairResult, repair_file

DEFAULT_EXTRACTIONS_DIR = Path("data/extractions")
EXPECTED_CHAPTERS = 37
MAX_NAMED_FIELDS = 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair malformed extraction files.")
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR)
    parser.add_argument("--expected", type=int, default=EXPECTED_CHAPTERS)
    parser.add_argument("--chapters", help="a selection like 12,18,21 (default: all)")
    parser.add_argument(
        "--write",
        action="store_true",
        help="apply the repairs; without it nothing is written",
    )
    args = parser.parse_args(argv)

    numbers = _wanted(args.chapters, args.expected)
    results = [
        repair_file(args.extractions_dir / f"chapter_{number:02d}.json")
        for number in numbers
    ]

    unrecoverable: list[RepairResult] = []
    changed: list[RepairResult] = []
    for number, result in zip(numbers, results, strict=True):
        if result.problem:
            unrecoverable.append(result)
            print(f"  ch {number:02d}   CANNOT REPAIR   {result.problem}")
            continue
        if not result.changed:
            continue
        changed.append(result)
        print(f"  ch {number:02d}   {_describe(result)}")

    print("  ---")
    print(
        f"  {len(results)} files: {len(changed)} "
        f"{'changed' if args.write else 'would change'}, "
        f"{len(results) - len(changed) - len(unrecoverable)} already valid, "
        f"{len(unrecoverable)} unrecoverable"
    )

    if not args.write:
        if changed:
            print("  dry run — nothing written. Re-run with --write to apply.")
        return 1 if unrecoverable else 0

    for result in changed:
        result.path.write_text(result.text, encoding="utf-8")
        print(f"  wrote {result.path}")
    if changed:
        print("  now run `git diff data/extractions/` and read the repairs,")
        print(
            "  then `uv run python scripts/03_validate.py` to confirm nothing was lost"
        )

    for result in unrecoverable:
        print(f"  FAIL  {result.path}: {result.problem}", file=sys.stderr)
    return 1 if unrecoverable else 0


def _describe(result: RepairResult) -> str:
    """One line saying what a file needed."""
    parts = []
    if result.syntax_repaired:
        parts.append("syntax repaired")
    if result.dropped_fields:
        named = list(result.dropped_fields[:MAX_NAMED_FIELDS])
        if len(result.dropped_fields) > MAX_NAMED_FIELDS:
            named.append(f"… and {len(result.dropped_fields) - MAX_NAMED_FIELDS} more")
        parts.append(f"dropped {len(result.dropped_fields)} fields: {', '.join(named)}")
    return "   ".join(parts)


def _wanted(spec: str | None, expected: int) -> list[int]:
    """Which chapters to look at: a selection like ``12,18,21``, or all of them."""
    if not spec:
        return list(range(1, expected + 1))
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


if __name__ == "__main__":
    sys.exit(main())
