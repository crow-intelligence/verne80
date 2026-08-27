"""Where the raw material comes from, and where it lands on disk.

One frozen record per source. The download itself lives in ``scripts/00_fetch.py``
— this module only describes what to fetch, so it stays importable without touching the
network or the filesystem.

Two kinds of source, and the difference is not cosmetic. :class:`GutenbergSource` is a
text whose *wording* everything downstream is joined to, so it is fetched once and never
touched again. :class:`GeoJSONSource` is geometry the map draws; it is equally a
provenance record, but it also carries the licence and the attribution line, because a
basemap is somebody's work and the footer has to say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BOOK",
    "BORDERS_1880",
    "BORDERS_MODERN",
    "DEFAULT_RAW_DIR",
    "GeoJSONSource",
    "GutenbergSource",
    "LAND",
    "SOURCES",
]

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
        min_bytes: Below this, the response is an error page rather than a book.
            Gutenberg answers a missing file with a 200 and a paragraph of HTML, so
            the size check is the only thing that catches it.
    """

    gutenberg_id: int
    slug: str
    title: str
    expected_chapters: int
    min_bytes: int = 100_000

    @property
    def name(self) -> str:
        """The identifier ``--only`` matches on.

        Returns:
            The short name.

        Examples:
            >>> BOOK.name
            'book'
        """
        return "book"

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


@dataclass(frozen=True, slots=True)
class GeoJSONSource:
    """One GeoJSON layer, and the local file it is cached as.

    The licence and attribution are fields rather than a note in a README because the
    footer has to print them and a footer that quotes a README drifts from it. Natural
    Earth asks for no permission and no credit; the credit is given anyway, and stating
    that here is what makes it a decision rather than an oversight.

    Attributes:
        name: The identifier ``--only`` matches on, e.g. ``"land"``.
        slug: The stem of the local filename.
        title: What the layer is, for run logs.
        url: Where to fetch it.
        licence: The licence, as the footer should print it.
        attribution: The credit line, as the footer should print it.
        min_bytes: Below this, the response is an error page rather than geometry.
    """

    name: str
    slug: str
    title: str
    url: str
    licence: str
    attribution: str
    min_bytes: int = 10_000

    @property
    def urls(self) -> tuple[str, ...]:
        """The download URLs, so a caller can treat every source the same way.

        A GeoJSON layer has exactly one URL, where a Gutenberg text has three shapes to
        try. Returning a tuple of one keeps the fetch loop from having to know which
        kind it is holding.

        Returns:
            The single URL, in a tuple.

        Examples:
            >>> len(LAND.urls)
            1
        """
        return (self.url,)

    @property
    def path(self) -> Path:
        """Where the untouched download is kept.

        Returns:
            The path under :data:`DEFAULT_RAW_DIR`.

        Examples:
            >>> LAND.path
            PosixPath('data/raw/ne_110m_land.geojson')
        """
        return DEFAULT_RAW_DIR / f"{self.slug}.geojson"


BOOK = GutenbergSource(
    gutenberg_id=103,
    slug="pg103",
    title="Around the World in Eighty Days",
    expected_chapters=37,
)

# Land only, not countries. The globe's first phase draws no borders, so one dissolved
# MultiPolygon is the whole requirement — and pinned to a commit rather than to
# ``master``, because a basemap that changes under a committed derived file is a
# provenance record that has stopped recording anything.
LAND = GeoJSONSource(
    name="land",
    slug="ne_110m_land",
    title="Natural Earth 1:110m land",
    url=(
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "v5.1.2/geojson/ne_110m_land.geojson"
    ),
    licence="public domain",
    attribution="Natural Earth",
)

# The world as Verne's readers knew it. There is no 1872 file and no 1870 one: the
# collection offers 53 years and the nearest to the novel is 1880, eight years after.
# That gap is stated on the page rather than rounded away, because "the borders of 1872"
# would be a claim about a file that does not exist.
#
# Pinned to a commit, not to a branch: the repository has no tags and no releases, so
# `master` is not a pin. This file has been byte-identical since December 2023.
#
# GPL-3.0, which is unusual for geodata and is the reason NOTICE exists. The repository
# carries a plain unmodified copy of the licence and no separate data terms, so the
# derived layer travels with the same licence and the author is credited by name.
BORDERS_1880 = GeoJSONSource(
    name="borders-1880",
    slug="world_1880",
    title="Historical basemaps: world borders, 1880",
    url=(
        "https://raw.githubusercontent.com/aourednik/historical-basemaps/"
        "62d8f1a03a71f2d3ff17f2d166f7553f256bce68/geojson/world_1880.geojson"
    ),
    licence="GPL-3.0",
    attribution="André Ourednik, historical-basemaps",
    min_bytes=500_000,
)

# The world now, from the same release as the coastline, so the two cannot drift apart.
BORDERS_MODERN = GeoJSONSource(
    name="borders-modern",
    slug="ne_110m_admin_0_countries",
    title="Natural Earth 1:110m country borders",
    url=(
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "v5.1.2/geojson/ne_110m_admin_0_countries.geojson"
    ),
    licence="public domain",
    attribution="Natural Earth",
    min_bytes=400_000,
)

SOURCES: tuple[GutenbergSource | GeoJSONSource, ...] = (
    BOOK,
    LAND,
    BORDERS_1880,
    BORDERS_MODERN,
)
