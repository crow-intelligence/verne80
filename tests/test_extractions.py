import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.extractions import (
    extract_json_object,
    load_all,
    load_extraction,
    parse_extraction_json,
    strip_code_fences,
)


def write(directory, number, payload):
    path = directory / f"chapter_{number:02d}.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), "utf-8"
    )
    return path


class TestFences:
    def test_json_fences_are_tolerated(self):
        assert parse_extraction_json('```json\n{"chapter": 1}\n```') == {"chapter": 1}

    def test_bare_fences_are_tolerated(self):
        assert parse_extraction_json('```\n{"chapter": 1}\n```') == {"chapter": 1}

    def test_bare_json_is_tolerated(self):
        assert parse_extraction_json('{"chapter": 1}') == {"chapter": 1}

    def test_stripping_is_identity_without_a_fence(self):
        assert strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_stripping_is_idempotent(self):
        once = strip_code_fences('```json\n{"a": 1}\n```')
        assert strip_code_fences(once) == once


class TestPreamble:
    def test_preamble_prose_is_tolerated(self):
        text = 'Here is the JSON you asked for:\n{"chapter": 2}\nHope that helps!'
        assert parse_extraction_json(text) == {"chapter": 2}

    def test_a_brace_inside_a_string_does_not_end_the_object_early(self):
        assert extract_json_object('prose {"a": "}"} more') == '{"a": "}"}'

    def test_an_escaped_quote_does_not_end_the_string_early(self):
        assert extract_json_object(r'{"a": "say \" }"}') == r'{"a": "say \" }"}'


class TestFailures:
    def test_malformed_json_names_the_file_and_position(self):
        with pytest.raises(ValueError, match=r"chapter_04\.json: invalid JSON at line"):
            parse_extraction_json('{"chapter": 4,,}', origin="chapter_04.json")

    def test_a_truncated_object_is_reported_not_repaired(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_extraction_json('{"chapter": 1, "summary_hover": "half a sen')

    def test_a_json_array_is_rejected(self):
        with pytest.raises(ValueError, match="expected a JSON object"):
            parse_extraction_json("[1, 2, 3]")

    def test_text_with_no_object_at_all_is_reported(self):
        with pytest.raises(ValueError, match="invalid JSON|no JSON object"):
            parse_extraction_json("I could not complete that request.")

    def test_unbalanced_braces_are_reported_as_truncation(self):
        with pytest.raises(ValueError, match="truncated"):
            extract_json_object('{"a": {"b": 1}')


class TestLoading:
    def test_a_missing_file_points_at_the_paste_workflow(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="data/prompts/README.md"):
            load_extraction(tmp_path / "chapter_07.json")

    def test_a_schema_failure_names_the_field(self, tmp_path, valid_extraction):
        broken = {**valid_extraction, "summary_hover": ""}
        path = write(tmp_path, 3, broken)
        with pytest.raises(ValueError, match="summary_hover"):
            load_extraction(path)

    def test_a_valid_file_loads(self, tmp_path, valid_extraction):
        path = write(tmp_path, 3, valid_extraction)
        assert load_extraction(path).chapter == 3

    def test_a_fenced_file_loads(self, tmp_path, valid_extraction):
        path = write(tmp_path, 3, f"```json\n{json.dumps(valid_extraction)}\n```")
        assert load_extraction(path).chapter == 3

    def test_one_bad_file_does_not_abort_the_others(self, tmp_path, valid_extraction):
        write(tmp_path, 3, valid_extraction)
        write(tmp_path, 4, "not json at all")
        loaded, problems = load_all(tmp_path, [3, 4, 5])
        assert set(loaded) == {3}
        assert len(problems) == 2

    def test_every_requested_number_is_accounted_for(self, tmp_path, valid_extraction):
        write(tmp_path, 3, valid_extraction)
        loaded, problems = load_all(tmp_path, [3, 9])
        assert len(loaded) + len(problems) == 2


class TestExtractionProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.dictionaries(
            st.text(min_size=1, max_size=10),
            st.one_of(st.integers(), st.text(max_size=20), st.none()),
            max_size=5,
        )
    )
    def test_parsing_round_trips_any_json_object(self, payload):
        assert parse_extraction_json(json.dumps(payload)) == payload

    @settings(max_examples=150, deadline=None)
    @given(
        st.dictionaries(
            st.text(min_size=1, max_size=10),
            st.one_of(st.integers(), st.text(max_size=20)),
            max_size=5,
        )
    )
    def test_fenced_and_unfenced_parse_identically(self, payload):
        raw = json.dumps(payload)
        assert parse_extraction_json(raw) == parse_extraction_json(
            f"```json\n{raw}\n```"
        )

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_only_value_error_escapes(self, text):
        try:
            result = parse_extraction_json(text)
        except ValueError:
            return
        assert isinstance(result, dict)

    @settings(max_examples=150, deadline=None)
    @given(st.text())
    def test_stripping_fences_never_raises(self, text):
        assert isinstance(strip_code_fences(text), str)
