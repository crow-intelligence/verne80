"""Shared fixtures.

``SYNTHETIC_RAW`` is the workhorse. It is a miniature Gutenberg document built to
contain every trap the real one does — CRLF line endings, a title page, a contents
block whose entries are indented, an illustration marker, hard-wrapped bodies, curly
quotation marks, an em dash, and a sentence that spans a line break — so most tests
can exercise a real failure mode without touching the network or the committed text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from verne80.chapters import Chapter, split_chapters, strip_gutenberg_boilerplate

REPO_ROOT = Path(__file__).resolve().parent.parent
PG103 = REPO_ROOT / "data" / "raw" / "pg103.txt"
CHAPTERS_DIR = REPO_ROOT / "data" / "chapters"

_LINES = [
    "The Project Gutenberg eBook of Around the World in Eighty Days",
    "",
    "*** START OF THE PROJECT GUTENBERG EBOOK AROUND THE WORLD ***",
    "",
    "[Illustration]",
    "",
    "Around the World in Eighty Days",
    "",
    "by Jules Verne",
    "",
    "Contents",
    "",
    " CHAPTER I. IN WHICH FOGG WAGERS",
    " CHAPTER II. IN WHICH THE MONGOLIA SAILS",
    " CHAPTER III. IN WHICH THE ELEPHANT IS BOUGHT",
    "",
    "",
    "CHAPTER I.",
    "IN WHICH FOGG WAGERS",
    "",
    "Mr. Phileas Fogg lived at No. 7, Saville Row. He said, “I will wager",
    "twenty thousand pounds that I make the tour of the world in eighty",
    "days.” The whist party stared at him—nobody spoke.",
    "",
    "CHAPTER II.",
    "IN WHICH THE MONGOLIA SAILS",
    "",
    "The Mongolia left Brindisi at five o’clock, and reached Suez in good",
    "time. Passepartout counted the days, and found that they had gained",
    "two days upon the itinerary.",
    "",
    "CHAPTER III.",
    "IN WHICH THE ELEPHANT IS BOUGHT",
    "",
    "They mounted upon the elephant, and set out across the forest. The",
    "beast was sold to him for two thousand pounds, which Mr. Fogg paid",
    "without a word.",
    "",
    "*** END OF THE PROJECT GUTENBERG EBOOK AROUND THE WORLD ***",
    "",
    "This eBook is for the use of anyone anywhere.",
]

# CRLF on purpose: the real download uses it, and every `$`-anchored pattern in the
# splitter would break on the stray carriage return if it were not normalised away.
SYNTHETIC_RAW = "\r\n".join(_LINES) + "\r\n"

# A passage that straddles a wrapped line in the fixture above. On one line here, as it
# would be in the extraction JSON — and therefore not a substring of the chapter file at
# all until the whitespace is collapsed. This is the single most common real failure.
WRAPPED_QUOTE = "across the forest. The beast was sold to him for two thousand pounds"


@pytest.fixture
def raw_text() -> str:
    return SYNTHETIC_RAW.replace("\r\n", "\n")


@pytest.fixture
def chapters(raw_text: str) -> list[Chapter]:
    return split_chapters(strip_gutenberg_boilerplate(raw_text))


@pytest.fixture
def chapters_dir(tmp_path: Path, chapters: list[Chapter]) -> Path:
    directory = tmp_path / "chapters"
    directory.mkdir()
    entries = []
    for chapter in chapters:
        (directory / f"chapter_{chapter.number:02d}.txt").write_text(
            chapter.to_text(), encoding="utf-8"
        )
        entries.append(
            {
                "number": chapter.number,
                "file": f"chapter_{chapter.number:02d}.txt",
                "title": chapter.title,
                "word_count": chapter.word_count,
            }
        )
    (directory / "index.json").write_text(
        json.dumps({"expected_chapters": len(chapters), "chapters": entries}),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def valid_extraction() -> dict:
    """An extraction for chapter 3 whose every quotation is really in the fixture."""
    return {
        "chapter": 3,
        "title": "IN WHICH THE ELEPHANT IS BOUGHT",
        "summary_hover": "Fogg buys an elephant and rides it across the forest.",
        "summary_detail": (
            "Fogg buys an elephant for two thousand pounds. The party mounts it and "
            "sets out across the forest. He pays without a word."
        ),
        "places_visited": [
            {
                "name_in_text": "the forest",
                "role": "passing_through",
                "evidence": "set out across the forest",
            }
        ],
        "places_mentioned": [],
        "people": [
            {
                "name_in_text": "Mr. Fogg",
                "role": "buys the elephant",
                "evidence": "which Mr. Fogg paid",
            }
        ],
        "transport": [
            {
                "mode": "elephant",
                "vessel_or_line_name": None,
                "from": None,
                "to": None,
                "evidence": WRAPPED_QUOTE,
            }
        ],
        "time": {
            "dates_mentioned": [],
            "days_elapsed_or_remaining": None,
            "schedule_status": "unknown",
            "schedule_detail": None,
            "evidence": None,
        },
        "money": {
            "amounts": [
                {
                    "amount_as_written": "two thousand pounds",
                    "purpose": "the elephant",
                    "evidence": "sold to him for two thousand pounds",
                }
            ],
            "fogg_remaining_stated": None,
        },
        "notes": None,
    }


@pytest.fixture
def pg103_raw() -> str:
    """The committed Gutenberg text, for the integration tests."""
    if not PG103.exists():
        pytest.skip("run `uv run python scripts/00_fetch.py` first")
    return PG103.read_text(encoding="utf-8").replace("\r\n", "\n")
