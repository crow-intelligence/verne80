"""Build ``web/index.html`` so the page says what it says before any script runs.

A crawler that executes no JavaScript used to read 107 words of this page. The chapter
summaries — two thousand nine hundred words of them — were in a payload the browser
fetched, and nowhere in the file. Google renders JavaScript; the crawlers that feed
language models generally do not.

So the page is generated now, from ``src/verne80/page_template.html`` and the payloads
``08_dashboard.py`` writes. Run this after that one, and commit both: the freshness test
fails if the committed page and its inputs have drifted apart.

The word count it prints at the end is the number this whole stage exists to move. Watch
it rather than trusting it.

Run: ``uv run python scripts/08_dashboard.py && uv run python scripts/10_page.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from verne80.page import (
    CHAPTERS_TEMPLATE,
    CHAPTERS_WORD_FLOOR,
    TEMPLATE,
    WORD_FLOOR,
    check_template,
    render,
    render_chapters,
    visible_text,
)

DEFAULT_DATA = Path("web/data")
DEFAULT_OUT = Path("web/index.html")

PAYLOADS = ("chapters", "journey", "places", "provenance")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the page.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--chapters-template", type=Path, default=CHAPTERS_TEMPLATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    missing = [name for name in PAYLOADS if not (args.data / f"{name}.json").exists()]
    if missing or not args.template.exists():
        for name in missing:
            print(
                f"  FAIL  {args.data / f'{name}.json'} not found — "
                "run scripts/08_dashboard.py first",
                file=sys.stderr,
            )
        if not args.template.exists():
            print(f"  FAIL  {args.template} not found", file=sys.stderr)
        return 1

    source = args.template.read_text(encoding="utf-8")
    chapters_source = args.chapters_template.read_text(encoding="utf-8")
    problems = check_template(source) + check_template(chapters_source)
    for problem in problems:
        print(f"  FAIL  {problem}", file=sys.stderr)
    if problems:
        return 1

    loaded = {
        name: json.loads((args.data / f"{name}.json").read_text(encoding="utf-8"))
        for name in PAYLOADS
    }
    page = render(
        loaded["chapters"],
        loaded["journey"],
        loaded["places"],
        loaded["provenance"],
        source,
    )
    summaries = render_chapters(loaded["chapters"], chapters_source)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    summaries_out = args.out.parent / "chapters" / "index.html"
    summaries_out.parent.mkdir(parents=True, exist_ok=True)
    summaries_out.write_text(summaries, encoding="utf-8")

    written = (
        (args.out, page, WORD_FLOOR),
        (summaries_out, summaries, CHAPTERS_WORD_FLOOR),
    )
    for path, text, _ in written:
        print(f"  wrote {path} ({len(text.encode()):,} bytes)")
    print("  ---")
    print(f"  chapters  {len(loaded['chapters']['chapters'])} written out in full")
    print(f"  stops     {len(loaded['journey']['nodes'])} in the itinerary")

    # The number this whole stage exists to move. Watch it rather than trusting it.
    short = False
    for path, text, floor in written:
        words = len(visible_text(text).split())
        print(f"  words     {words:>6,} in {path}  (floor {floor:,})")
        if words < floor:
            print(
                f"  FAIL  {path} says {words} words with JavaScript switched off — "
                "a block did not render",
                file=sys.stderr,
            )
            short = True
    return 1 if short else 0


if __name__ == "__main__":
    sys.exit(main())
