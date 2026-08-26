"""The string table: the things that break a page silently."""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from verne80.strings import (
    LANGUAGE,
    STRINGS,
    check_strings,
    placeholder_names,
    strings_payload,
)


class TestTheShippedTable:
    def test_it_is_sound(self):
        assert check_strings() == []

    def test_no_string_smuggles_in_markup(self):
        """The page sets textContent, so a tag would print as angle brackets."""
        assert not [
            key for key, value in STRINGS.items() if "<" in value and ">" in value
        ]

    def test_the_placeholders_the_page_relies_on_are_present(self):
        assert placeholder_names(STRINGS["chapter.of"]) == {"n", "total"}
        assert placeholder_names(STRINGS["prov.line"]) == {
            "plotted",
            "total",
            "confirmed",
        }
        assert "who" in placeholder_names(STRINGS["track.absent"])

    def test_the_reader_is_never_shown_the_word_leg(self):
        """`leg` is the data's word, `stage` the reader's. This is the boundary."""
        offenders = [
            key
            for key, value in STRINGS.items()
            if " leg " in f" {value.lower()} " or " legs " in f" {value.lower()} "
        ]
        assert offenders == []

    def test_the_stage_keys_exist_and_the_leg_keys_do_not(self):
        assert "stage.count" in STRINGS
        assert not [key for key in STRINGS if key.startswith("leg.")]


class TestTheChecks:
    def test_markup_is_caught(self):
        assert check_strings({"x": "see <a href='#'>this</a>"}) == [
            "'x' contains markup — split it into two keys, or do without"
        ]

    def test_a_blank_is_caught(self):
        assert "is empty" in check_strings({"x": "   "})[0]

    def test_an_unmatched_brace_is_caught(self):
        """`day {n` prints as written, which is how a count becomes furniture."""
        assert "unmatched brace" in check_strings({"day": "day {n"})[0]

    def test_a_sound_table_has_nothing_to_say(self):
        assert check_strings({"day": "Day {n} of {total}"}) == []


class TestThePayload:
    def test_it_names_the_language_once(self):
        """So the markup, the JSON-LD and the OpenGraph locale have one source."""
        assert strings_payload()["language"] == LANGUAGE

    def test_it_carries_no_language_picker(self):
        """One language and a picker for it is a control that does nothing."""
        payload = strings_payload()
        assert "languages" not in payload
        assert "default" not in payload

    def test_the_strings_travel_under_one_key(self):
        assert strings_payload({"a": "A"})["strings"] == {"a": "A"}


@given(st.text(max_size=60))
@settings(max_examples=200)
def test_placeholder_names_never_raises_and_never_invents(text):
    for name in placeholder_names(text):
        assert "{" + name + "}" in text


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8, alphabet="abcd."),
        st.text(min_size=1, max_size=20, alphabet="abc {n}{t}"),
        max_size=8,
    )
)
@settings(max_examples=200)
def test_checking_never_raises_on_arbitrary_tables(table):
    for problem in check_strings(table):
        assert problem.startswith("'")
