import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.conftest import SYNTHETIC_RAW
from tests.strategies import gutenberg_document
from verne80.chapters import (
    CHAPTER_HEADING,
    EXPECTED_CHAPTERS,
    Chapter,
    build_index,
    chapter_path,
    check_chapters,
    int_to_roman,
    read_raw,
    roman_to_int,
    split_chapters,
    strip_front_matter,
    strip_gutenberg_boilerplate,
    toc_titles,
)
from verne80.normalize import match_key, normalize_quote
from verne80.sources import BOOK


class TestBoilerplate:
    def test_boilerplate_is_removed(self, raw_text):
        body = strip_gutenberg_boilerplate(raw_text)
        assert "PROJECT GUTENBERG" not in body
        assert "This eBook is for the use of anyone anywhere." not in body

    def test_missing_start_marker_raises(self):
        with pytest.raises(ValueError, match="START OF THE PROJECT GUTENBERG"):
            strip_gutenberg_boilerplate("no markers here\nCHAPTER I.\n")

    def test_missing_end_marker_raises(self):
        text = "*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody"
        with pytest.raises(ValueError, match="truncated"):
            strip_gutenberg_boilerplate(text)

    def test_no_heading_at_all_raises(self):
        with pytest.raises(ValueError, match="no chapter heading"):
            strip_front_matter("just some prose\nand more prose\n")


class TestTheTableOfContentsTrap:
    def test_toc_lines_are_not_mistaken_for_chapter_headings(self, raw_text):
        assert len(split_chapters(strip_gutenberg_boilerplate(raw_text))) == 3

    def test_an_indented_heading_does_not_split(self):
        text = "CHAPTER I.\nA TITLE\n\nBody.\n\n  CHAPTER II.\nNot a heading.\n"
        assert len(split_chapters(text)) == 1

    def test_a_heading_with_a_title_on_the_same_line_does_not_split(self):
        text = "CHAPTER I.\nA TITLE\n\nBody.\n\nCHAPTER II. WITH A TITLE HERE\n"
        assert len(split_chapters(text)) == 1

    def test_front_matter_is_dropped_entirely(self, raw_text):
        body = strip_front_matter(strip_gutenberg_boilerplate(raw_text))
        assert body.startswith("CHAPTER I.")
        assert "Contents" not in body
        assert "[Illustration]" not in body

    def test_toc_titles_are_read_whole_not_truncated(self, raw_text):
        titles = toc_titles(strip_gutenberg_boilerplate(raw_text))
        assert titles == [
            "IN WHICH FOGG WAGERS",
            "IN WHICH THE MONGOLIA SAILS",
            "IN WHICH THE ELEPHANT IS BOUGHT",
        ]

    def test_toc_titles_is_empty_without_a_contents_block(self):
        assert toc_titles("CHAPTER I.\nA TITLE\n\nBody.\n") == []


class TestLineEndings:
    def test_crlf_line_endings_do_not_break_the_heading_regex(self, tmp_path):
        path = tmp_path / "raw.txt"
        path.write_bytes(SYNTHETIC_RAW.encode("utf-8"))
        text = read_raw(path)
        assert "\r" not in text
        assert len(CHAPTER_HEADING.findall(text)) == 3

    def test_a_missing_raw_file_names_the_stage_that_makes_it(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="scripts/00_fetch.py"):
            read_raw(tmp_path / "absent.txt")

    def test_latin1_fallback_decodes_rather_than_raising(self, tmp_path):
        path = tmp_path / "raw.txt"
        path.write_bytes(b"*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\xe9\n")
        assert "é" in read_raw(path) or "Ã©" in read_raw(path)


class TestSplitting:
    def test_two_line_titles_are_joined(self):
        text = "CHAPTER I.\nA VERY LONG TITLE\nCONTINUED ON A SECOND LINE\n\nBody.\n"
        assert (
            split_chapters(text)[0].title
            == "A VERY LONG TITLE CONTINUED ON A SECOND LINE"
        )

    def test_bodies_do_not_contain_headings(self, chapters):
        assert not any(CHAPTER_HEADING.search(chapter.body) for chapter in chapters)

    def test_numbers_come_from_the_numerals(self, chapters):
        assert [chapter.number for chapter in chapters] == [1, 2, 3]

    def test_first_line_is_prose_not_a_title(self, chapters):
        assert chapters[0].first_line.startswith("Mr. Phileas Fogg lived")

    def test_to_text_puts_the_number_and_title_first(self, chapters):
        lines = chapters[0].to_text().splitlines()
        assert lines[0] == "CHAPTER 01"
        assert lines[1] == "IN WHICH FOGG WAGERS"
        assert lines[2] == ""


class TestRomanNumerals:
    def test_it_decodes_the_book_s_range(self):
        assert roman_to_int("XXXVII") == 37

    def test_non_canonical_roman_numeral_raises(self):
        with pytest.raises(ValueError, match="not a canonical roman numeral"):
            roman_to_int("IIII")

    def test_subtractive_misspelling_raises(self):
        with pytest.raises(ValueError, match="not a canonical roman numeral"):
            roman_to_int("VX")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty roman numeral"):
            roman_to_int("")

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="outside the roman numeral range"):
            int_to_roman(0)


