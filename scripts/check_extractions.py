"""Pre-flight sweep over the pasted extraction files.

The first thing to run after a paste session, and deliberately independent of the schema
so it still answers on files too broken for the real validator. Four questions:

- Are all thirty-seven there, and is any of them empty?
- Does each one parse?
- Does the number in the filename match the ``"chapter"`` key inside it?
- Do any two files claim the same chapter?

The third is the one worth having. Everything downstream joins an extraction to a
chapter by its *filename* — the prompt embedded ``chapter_22.txt``, the evidence
validator greps ``chapter_22.txt`` — so a file saved under the wrong name would attach
one chapter's quotations to another's text, and every one of them would fail the
evidence check at once with no hint as to why. This says why.

Silent when everything is well. Run: ``uv run python scripts/check_extractions.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verne80.extractions import check_extraction_files

DEFAULT_EXTRACTIONS_DIR = Path("data/extractions")
EXPECTED_CHAPTERS = 37


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanity-check the extraction files.")
    parser.add_argument("--extractions-dir", type=Path, default=DEFAULT_EXTRACTIONS_DIR)
    parser.add_argument("--expected", type=int, default=EXPECTED_CHAPTERS)
    args = parser.parse_args(argv)

    if not args.extractions_dir.is_dir():
        print(f"  FAIL  {args.extractions_dir} is not a directory", file=sys.stderr)
        return 1

    problems = check_extraction_files(args.extractions_dir, args.expected)
    for problem in problems:
        print(f"  {problem}")
    if problems:
        print("  ---")

    counts = {
        word: sum(1 for problem in problems if word in problem)
        for word in ("MISSING", "EMPTY", "MALFORMED", "MISMATCH", "DUPLICATE")
    }
    parses = args.expected - counts["MISSING"] - counts["EMPTY"] - counts["MALFORMED"]
    print(
        f"  {args.expected} expected: {parses} parse, {counts['MALFORMED']} malformed, "
        f"{counts['EMPTY']} empty, {counts['MISSING']} missing, "
        f"{counts['MISMATCH']} chapter-key mismatches, "
        f"{counts['DUPLICATE']} duplicated"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
