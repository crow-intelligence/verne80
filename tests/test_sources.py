from pathlib import Path

from verne80.sources import BOOK, DEFAULT_RAW_DIR, GutenbergSource


def test_the_book_is_number_103_with_37_chapters():
    assert BOOK.gutenberg_id == 103
    assert BOOK.expected_chapters == 37


def test_every_url_mentions_the_ebook_number():
    assert BOOK.urls
    assert all("103" in url for url in BOOK.urls)


def test_the_verified_url_shape_is_tried_first():
    assert BOOK.urls[0] == "https://www.gutenberg.org/cache/epub/103/pg103.txt"


def test_the_cached_path_is_under_the_raw_directory():
    assert BOOK.path == DEFAULT_RAW_DIR / "pg103.txt"


def test_urls_are_deterministic():
    other = GutenbergSource(103, "pg103", "Around the World in Eighty Days", 37)
    assert other.urls == BOOK.urls
    assert other.path == Path("data/raw/pg103.txt")
