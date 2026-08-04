r"""Split the raw Gutenberg download into thirty-seven chapters, or say why not.

The classic failure mode when slicing a Gutenberg text is catching the table of contents
as well as the body, and quietly producing seventy-four chapters instead of
thirty-seven. This module is built so that cannot happen silently, in three layers:

**Anchoring.** In #103 the body headings sit at column zero with nothing after the roman
numeral — ``CHAPTER I.`` — while every table-of-contents entry is indented by one space
and carries its title on the same line. A pattern anchored at column zero that permits
nothing after the numeral therefore cannot match a contents line at all.

**Slicing.** :func:`strip_front_matter` cuts everything before the first body heading,
which removes the title page, the contents block and the illustration marker in one
move.

**Assertion.** :func:`check_chapters` returns a list of human-readable problems, and the
stage script refuses to write anything if that list is non-empty. Wrong is reported,
never guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import median

from verne80.normalize import normalize_quote
from verne80.sources import GutenbergSource

__all__ = [
    "CHAPTER_HEADING",
    "EXPECTED_CHAPTERS",
    "MAX_WORDS",
    "MIN_WORDS",
    "TOC_LINE",
    "Chapter",
    "build_index",
    "chapter_path",
    "check_chapters",
    "int_to_roman",
    "read_raw",
    "roman_to_int",
    "split_chapters",
    "strip_front_matter",
    "strip_gutenberg_boilerplate",
    "toc_titles",
]

EXPECTED_CHAPTERS = 37

# Length guards, set against the real distribution: chapters run 777 to 3,869 words, and
# 0.46x to 2.28x the median. The bands are wide enough that no real chapter trips them
# and tight enough that a captured contents line (about fifteen words) does.
MIN_WORDS = 400
MAX_WORDS = 6000
RATIO_BAND = (0.25, 4.0)

# Real titles occupy one or two lines; four is slack, not an expectation.
MAX_TITLE_LINES = 4

# Anchored at column zero with nothing permitted after the numeral. Both halves of that
# are load-bearing — see the module docstring.
CHAPTER_HEADING = re.compile(r"^CHAPTER[ \t]+([IVXLC]+)\.[ \t]*$", re.MULTILINE)
# The contents block puts the numeral and the whole title on one indented line — the
# mirror image of a body heading, and the reason anchoring alone separates the two.
TOC_LINE = re.compile(r"^[ \t]+CHAPTER[ \t]+([IVXLC]+)\.[ \t]+(\S.*)$", re.MULTILINE)

GUTENBERG_START = re.compile(
    r"^\*\*\*\s*START OF (?:THE |THIS )?PROJECT GUTENBERG.*$",
    re.IGNORECASE | re.MULTILINE,
)
GUTENBERG_END = re.compile(
    r"^\*\*\*\s*END OF (?:THE |THIS )?PROJECT GUTENBERG.*$",
    re.IGNORECASE | re.MULTILINE,
)

_ROMAN_VALUES = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


@dataclass(frozen=True, slots=True)
class Chapter:
    """One chapter of the novel, as split out of the raw text.

    Attributes:
        number: The chapter number, decoded from its roman numeral.
        title: The printed title, joined onto one line. ALL CAPS, as in the source.
        body: The chapter text, with the heading and title removed.
    """

    number: int
    title: str
    body: str

    @property
    def word_count(self) -> int:
        """How many whitespace-separated tokens the body holds.

        Returns:
            The token count.

        Examples:
            >>> Chapter(1, "A TITLE", "one two  three").word_count
            3
        """
        return len(self.body.split())

    @property
    def first_line(self) -> str:
        r"""The first non-empty line of the body, as printed.

        A cheap sanity check that the split landed where it should: if this is a title
        or a contents entry rather than prose, the split is wrong.

        Returns:
            The line, stripped, or the empty string if the body has no content.

        Examples:
            >>> body = "\n\n  Mr. Phileas Fogg lived\nin 1872."
            >>> Chapter(1, "A TITLE", body).first_line
            'Mr. Phileas Fogg lived'
        """
        for line in self.body.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def to_text(self) -> str:
        """Render the chapter as it is written to ``chapter_NN.txt``.

        The number and title come first, then a blank line, then the body — which is the
        form the extraction prompt embeds and the evidence validator greps.

        Returns:
            The file contents, ending in a single newline.

        Examples:
            >>> print(Chapter(7, "IN WHICH SUEZ", "The Mongolia sailed.").to_text())
            CHAPTER 07
            IN WHICH SUEZ
            <BLANKLINE>
            The Mongolia sailed.
            <BLANKLINE>
        """
        return f"CHAPTER {self.number:02d}\n{self.title}\n\n{self.body}\n"


def read_raw(path: Path) -> str:
    r"""Read the raw download and normalise its line endings.

    Gutenberg serves CRLF. Every ``$``-anchored pattern in this module would otherwise
    see a stray carriage return before the end of line and fail to match, so this
    conversion is not cosmetic.

    Args:
        path: The file to read, normally ``data/raw/pg103.txt``.

    Returns:
        The decoded text with ``\n`` line endings.

    Raises:
        FileNotFoundError: If the file does not exist, naming the stage that creates it.

    Contract:
        - The result contains no ``\r``.
        - Decoding is attempted as UTF-8, then UTF-8 with BOM, then Latin-1, so a
          re-encoded edition still loads rather than raising.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run `uv run python scripts/00_fetch.py` first"
        )
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return text.replace("\r\n", "\n").replace("\r", "\n")
    raise ValueError(f"{path} could not be decoded as UTF-8, UTF-8-BOM or Latin-1")


