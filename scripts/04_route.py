"""Parse Fogg's own itinerary out of chapter 3, and assert it adds up.

The novel prints its own route: eight legs, a day count each, and a total underneath.
Because the legs must sum to that total, the text checks the parse rather than the other
way round — so this stage writes nothing unless the arithmetic agrees with the book.

Run: ``uv run python scripts/04_route.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

from verne80.chapters import chapter_path
from verne80.route import (
    check_spine,
    format_run_log,
    parse_itinerary,
    route_to_dict,
)

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_OUT = Path("data/processed/route_spine.json")
ITINERARY_CHAPTER = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse the chapter-3 itinerary table.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--chapter", type=int, default=ITINERARY_CHAPTER)
    args = parser.parse_args(argv)

    source = chapter_path(args.chapters_dir, args.chapter)
    if not source.exists():
        print(
            f"  FAIL  {source} not found — "
            "run `uv run python scripts/01_chapters.py` first",
            file=sys.stderr,
        )
        return 1

    text = source.read_text(encoding="utf-8")
    digest = sha256(text.encode("utf-8")).hexdigest()
    try:
        spine = parse_itinerary(text, chapter=args.chapter, source_sha256=digest)
    except ValueError as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1

    for line in format_run_log(spine):
        print(line)

    problems = check_spine(spine)
    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}", file=sys.stderr)
        print(f"  wrote nothing to {args.out}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(route_to_dict(spine), indent=2, ensure_ascii=False)
    args.out.write_text(payload + "\n", encoding="utf-8")
    print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
