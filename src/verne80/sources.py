"""Where the raw text comes from, and where it lands on disk.

One frozen record per source text. The download itself lives in ``scripts/00_fetch.py``
— this module only describes what to fetch, so it stays importable without touching the
network or the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["BOOK", "DEFAULT_RAW_DIR", "GutenbergSource"]

DEFAULT_RAW_DIR = Path("data/raw")

# Project Gutenberg serves the same text from three shapes of URL and does not guarantee
# all three exist for a given book. ``cache/epub`` is first because it is the one
# verified to serve #103.
_URL_PATTERNS = (
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
)


@dataclass(frozen=True, slots=True)
class GutenbergSource:
    """One Project Gutenberg text, and the local file it is cached as.

    Attributes:
        gutenberg_id: The Project Gutenberg ebook number.
        slug: The stem of the local filename, e.g. ``"pg103"``.
        title: The work's title, for run logs and provenance records.
        expected_chapters: How many chapters the text must split into. Asserted rather
            than discovered, so a changed edition is an error and not a silent surprise.
    """

    gutenberg_id: int
    slug: str
    title: str
    expected_chapters: int

    @property
    def urls(self) -> tuple[str, ...]:
        """The candidate download URLs, most reliable first.

        Returns:
            The URLs to try in order.

        Contract:
            - Non-empty, and every element mentions ``gutenberg_id``.
            - Deterministic: the same source always yields the same tuple.

        Examples:
            >>> BOOK.urls[0]
            'https://www.gutenberg.org/cache/epub/103/pg103.txt'
        """
        return tuple(pattern.format(id=self.gutenberg_id) for pattern in _URL_PATTERNS)

    @property
    def path(self) -> Path:
        """Where the untouched download is kept.

        Returns:
            The path under :data:`DEFAULT_RAW_DIR`.

        Contract:
            - Always ``DEFAULT_RAW_DIR / f"{slug}.txt"``.

        Examples:
            >>> BOOK.path
            PosixPath('data/raw/pg103.txt')
        """
        return DEFAULT_RAW_DIR / f"{self.slug}.txt"


BOOK = GutenbergSource(
    gutenberg_id=103,
    slug="pg103",
    title="Around the World in Eighty Days",
    expected_chapters=37,
)