def strip_gutenberg_boilerplate(text: str) -> str:
    r"""Cut everything outside the START and END markers.

    A missing marker means the edition's framing has changed, which is exactly when
    downstream slicing is most likely to go quietly wrong — so this raises rather than
    carrying on with the licence text attached.

    Args:
        text: The full raw download.

    Returns:
        The text between the markers, stripped.

    Raises:
        ValueError: If either marker is absent.

    Contract:
        - The result contains neither marker line.
        - Raises, rather than passing through, on text whose markers are already
          gone — a missing marker is the signal, not a no-op.

    Examples:
        >>> raw = "front\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody\n"
        >>> raw += "*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicence"
        >>> strip_gutenberg_boilerplate(raw)
        'body'
    """
    start = GUTENBERG_START.search(text)
    if start is None:
        raise ValueError(
            "no '*** START OF THE PROJECT GUTENBERG EBOOK ***' marker — "
            "the edition's framing has changed; re-check the download"
        )
    end = GUTENBERG_END.search(text, start.end())
    if end is None:
        raise ValueError(
            "no '*** END OF THE PROJECT GUTENBERG EBOOK ***' marker — "
            "the download may be truncated"
        )
    return text[start.end() : end.start()].strip()


def strip_front_matter(text: str) -> str:
    """Drop everything before the first body chapter heading.

    This one slice removes the title page, the ``Contents`` block and the illustration
    marker together, because none of them can contain a column-zero heading.

    Args:
        text: The de-boilerplated text.

    Returns:
        The text from the first chapter heading onwards.

    Raises:
        ValueError: If no chapter heading is found at all.

    Contract:
        - The result starts with a :data:`CHAPTER_HEADING` match.
        - Contains no :data:`TOC_LINE` match from the contents block.
    """
    first = CHAPTER_HEADING.search(text)
    if first is None:
        raise ValueError(
            "no chapter heading found — expected lines like 'CHAPTER I.' at column 0"
        )
    return text[first.start() :]


def roman_to_int(numeral: str) -> int:
    """Decode a canonical roman numeral.

    Strict on purpose. A lenient additive parser turns a corrupted heading into a
    plausible wrong number, and a plausible wrong number is worse than a crash: it would
    reorder the route without anything looking amiss.

    Args:
        numeral: An uppercase roman numeral, e.g. ``"XIV"``.

    Returns:
        Its integer value.

    Raises:
        ValueError: If the input is empty, contains a non-numeral character, or is not
        the
            canonical spelling of its value (``IIII``, ``VX``).

    Contract:
        - Round-trips with :func:`int_to_roman` for ``1 <= n <= 3999``.
        - Accepts only the canonical spelling.

    Examples:
        >>> roman_to_int("XXXVII")
        37
        >>> roman_to_int("IIII")
        Traceback (most recent call last):
        ValueError: 'IIII' is not a canonical roman numeral
    """
    if not numeral:
        raise ValueError("empty roman numeral")
    total = 0
    index = 0
    for value, symbol in _ROMAN_VALUES:
        while numeral[index : index + len(symbol)] == symbol:
            total += value
            index += len(symbol)
    if index != len(numeral) or int_to_roman(total) != numeral:
        raise ValueError(f"{numeral!r} is not a canonical roman numeral")
    return total


