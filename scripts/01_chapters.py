"""Slice the raw novel into thirty-seven chapter files plus an index.

Nothing is written unless the split checks out completely. A half-written
``data/chapters/`` silently mismatched against committed extractions is the expensive
failure here, so the run either produces a clean set of thirty-seven files or produces
nothing at all and says what is wrong.

Run: ``uv run python scripts/01_chapters.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

from verne80.chapters import (
    build_index,
    chapter_path,
    check_chapters,
    read_raw,
    split_chapters,
    strip_gutenberg_boilerplate,
    toc_titles,
)
from verne80.normalize import match_key
from verne80.sources import BOOK

DEFAULT_CHAPTERS_DIR = Path("data/chapters")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Split #103 into 37 chapters.")
    parser.add_argument("--raw", type=Path, default=BOOK.path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    args = parser.parse_args(argv)

    try:
        raw_text = read_raw(args.raw)
    except (FileNotFoundError, ValueError) as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1
    raw_bytes = args.raw.stat().st_size
    raw_digest = sha256(args.raw.read_bytes()).hexdigest()

    index_path = args.out_dir / "index.json"
    if index_path.exists():
        previous = json.loads(index_path.read_text(encoding="utf-8"))
        if previous.get("source", {}).get("raw_sha256") not in (None, raw_digest):
            print("  WARN  data/raw has changed since the last split — committed")
            print("        extractions may no longer line up with these chapters")

    try:
        body = strip_gutenberg_boilerplate(raw_text)
        chapters = split_chapters(body)
    except ValueError as error:
        print(f"  FAIL  {error}", file=sys.stderr)
        return 1

    problems = check_chapters(chapters)
    problems.extend(_check_against_contents(body, chapters))
    if problems:
        for problem in problems:
            print(f"  FAIL  {problem}", file=sys.stderr)
        print(f"  wrote nothing to {args.out_dir}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for chapter in chapters:
        chapter_path(args.out_dir, chapter.number).write_text(
            chapter.to_text(), encoding="utf-8"
        )
        print(
            f"  ch {chapter.number:02d}   {chapter.word_count:5,} words  "
            f"{chapter.title[:58]}"
        )

    index = build_index(chapters, BOOK, raw_digest, raw_bytes)
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    print(
        f"  wrote {index_path} ({len(chapters)} chapters, "
        f"{index['total_words']:,} words)"
    )
    return 0


def _check_against_contents(body: str, chapters: list) -> list[str]:
    """Cross-check the body titles against the book's own table of contents."""
    printed = toc_titles(body)
    if len(printed) != len(chapters):
        return [
            f"table of contents lists {len(printed)} titles but "
            f"{len(chapters)} chapters were split — not cross-checking"
        ]
    return [
        f"chapter {chapter.number:02d} title does not match the table of contents: "
        f"{chapter.title[:50]!r} vs {expected[:50]!r}"
        for chapter, expected in zip(chapters, printed, strict=True)
        if match_key(chapter.title) != match_key(expected)
    ]


if __name__ == "__main__":
    sys.exit(main())