class TestChecks:
    def test_wrong_chapter_count_is_reported_not_guessed(self, chapters):
        problems = check_chapters(chapters)
        assert f"found 3 chapters, expected {EXPECTED_CHAPTERS}" in problems

    def test_an_empty_split_is_reported_without_crashing(self):
        assert check_chapters([]) == ["found 0 chapters, expected 37"]

    def test_short_chapter_is_flagged(self):
        problems = check_chapters([Chapter(1, "A TITLE", "only a few words here")])
        assert any("suspiciously short" in problem for problem in problems)

    def test_a_lowercase_title_is_flagged_as_not_a_heading(self):
        problems = check_chapters(
            [Chapter(1, "a body sentence, not a title", "x " * 500)]
        )
        assert any("does not look like a heading" in problem for problem in problems)

    def test_body_containing_toc_lines_is_flagged(self):
        toc = "\n".join(f" CHAPTER {int_to_roman(n)}. A TITLE" for n in range(1, 6))
        problems = check_chapters([Chapter(1, "A TITLE", "x " * 500 + "\n" + toc)])
        assert any("table-of-contents lines" in problem for problem in problems)

    def test_boilerplate_residue_is_flagged(self):
        body = "x " * 500 + "\n*** END OF THE PROJECT GUTENBERG EBOOK X ***"
        problems = check_chapters([Chapter(1, "A TITLE", body)])
        assert any("Gutenberg boilerplate" in problem for problem in problems)

    def test_duplicate_numbers_are_flagged(self):
        body = "x " * 500
        problems = check_chapters(
            [Chapter(1, "A TITLE", body), Chapter(1, "B TITLE", body)]
        )
        assert any("duplicate chapter numbers" in problem for problem in problems)

    def test_out_of_order_numbers_are_flagged(self):
        body = "x " * 500
        problems = check_chapters(
            [Chapter(2, "A TITLE", body), Chapter(1, "B TITLE", body)]
        )
        assert any("not 1..2 in order" in problem for problem in problems)


class TestIndex:
    def test_the_index_records_one_entry_per_chapter(self, chapters):
        index = build_index(chapters, BOOK, "abc123", 1234)
        assert len(index["chapters"]) == len(chapters)
        assert index["source"]["raw_sha256"] == "abc123"
        assert index["total_words"] == sum(c.word_count for c in chapters)

    def test_chapter_paths_are_zero_padded(self, tmp_path):
        assert chapter_path(tmp_path, 7).name == "chapter_07.txt"


class TestRealText:
    """The committed Gutenberg text — the split has to work on the actual book."""

    def test_real_text_splits_into_37_chapters(self, pg103_raw):
        body = strip_gutenberg_boilerplate(pg103_raw)
        assert len(split_chapters(body)) == EXPECTED_CHAPTERS

    def test_body_titles_match_the_table_of_contents(self, pg103_raw):
        """The book's own contents block is an independent oracle for the split."""
        body = strip_gutenberg_boilerplate(pg103_raw)
        printed = toc_titles(body)
        split = split_chapters(body)
        assert len(printed) == len(split) == EXPECTED_CHAPTERS
        for chapter, expected in zip(split, printed, strict=True):
            assert match_key(chapter.title) == match_key(expected)

    def test_real_check_chapters_is_clean(self, pg103_raw):
        chapters = split_chapters(strip_gutenberg_boilerplate(pg103_raw))
        assert check_chapters(chapters) == []

    def test_chapter_one_first_line_is_the_famous_one(self, pg103_raw):
        chapters = split_chapters(strip_gutenberg_boilerplate(pg103_raw))
        assert chapters[0].first_line.startswith("Mr. Phileas Fogg lived, in 1872")

    def test_no_body_contains_a_heading(self, pg103_raw):
        chapters = split_chapters(strip_gutenberg_boilerplate(pg103_raw))
        assert not any(CHAPTER_HEADING.search(chapter.body) for chapter in chapters)


class TestChapterProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.integers(min_value=1, max_value=3999))
    def test_roman_numerals_round_trip(self, value):
        assert roman_to_int(int_to_roman(value)) == value

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(gutenberg_document())
    def test_it_finds_exactly_the_chapters_that_are_there(self, document):
        text, count = document
        assert len(split_chapters(strip_gutenberg_boilerplate(text))) == count

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(gutenberg_document())
    def test_numbers_are_one_to_n_in_order(self, document):
        text, count = document
        chapters = split_chapters(strip_gutenberg_boilerplate(text))
        assert [c.number for c in chapters] == list(range(1, count + 1))

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(gutenberg_document())
    def test_the_split_is_lossless(self, document):
        text, _ = document
        body = strip_front_matter(strip_gutenberg_boilerplate(text))
        chapters = split_chapters(body)
        rejoined = normalize_quote(" ".join(f"{c.title} {c.body}" for c in chapters))
        stripped = normalize_quote(CHAPTER_HEADING.sub(" ", body))
        assert rejoined == stripped

    @settings(
        max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(gutenberg_document(), st.integers(min_value=0, max_value=20))
    def test_extra_contents_lines_change_nothing(self, document, extra):
        text, count = document
        noise = "\n".join(
            f" CHAPTER {int_to_roman(n + 1)}. NOISE" for n in range(extra)
        )
        polluted = text.replace("Contents\n", f"Contents\n{noise}\n", 1)
        assert len(split_chapters(strip_gutenberg_boilerplate(polluted))) == count

    @settings(
        max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(gutenberg_document())
    def test_check_chapters_never_raises(self, document):
        text, _ = document
        chapters = split_chapters(strip_gutenberg_boilerplate(text))
        problems = check_chapters(chapters)
        assert isinstance(problems, list)
        assert all(isinstance(problem, str) for problem in problems)