def int_to_roman(value: int) -> str:
    """Render an integer as its canonical roman numeral.

    Args:
        value: An integer in ``1..3999``.

    Returns:
        The canonical numeral.

    Raises:
        ValueError: If the value is outside ``1..3999``.

    Contract:
        - Round-trips with :func:`roman_to_int`.

    Examples:
        >>> int_to_roman(37)
        'XXXVII'
        >>> int_to_roman(4)
        'IV'
    """
    if not 1 <= value <= 3999:
        raise ValueError(f"{value} is outside the roman numeral range 1..3999")
    parts: list[str] = []
    remainder = value
    for amount, symbol in _ROMAN_VALUES:
        count, remainder = divmod(remainder, amount)
        parts.append(symbol * count)
    return "".join(parts)


def split_chapters(text: str) -> list[Chapter]:
    r"""Split de-boilerplated text into chapters at the column-zero headings.

    The title is whatever non-blank lines follow the heading, joined onto one line; the
    body is everything after the first blank line. Nothing is inferred: the number of
    chapters returned is exactly the number of headings found.

    Args:
        text: The text to split. Front matter is removed first, so passing the full
            de-boilerplated text is fine.

    Returns:
        The chapters, in document order.

    Raises:
        ValueError: If no heading is found, or a heading carries a non-canonical
        numeral.

    Contract:
        - Returns exactly one chapter per :data:`CHAPTER_HEADING` match — it
          never invents or drops one.
          drops one.
        - Numbers are the decoded numerals, in document order.
        - No returned body contains a :data:`CHAPTER_HEADING` match.
        - Lossless: the bodies rejoined equal the input minus headings and titles, under
          :func:`~verne80.normalize.normalize_quote`.
        - Immune to the table of contents: prefixing any number of
          :data:`TOC_LINE`-shaped lines leaves the result unchanged.
          lines leaves the result unchanged.
        - Pure and deterministic.

    Examples:
        >>> raw = "CHAPTER I.\nA FIRST TITLE\n\nFirst body.\n\nCHAPTER II.\n"
        >>> raw += "A SECOND TITLE\n\nSecond body.\n"
        >>> [(c.number, c.title, c.body) for c in split_chapters(raw)]
        [(1, 'A FIRST TITLE', 'First body.'), (2, 'A SECOND TITLE', 'Second body.')]

        A contents block above the body does not become a chapter:

        >>> len(split_chapters("  CHAPTER I. A FIRST TITLE\n\n" + raw))
        2
    """
    body_text = strip_front_matter(text)
    matches = list(CHAPTER_HEADING.finditer(body_text))
    chapters: list[Chapter] = []
    for position, match in enumerate(matches):
        end = (
            matches[position + 1].start()
            if position + 1 < len(matches)
            else len(body_text)
        )
        title, body = _split_title_and_body(body_text[match.end() : end])
        chapters.append(
            Chapter(number=roman_to_int(match.group(1)), title=title, body=body)
        )
    return chapters


def _split_title_and_body(span: str) -> tuple[str, str]:
    """Separate the title lines from the body within one chapter's span."""
    lines = span.lstrip("\n").splitlines()
    title_lines: list[str] = []
    index = 0
    while (
        index < len(lines)
        and lines[index].strip()
        and len(title_lines) < MAX_TITLE_LINES
    ):
        title_lines.append(lines[index].strip())
        index += 1
    title = normalize_quote(" ".join(title_lines))
    body = "\n".join(lines[index:]).strip()
    return title, body


def toc_titles(text: str) -> list[str]:
    r"""Read the chapter titles out of the table of contents.

    The contents block is an independent statement, by the book itself, of what the
    chapters are called — which makes it an oracle for the split rather than the hazard
    it is usually treated as.

    Args:
        text: The de-boilerplated text, with the contents block still attached.

    Returns:
        The titles, in order, with the ``CHAPTER N.`` prefix removed and normalised the
        same way body titles are, so the two are directly comparable.

    Contract:
        - Never raises; returns an empty list if there is no contents block.

    Examples:
        >>> toc_titles("  CHAPTER I. IN WHICH FOGG WAGERS\n  CHAPTER II. AT SEA\n")
        ['IN WHICH FOGG WAGERS', 'AT SEA']
    """
    return [normalize_quote(match.group(2)) for match in TOC_LINE.finditer(text)]


