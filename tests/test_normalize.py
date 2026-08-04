import unicodedata

import hypothesis.strategies as st
from hypothesis import assume, given, settings

from tests.strategies import italicised, typographic_variant
from verne80.normalize import (
    fold_typography,
    match_key,
    normalize_quote,
    place_key,
    strip_edge_quotes,
)


class TestFolding:
    def test_curly_apostrophes_fold_to_ascii(self):
        assert normalize_quote("Fogg’s wager") == "Fogg's wager"

    def test_curly_quotes_fold_to_ascii(self):
        assert normalize_quote("“I will wager”") == '"I will wager"'

    def test_em_dash_and_double_hyphen_agree(self):
        assert normalize_quote("him—nobody") == normalize_quote("him--nobody")

    def test_ellipsis_character_becomes_three_dots(self):
        assert normalize_quote("wait…") == "wait..."

    def test_zero_width_characters_are_removed(self):
        assert normalize_quote("Bom​bay") == "Bombay"

    def test_non_breaking_space_is_ordinary_space(self):
        assert normalize_quote("two days") == "two days"


class TestItalics:
    def test_gutenberg_italic_underscores_do_not_break_a_quote(self):
        assert normalize_quote(
            "From London to Suez _viâ_ Mont Cenis"
        ) == normalize_quote("From London to Suez viâ Mont Cenis")

    def test_an_italic_spanning_a_line_break_still_joins(self):
        """Chapter 29's italicised Railway Pioneer — the one span that wraps."""
        assert (
            normalize_quote("the _Railway\nPioneer_ said") == "the Railway Pioneer said"
        )

    def test_an_italicised_newspaper_title_matches_its_plain_form(self):
        assert normalize_quote("_Daily Telegraph_") == normalize_quote(
            "Daily Telegraph"
        )


class TestEdgeQuotes:
    def test_a_quote_mark_the_model_added_is_stripped(self):
        """Chapter 4: the closing mark is real, the opening one was invented."""
        quoted = normalize_quote(
            "\u201cWe start for Dover and Calais in ten minutes.\u201d"
        )
        assert (
            strip_edge_quotes(quoted) == "We start for Dover and Calais in ten minutes."
        )

    def test_an_interior_quote_mark_is_content_and_survives(self):
        assert strip_edge_quotes('he said "no" twice') == 'he said "no" twice'

    def test_stripping_is_idempotent(self):
        once = strip_edge_quotes('"a quotation."')
        assert strip_edge_quotes(once) == once


class TestWhitespaceCollapse:
    def test_a_quote_spanning_a_line_break_collapses_to_one_line(self):
        wrapped = "They mounted upon\nthe elephant, and set out"
        assert normalize_quote(wrapped) == "They mounted upon the elephant, and set out"

    def test_folding_alone_keeps_line_structure(self):
        assert "\n" in fold_typography("one\ntwo")

    def test_leading_and_trailing_whitespace_go(self):
        assert normalize_quote("\n  Suez  \n") == "Suez"


class TestMatchKey:
    def test_case_is_folded(self):
        assert match_key("AROUND THE WORLD") == match_key("Around the World")

    def test_it_still_collapses_whitespace(self):
        assert match_key("  Bombay\n") == "bombay"


class TestNormalizeProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_normalize_is_idempotent(self, text):
        once = normalize_quote(text)
        assert normalize_quote(once) == once

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_output_is_nfc(self, text):
        once = normalize_quote(text)
        assert unicodedata.normalize("NFC", once) == once

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_output_has_no_stray_whitespace(self, text):
        once = normalize_quote(text)
        assert once == once.strip()
        assert "  " not in once
        assert "\n" not in once
        assert "\t" not in once

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_it_never_raises(self, text):
        assert isinstance(normalize_quote(text), str)
        assert isinstance(fold_typography(text), str)
        assert isinstance(match_key(text), str)

    @settings(max_examples=150, deadline=None)
    @given(st.data(), st.text(min_size=1))
    def test_typography_does_not_change_the_key(self, data, text):
        variant = data.draw(typographic_variant(text))
        assert normalize_quote(variant) == normalize_quote(text)

    @settings(max_examples=150, deadline=None)
    @given(st.text(alphabet=st.characters(codec="ascii")))
    def test_match_key_is_case_invariant_for_ascii(self, text):
        assert match_key(text.upper()) == match_key(text.lower())

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_case_folding_first_changes_nothing(self, text):
        """Case-folding before match_key is a no-op — the general form of the property.

        Full Unicode case-invariance is false: U+0131 (dotless i) upper-cases to "I"
        and folds to "i", but folds to itself when left alone. The 1872 text is
        Latin-1, so this never bites in practice; the property is stated the way
        casefold actually behaves rather than the way one might wish it did.
        """
        assert match_key(text.casefold()) == match_key(text)

    @settings(max_examples=150, deadline=None)
    @given(st.data(), st.text(min_size=1))
    def test_inserting_italic_markers_never_changes_the_key(self, data, text):
        variant = data.draw(italicised(text))
        assert normalize_quote(variant) == normalize_quote(text)

    @settings(max_examples=150, deadline=None)
    @given(st.text(min_size=1))
    def test_wrapping_a_quote_in_marks_never_changes_the_stripped_key(self, text):
        """Restricted to text that does not already end in a quotation mark.

        Hypothesis found `0" `: wrapping it makes its own trailing mark interior, so
        stripping no longer removes it. Stripping only ever looks at the ends, and that
        is the honest scope of the property.
        """
        inner = strip_edge_quotes(normalize_quote(text))
        assume(inner == normalize_quote(text))
        wrapped = strip_edge_quotes(normalize_quote(f'"{text}"'))
        assert wrapped == inner

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_stripping_edge_quotes_never_lengthens(self, text):
        assert len(strip_edge_quotes(text)) <= len(text)

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_match_key_is_idempotent(self, text):
        once = match_key(text)
        assert match_key(once) == once


class TestTheLeadingArticle:
    """Verne writes both "the Reform Club" and "Reform Club"; they are one place."""

    def test_an_article_does_not_make_a_second_place(self):
        assert place_key("the Reform Club") == place_key("Reform Club")

    def test_the_article_goes_after_the_quote_marks(self):
        assert place_key("“the Continent”") == place_key("Continent")

    def test_an_article_inside_a_name_is_left_alone(self):
        assert place_key("valley of the Ganges") == "valley of the ganges"

    def test_a_bare_article_is_not_emptied(self):
        """Emptying it would collapse it onto every other empty key."""
        assert place_key("the") == "the"

    def test_only_one_article_is_dropped(self):
        assert place_key("the a") == "a"

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_it_stays_idempotent(self, text):
        once = place_key(text)
        assert place_key(once) == once
