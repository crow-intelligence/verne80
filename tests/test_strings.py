"""The catalogue: the two things that actually break a translated page."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from verne80.strings import (
    CATALOGUE,
    DEFAULT_LANGUAGE,
    LANGUAGES,
    catalogue_payload,
    check_catalogue,
    missing_keys,
    placeholder_names,
)


class TestTheShippedCatalogue:
    def test_english_is_complete_and_sound(self):
        assert check_catalogue() == []

    def test_every_offered_language_has_an_entry(self):
        for code, _ in LANGUAGES:
            assert code in CATALOGUE

    def test_hungarian_is_empty_rather_than_guessed(self):
        """An empty key falls back visibly. A guessed one reads as finished work."""
        assert CATALOGUE["hu"] == {}
        assert missing_keys()["hu"] == sorted(CATALOGUE["en"])

    def test_no_string_smuggles_in_markup(self):
        """A tag in a catalogue is an injection hole and an untranslatable blob."""
        assert not [
            key
            for key, value in CATALOGUE["en"].items()
            if "<" in value and ">" in value
        ]

    def test_the_placeholders_the_page_relies_on_are_present(self):
        english = CATALOGUE["en"]
        assert placeholder_names(english["chapter.of"]) == {"n", "total"}
        assert placeholder_names(english["leg.table_says"]) == {"from", "to"}
        assert "who" in placeholder_names(english["track.absent"])


class TestParity:
    def test_a_lost_placeholder_is_caught(self):
        problems = check_catalogue({"en": {"d": "Day {n}"}, "hu": {"d": "Nap"}})
        assert problems == ["hu 'd' is missing the placeholder {n}"]

    def test_an_invented_placeholder_is_caught(self):
        problems = check_catalogue({"en": {"d": "Day"}, "hu": {"d": "{n}. nap"}})
        assert "has a placeholder {n}" in problems[0]

    def test_a_translation_with_no_original_is_caught(self):
        problems = check_catalogue({"en": {}, "hu": {"stray": "x"}})
        assert "has no en original" in problems[0]

    def test_reordering_a_placeholder_is_fine(self):
        """Word order is exactly what a translator is for."""
        assert (
            check_catalogue({"en": {"d": "{n} of {t}"}, "hu": {"d": "{t}-ból {n}"}})
            == []
        )

    def test_an_untranslated_key_is_not_a_problem(self):
        """It falls back, and missing_keys is where it gets reported."""
        assert check_catalogue({"en": {"a": "A", "b": "B"}, "hu": {"a": "Á"}}) == []


class TestThePayload:
    def test_every_offered_language_gets_an_object_even_when_empty(self):
        payload = catalogue_payload()
        for code, _ in LANGUAGES:
            assert isinstance(payload[code], dict)

    def test_the_default_language_is_named_in_the_payload(self):
        assert catalogue_payload()["default"] == DEFAULT_LANGUAGE

    def test_a_language_not_offered_is_left_out(self):
        payload = catalogue_payload(
            {"en": {"a": "A"}, "fr": {"a": "A"}}, (("en", "En"),)
        )
        assert "fr" not in payload


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8, alphabet="abcd."),
        st.text(min_size=0, max_size=20, alphabet="abc {n}{t}"),
        max_size=8,
    )
)
@settings(max_examples=200)
def test_a_catalogue_translated_into_itself_is_always_sound(english):
    """Copying English into Hungarian is a bad translation and a valid one."""
    assume_clean = {k: v.replace("<", "").replace(">", "") for k, v in english.items()}
    assert check_catalogue({"en": assume_clean, "hu": dict(assume_clean)}) == []


@given(st.text(max_size=60))
@settings(max_examples=200)
def test_placeholder_names_never_raises_and_never_invents(text):
    for name in placeholder_names(text):
        assert "{" + name + "}" in text
