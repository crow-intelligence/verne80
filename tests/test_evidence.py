from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.conftest import WRAPPED_QUOTE
from tests.strategies import evidence_quote, typographic_variant
from verne80.evidence import (
    PASSING,
    MatchKind,
    NormalisedChapter,
    check_chapter_quotes,
    check_quote,
    failing,
    find_best_span,
    inline_diff,
    summarise,
)
from verne80.normalize import normalize_quote
from verne80.schema import ChapterExtraction, EvidenceRef

CHAPTER_TEXT = (
    "CHAPTER 03\n"
    "IN WHICH THE ELEPHANT IS BOUGHT\n"
    "\n"
    "They mounted upon the elephant, and set out across the forest. The\n"
    "beast was sold to him for two thousand pounds, which Mr. Fogg paid\n"
    "without a word. He said, “the wager stands”—and nobody spoke.\n"
)


def chapter() -> NormalisedChapter:
    return NormalisedChapter.from_text(3, CHAPTER_TEXT)


def ref(quote: str) -> EvidenceRef:
    return EvidenceRef(3, "transport[0].evidence", quote)


class TestTheLadder:
    def test_an_exact_substring_is_exact(self):
        assert check_quote(ref("They mounted upon the elephant"), chapter()).kind is (
            MatchKind.EXACT
        )

    def test_quote_spanning_a_line_break_matches(self):
        """The single most common real failure: Gutenberg wraps, the JSON does not."""
        result = check_quote(ref(WRAPPED_QUOTE), chapter())
        assert result.kind is MatchKind.NORMALISED
        assert result.passed

    def test_curly_quote_variant_matches(self):
        assert check_quote(ref('He said, "the wager stands"'), chapter()).passed

    def test_em_dash_variant_matches(self):
        assert check_quote(
            ref('"the wager stands"--and nobody spoke'), chapter()
        ).passed

    def test_case_change_is_a_warning_not_a_pass(self):
        result = check_quote(ref("THEY MOUNTED UPON THE ELEPHANT"), chapter())
        assert result.kind is MatchKind.CASE_INSENSITIVE
        assert not result.passed

    def test_ellipsis_quote_is_recognised(self):
        result = check_quote(ref("They mounted upon ... across the forest"), chapter())
        assert result.kind is MatchKind.ELLIPSIS

    def test_near_miss_reports_the_closest_span_and_line(self):
        result = check_quote(ref("They mounted the elephant, and set out"), chapter())
        assert result.kind is MatchKind.NEAR_MISS
        assert result.best_span is not None
        assert result.line_no == 4

    def test_invented_quote_is_missing(self):
        invented = ref("the elephant Kiouni was purchased in Allahabad for a great sum")
        assert check_quote(invented, chapter()).kind is MatchKind.MISSING

    def test_an_empty_quote_is_missing(self):
        assert check_quote(ref("   "), chapter()).kind is MatchKind.MISSING


class TestGutenbergItalics:
    def test_an_italicised_word_is_not_a_near_miss(self):
        """Gemini strips Gutenberg's underscores; the fold is what stops the drizzle."""
        real = Path("data/chapters/chapter_03.txt")
        if not real.exists():
            pytest.skip("run `uv run python scripts/01_chapters.py` first")
        chapter = NormalisedChapter.from_text(3, real.read_text(encoding="utf-8"))
        quote = "From London to Suez viâ Mont Cenis and Brindisi"
        assert check_quote(
            EvidenceRef(3, "places_mentioned[0].evidence", quote), chapter
        ).passed


class TestLineNumbers:
    def test_line_number_points_at_the_right_line(self):
        result = check_quote(ref("beast was sold to him"), chapter())
        assert result.line_no == 5

    def test_the_offset_map_is_monotonic_and_in_range(self):
        prepared = chapter()
        assert len(prepared.offsets) == len(prepared.norm)
        assert list(prepared.offsets) == sorted(prepared.offsets)
        assert all(0 <= offset < len(prepared.raw) for offset in prepared.offsets)

    def test_the_normalised_form_agrees_with_the_primitive(self):
        prepared = chapter()
        assert prepared.norm == normalize_quote(prepared.raw)

    def test_an_out_of_range_index_clamps_rather_than_raising(self):
        assert chapter().line_of(10**6) >= 1