def check_chapters(chapters: Sequence[Chapter]) -> list[str]:
    """Report everything that looks wrong about a split.

    Returns problems rather than raising, so one run surfaces all of them at once; the
    stage script writes nothing when the list is non-empty. That ordering matters — a
    half-written ``data/chapters/`` silently mismatched against committed extractions is
    the expensive failure this guards against.

    Args:
        chapters: The chapters to check.

    Returns:
        Human-readable problems, empty when the split looks sound.

    Contract:
        - Never raises, for any input including the empty sequence.
        - Empty result means: exactly :data:`EXPECTED_CHAPTERS` chapters, numbered
          ``1..37`` in order, each with a heading-shaped title, a plausible length, and
          no contents or boilerplate residue.

    Examples:
        >>> check_chapters([])
        ['found 0 chapters, expected 37']
        >>> problems = check_chapters([Chapter(1, "A TITLE", "too short")])
        >>> problems[0]
        'found 1 chapters, expected 37'
    """
    problems: list[str] = []
    if len(chapters) != EXPECTED_CHAPTERS:
        problems.append(f"found {len(chapters)} chapters, expected {EXPECTED_CHAPTERS}")

    numbers = [chapter.number for chapter in chapters]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        problems.append(f"duplicate chapter numbers: {duplicates}")
    elif numbers and numbers != list(range(1, len(numbers) + 1)):
        problems.append(
            f"chapter numbers are not 1..{len(numbers)} in order: {numbers}"
        )

    if not chapters:
        return problems

    counts = [chapter.word_count for chapter in chapters]
    middle = median(counts) or 1
    for chapter in chapters:
        problems.extend(_check_one(chapter, middle))
    return problems


def _check_one(chapter: Chapter, middle: float) -> list[str]:
    """Check a single chapter against the length and shape guards."""
    problems: list[str] = []
    label = f"chapter {chapter.number:02d}"
    if not chapter.title:
        problems.append(f"{label} has an empty title")
    else:
        letters = [c for c in chapter.title if c.isalpha()]
        upper = sum(c.isupper() for c in letters) / len(letters) if letters else 0.0
        if upper < 0.8:
            problems.append(
                f"{label} title does not look like a heading "
                f"(only {upper:.0%} uppercase): {chapter.title[:60]!r}"
            )
    if not chapter.body:
        problems.append(f"{label} has an empty body")

    words = chapter.word_count
    if words < MIN_WORDS:
        problems.append(
            f"{label} is suspiciously short: {words:,} words (< {MIN_WORDS:,})"
        )
    if words > MAX_WORDS:
        problems.append(
            f"{label} is suspiciously long: {words:,} words (> {MAX_WORDS:,})"
        )
    ratio = words / middle
    if not RATIO_BAND[0] <= ratio <= RATIO_BAND[1]:
        problems.append(f"{label} is {ratio:.2f}x the median length ({words:,} words)")

    toc_hits = len(TOC_LINE.findall(chapter.body))
    if toc_hits >= 3:
        problems.append(
            f"{label} body still contains table-of-contents lines ({toc_hits} matches)"
        )
    if "PROJECT GUTENBERG" in chapter.body:
        problems.append(f"{label} body contains Gutenberg boilerplate")
    return problems


def chapter_path(directory: Path, number: int) -> Path:
    """Where chapter ``number`` lives.

    Zero-padding is what makes everything downstream sort and join correctly.

    Args:
        directory: The chapters directory.
        number: The chapter number.

    Returns:
        The path.

    Examples:
        >>> chapter_path(Path("data/chapters"), 7)
        PosixPath('data/chapters/chapter_07.txt')
    """
    return directory / f"chapter_{number:02d}.txt"


def build_index(
    chapters: Sequence[Chapter],
    source: GutenbergSource,
    raw_sha256: str,
    raw_bytes: int,
) -> dict[str, object]:
    """Assemble ``data/chapters/index.json``.

    The hashes are the drift alarm. An extraction is only meaningful against the exact
    chapter text it was produced from, and these let a later stage prove the two still
    agree instead of assuming it.

    Args:
        chapters: The split chapters.
        source: The source record they came from.
        raw_sha256: Hex digest of the raw download.
        raw_bytes: Size of the raw download.

    Returns:
        The index, ready to serialise.

    Contract:
        - One entry per chapter, in order.
        - Every entry carries the sha256 of the exact bytes written to its file.
    """
    entries = [
        {
            "number": chapter.number,
            "file": f"chapter_{chapter.number:02d}.txt",
            "title": chapter.title,
            "word_count": chapter.word_count,
            "char_count": len(chapter.body),
            "sha256": sha256(chapter.to_text().encode("utf-8")).hexdigest(),
            "first_line": chapter.first_line,
        }
        for chapter in chapters
    ]
    return {
        "source": {
            "gutenberg_id": source.gutenberg_id,
            "title": source.title,
            "url": source.urls[0],
            "raw_path": str(source.path),
            "raw_bytes": raw_bytes,
            "raw_sha256": raw_sha256,
        },
        "expected_chapters": source.expected_chapters,
        "total_words": sum(chapter.word_count for chapter in chapters),
        "generated_by": "scripts/01_chapters.py",
        "chapters": entries,
    }
