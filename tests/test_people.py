"""The display roster: folding printed names without losing any of them."""

from __future__ import annotations

import json
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from verne80.normalize import match_key
from verne80.people import Cast, check_cast, load_cast, looks_like_a_role
from verne80.position import TRACKS_JSON

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTIONS = REPO_ROOT / "data" / "extractions"


@pytest.fixture(scope="module")
def cast():
    return load_cast()


@pytest.fixture(scope="module")
def printed():
    """Every name the book puts on stage or names as absent, with its chapter."""
    out = []
    for path in sorted(EXTRACTIONS.glob("chapter_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        narrative = data["narrative"]
        for entry in narrative["on_stage"] + narrative["named_but_not_present"]:
            out.append((data["chapter"], entry["name_in_text"]))
    return out


# ------------------------------------------------------------------ the shipped file


class TestTheShippedRoster:
    def test_it_is_sound(self, cast):
        assert check_cast(cast) == []

    def test_every_curated_entry_has_a_reason_to_exist(self, cast, printed):
        """Two reasons are allowed, and nothing else.

        Either the book prints the person more than one way and a fold is needed, or
        the person has a track and the entry exists to be checked against
        ``tracks.json``. Fix qualifies on the second ground only: the book calls him
        Fix throughout, and the passthrough would already get that right. Any other
        entry is an assertion with nothing behind it and one more thing to keep in step.
        """
        spellings: dict[str, set[str]] = {}
        for _, name in printed:
            spellings.setdefault(cast.fold(name).key, set()).add(name)
        for identifier, entry in cast.people.items():
            folded = len(spellings.get(identifier, set())) > 1
            assert folded or entry.get("track"), (
                f"{identifier!r} is curated, is printed one way, and has no track — "
                "the passthrough already gets it right"
            )

    def test_no_curated_spelling_is_one_the_book_never_prints(self, cast, printed):
        """Except the ones tracks.json owns, which are checked against it instead."""
        seen = {name for _, name in printed}
        owned = {
            alias
            for track in json.loads(TRACKS_JSON.read_text(encoding="utf-8"))["tracks"]
            for alias in track["aliases"]
        }
        for entry in cast.people.values():
            for alias in entry["aliases"]:
                assert alias in seen or alias in owned, alias

    def test_no_listed_role_is_a_name_the_book_never_prints(self, cast, printed):
        seen = {name for _, name in printed}
        for entry in cast.roles:
            assert entry["name"] in seen, entry["name"]

    def test_every_entry_says_why(self, cast):
        """House pattern: a curation file that does not argue is a list of opinions."""
        for entry in list(cast.people.values()) + list(cast.roles):
            assert entry.get("why", "").strip()


class TestAgreementWithTracksJson:
    """The two files answer different questions and must not drift.

    ``tracks.json`` says who gets a position series; ``people.json`` says what to call
    them. Three characters are in both, and an alias added to one and forgotten in the
    other is exactly the kind of divergence nothing else would notice.
    """

    def test_every_track_alias_is_a_people_alias(self, cast):
        by_track = {
            str(entry["track"]): entry
            for entry in cast.people.values()
            if entry.get("track")
        }
        for track in json.loads(TRACKS_JSON.read_text(encoding="utf-8"))["tracks"]:
            assert track["track"] in by_track, track["track"]
            mine = {match_key(a) for a in by_track[track["track"]]["aliases"]}
            for alias in track["aliases"]:
                assert match_key(alias) in mine, f"{track['track']}: {alias}"

    def test_every_claimed_track_is_a_real_one(self, cast):
        real = {
            track["track"]
            for track in json.loads(TRACKS_JSON.read_text(encoding="utf-8"))["tracks"]
        }
        for entry in cast.people.values():
            if entry.get("track"):
                assert entry["track"] in real, entry["track"]


# ------------------------------------------------------------------------ the rule


class TestTellingAPersonFromARole:
    def test_a_lower_case_name_is_a_role(self):
        assert looks_like_a_role("engineer")
        assert looks_like_a_role("the cabman")

    def test_a_capitalised_name_is_a_person(self):
        assert not looks_like_a_role("Phileas Fogg")
        assert not looks_like_a_role("the Barings")

    def test_the_rule_is_right_about_almost_everything(self, cast, printed):
        """Stated as a number so a change to the data shows up as a change to it."""
        names = {name for _, name in printed}
        wrong = {
            name
            for name in names
            if looks_like_a_role(name) != (cast.fold(name).kind == "role")
        }
        assert len(wrong) == len(cast.roles), (
            f"the rule is now wrong about {len(wrong)} names, and people.json lists "
            f"{len(cast.roles)}"
        )


# ---------------------------------------------------------------------- the folds


class TestTheFolds:
    def test_the_printed_spelling_always_survives(self, cast):
        assert cast.fold("Mr. Fogg").name_in_text == "Mr. Fogg"

    def test_two_spellings_of_one_person_share_a_key(self, cast):
        assert cast.fold("Mr. Fogg").key == cast.fold("Phileas Fogg").key

    def test_the_book_disagreeing_with_itself_is_reconciled_not_erased(self, cast):
        """Chapter 24 of Gutenberg #103 really does print 'John Busby'."""
        busby = cast.fold("John Busby")
        assert busby.key == cast.fold("John Bunsby").key
        assert busby.display == "John Bunsby"
        assert busby.name_in_text == "John Busby"

    def test_a_role_is_never_folded_onto_a_person(self, cast):
        """Chapter 26 has Fix and a detective on stage, and they are two men."""
        assert cast.fold("detective").key != cast.fold("Fix").key
        assert cast.fold("detective").kind == "role"

    def test_a_capitalised_people_is_still_a_role(self, cast):
        assert cast.fold("Sioux").kind == "role"
        assert cast.fold("Parsee").kind == "role"

    def test_a_surname_never_folds_on_its_own(self, cast):
        """Joe Smith the prophet and Rev. Decimus Smith are different men."""
        assert cast.fold("Joe Smith").key != cast.fold("Rev. Decimus Smith").key

    def test_an_uncurated_name_passes_through(self, cast):
        one = cast.fold("Aouda")
        assert (one.key, one.display, one.kind) == ("aouda", "Aouda", "person")


class TestTheWholeBook:
    def test_every_printed_name_folds(self, cast, printed):
        for chapter, name in printed:
            assert cast.fold(name).name_in_text == name, (chapter, name)

    def test_no_chapter_merges_two_people_who_are_both_in_it(self, cast, printed):
        """A fold that swallowed a neighbour would show up here and nowhere else."""
        by_chapter: dict[int, list[str]] = {}
        for chapter, name in printed:
            by_chapter.setdefault(chapter, []).append(name)
        for chapter, names in by_chapter.items():
            for name in names:
                one = cast.fold(name)
                if one.kind != "person" or one.key not in cast.people:
                    continue
                aliases = {match_key(a) for a in cast.people[one.key]["aliases"]}
                clashing = [
                    other
                    for other in names
                    if cast.fold(other).key == one.key
                    and match_key(other) not in aliases
                ]
                assert clashing == [], (chapter, one.key, clashing)


# ---------------------------------------------------------------------- properties


@given(st.text(max_size=40))
@settings(max_examples=400)
def test_the_quotation_always_survives(text):
    """The property the module exists to keep. A well-meaning tidy-up fails here."""
    assert load_cast().fold(text).name_in_text == text


@given(st.text(max_size=40))
@settings(max_examples=400)
def test_folding_never_raises_and_always_names_a_kind(text):
    one = load_cast().fold(text)
    assert one.kind in {"person", "role"}
    assert isinstance(one.key, str)


@given(st.text(max_size=40))
@settings(max_examples=200)
def test_the_display_name_folds_back_to_the_same_person(text):
    """Which is only true if every display name is one of its own aliases."""
    cast = load_cast()
    one = cast.fold(text)
    assert cast.fold(one.display).key == one.key


def test_a_display_name_the_book_never_prints_is_refused():
    bad = Cast([{"person": "x", "display": "Zed", "aliases": ["Ex"]}], [])
    assert check_cast(bad) == [
        "'x' displays as 'Zed', which is not one of its own printed spellings"
    ]


def test_an_alias_claimed_twice_is_refused():
    bad = Cast(
        [
            {"person": "a", "display": "Ex", "aliases": ["Ex"]},
            {"person": "b", "display": "Ex", "aliases": ["Ex"]},
        ],
        [],
    )
    assert any("claimed by both" in problem for problem in check_cast(bad))


def test_a_name_that_is_both_a_person_and_a_role_is_refused():
    bad = Cast(
        [{"person": "a", "display": "Fix", "aliases": ["Fix"]}], [{"name": "Fix"}]
    )
    assert any("both a person's spelling and a role" in p for p in check_cast(bad))