class TestFindBestSpan:
    def test_a_present_needle_scores_one(self):
        ratio, start, end = find_best_span("they mounted the elephant", "the elephant")
        assert ratio == 1.0
        assert "they mounted the elephant"[start:end] == "the elephant"

    def test_an_empty_needle_scores_zero(self):
        assert find_best_span("anything", "") == (0.0, 0, 0)

    def test_an_unrelated_needle_scores_low(self):
        ratio, _, _ = find_best_span("they mounted the elephant", "zzzz qqqq wwww")
        assert ratio < 0.5


class TestReporting:
    def test_the_diff_shows_what_was_added(self):
        diff = inline_diff(
            "They mounted the elephant", "They mounted upon the elephant"
        )
        assert "{+upon +}" in diff

    def test_the_diff_of_identical_strings_is_the_string(self):
        assert inline_diff("same", "same") == "same"

    def test_failing_puts_missing_first(self):
        checks = [
            type(check_quote(ref("x"), chapter()))(ref("a"), MatchKind.NEAR_MISS, 0.9),
            type(check_quote(ref("x"), chapter()))(ref("b"), MatchKind.MISSING, 0.1),
        ]
        assert [c.kind for c in failing(checks)] == [
            MatchKind.MISSING,
            MatchKind.NEAR_MISS,
        ]

    def test_summarise_counts_by_kind(self):
        checks = check_chapter_quotes(
            ChapterExtraction(
                chapter=3,
                summary_hover="A hover summary.",
                summary_detail="A detail summary. With two sentences.",
                places_visited=[
                    {
                        "name_in_text": "the forest",
                        "role": "passing_through",
                        "evidence": "across the forest",
                    }
                ],
            ),
            chapter(),
        )
        assert summarise(checks)[MatchKind.EXACT] == 1


class TestWholeExtraction:
    def test_every_quote_in_a_good_extraction_passes(self, valid_extraction, chapters):
        prepared = NormalisedChapter.from_text(3, chapters[2].to_text())
        checks = check_chapter_quotes(ChapterExtraction(**valid_extraction), prepared)
        assert len(checks) == 5
        assert all(check.passed for check in checks), [
            (c.ref.path, c.kind, c.ratio) for c in checks if not c.passed
        ]

    def test_one_verdict_per_evidence_item(self, valid_extraction, chapters):
        extraction = ChapterExtraction(**valid_extraction)
        prepared = NormalisedChapter.from_text(3, chapters[2].to_text())
        assert len(check_chapter_quotes(extraction, prepared)) == len(
            extraction.evidence_items()
        )


class TestEvidenceProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=200), st.text(max_size=60))
    def test_the_ratio_stays_in_range(self, haystack, needle):
        ratio, start, end = find_best_span(haystack, needle)
        assert 0.0 <= ratio <= 1.0
        assert 0 <= start <= end <= len(haystack)

    @settings(max_examples=150, deadline=None)
    @given(st.text(min_size=1, max_size=200), st.data())
    def test_a_present_needle_always_scores_one(self, haystack, data):
        start = data.draw(st.integers(min_value=0, max_value=len(haystack) - 1))
        end = data.draw(st.integers(min_value=start + 1, max_value=len(haystack)))
        ratio, _, _ = find_best_span(haystack, haystack[start:end])
        assert ratio == 1.0

    @settings(
        max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(evidence_quote(CHAPTER_TEXT))
    def test_a_real_slice_of_the_chapter_always_passes(self, quote):
        """The anti-false-alarm invariant: the validator must not cry wolf."""
        assert check_quote(ref(quote), chapter()).kind in PASSING

    @settings(
        max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow]
    )
    @given(evidence_quote(CHAPTER_TEXT), st.data())
    def test_a_real_slice_still_passes_after_a_typographic_rewrite(self, quote, data):
        """The highest-value property here: it is what a real paste does to a quote."""
        variant = data.draw(typographic_variant(quote))
        assert check_quote(ref(variant), chapter()).kind in PASSING

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=100))
    def test_checking_never_raises(self, quote):
        result = check_quote(ref(quote), chapter())
        assert isinstance(result.kind, MatchKind)
        assert 0.0 <= result.ratio <= 1.0

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=200))
    def test_the_offset_map_always_lines_up(self, raw):
        """The map is monotonic, not strictly increasing.

        `…` folds to three characters, and all three point back at the one character
        they came from.
        """
        prepared = NormalisedChapter.from_text(1, raw)
        assert len(prepared.offsets) == len(prepared.norm)
        assert prepared.norm == normalize_quote(raw)
        assert list(prepared.offsets) == sorted(prepared.offsets)
        assert all(0 <= offset < len(raw) for offset in prepared.offsets)
