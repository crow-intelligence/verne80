import unicodedata

import hypothesis.strategies as st
from hypothesis import given, settings

from tests.strategies import italicised, typographic_variant
from verne80.normalize import fold_typography, match_key, normalize_quote


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
    @given(st.text())
    def test_match_key_is_idempotent(self, text):
        once = match_key(text)
        assert match_key(once) == once
