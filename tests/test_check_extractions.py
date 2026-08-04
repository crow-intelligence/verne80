import json

from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.extractions import check_extraction_files, stated_chapter


def write(directory, number, payload):
    path = directory / f"chapter_{number:02d}.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )
    return path


def good(number):
    return {
        "chapter": number,
        "summary_hover": "Something happens.",
        "summary_detail": "Something happens. Then something else does.",
    }


class TestTheChapterKey:
    def test_a_file_whose_chapter_key_disagrees_with_its_name_is_reported(
        self, tmp_path
    ):
        """The one error that would silently attach the wrong evidence to a chapter."""
        write(tmp_path, 22, good(23))
        problems = check_extraction_files(tmp_path, expected=22)
        assert any(
            "MISMATCH" in p and "chapter_22" in p and "says 23" in p for p in problems
        )

    def test_the_chapter_key_is_found_even_in_a_malformed_file(self):
        """A broken file is the one whose number is most worth knowing."""
        number, note = stated_chapter('{\n"chapter": 21,\n"title": "THE "X" RUNS"\n}')
        assert number == 21
        assert note and note.startswith("invalid JSON")

    def test_a_document_with_no_chapter_key_is_reported(self, tmp_path):
        write(tmp_path, 1, {"summary_hover": "x"})
        assert any("NO KEY" in p for p in check_extraction_files(tmp_path, expected=1))

    def test_a_string_chapter_key_does_not_pass_as_a_number(self):
        assert stated_chapter('{"chapter": "07"}') == (None, None)

    def test_a_matching_file_is_not_reported(self, tmp_path):
        write(tmp_path, 7, good(7))
        assert check_extraction_files(tmp_path, expected=7) == [
            f"ch {n:02d}   MISSING     not pasted yet" for n in range(1, 7)
        ]


class TestTheOtherFaults:
    def test_a_missing_chapter_is_reported(self, tmp_path):
        write(tmp_path, 1, good(1))
        problems = check_extraction_files(tmp_path, expected=2)
        assert problems == ["ch 02   MISSING     not pasted yet"]

    def test_an_empty_file_is_reported(self, tmp_path):
        write(tmp_path, 1, "   \n")
        assert check_extraction_files(tmp_path, expected=1) == [
            "ch 01   EMPTY       the paste did not land"
        ]

    def test_a_malformed_file_is_reported(self, tmp_path):
        write(tmp_path, 1, '{"chapter": 1,,}')
        assert any(
            "MALFORMED" in p for p in check_extraction_files(tmp_path, expected=1)
        )

    def test_two_files_claiming_the_same_chapter_are_reported(self, tmp_path):
        write(tmp_path, 1, good(1))
        write(tmp_path, 2, good(1))
        problems = check_extraction_files(tmp_path, expected=2)
        assert any("DUPLICATE" in p and "2 files" in p for p in problems)

    def test_a_json_array_is_not_mistaken_for_an_extraction(self):
        number, note = stated_chapter("[1, 2, 3]")
        assert number is None
        assert note and "not an object" in note

    def test_a_clean_set_reports_nothing(self, tmp_path):
        for number in range(1, 6):
            write(tmp_path, number, good(number))
        assert check_extraction_files(tmp_path, expected=5) == []


class TestCheckProperties:
    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=200))
    def test_reading_the_chapter_key_never_raises(self, text):
        number, note = stated_chapter(text)
        assert number is None or isinstance(number, int)
        assert note is None or isinstance(note, str)

    @settings(max_examples=100, deadline=None)
    @given(st.integers(min_value=1, max_value=12))
    def test_a_complete_clean_set_is_always_silent(self, tmp_path_factory, count):
        directory = tmp_path_factory.mktemp("extractions")
        for number in range(1, count + 1):
            write(directory, number, good(number))
        assert check_extraction_files(directory, expected=count) == []

    @settings(max_examples=100, deadline=None)
    @given(
        st.integers(min_value=1, max_value=12), st.integers(min_value=1, max_value=12)
    )
    def test_any_disagreement_between_name_and_key_is_caught(
        self, tmp_path_factory, named, stated
    ):
        directory = tmp_path_factory.mktemp("extractions")
        write(directory, named, good(stated))
        problems = check_extraction_files(directory, expected=named)
        assert any("MISMATCH" in p for p in problems) == (named != stated)
