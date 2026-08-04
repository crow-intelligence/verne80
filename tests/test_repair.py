import json
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.repair import (
    drop_forbidden_fields,
    render_json,
    repair_file,
    repair_text,
    sniff_indent,
)
from verne80.schema import ChapterExtraction

# The two real failures, verbatim. Fixtures made from the actual broken bytes rather
# than an approximation of them, so these tests fail if the repair stops handling what
# it was built for.
CH21_TITLE = (
    "IN WHICH THE MASTER OF THE "
    '"TANKADERE"'
    " RUNS GREAT RISK OF LOSING A REWARD OF TWO HUNDRED POUNDS"
)
CH21_BROKEN = (
    '{\n"chapter": 21,\n"title": "' + CH21_TITLE + '",\n'
    '"summary_hover": "A typhoon nearly costs the pilot his reward.",\n'
    '"summary_detail": "A typhoon strikes. The pilot holds his course.",\n'
    '"next": "ok"\n}'
)

CH12_EVIDENCE = (
    'the guide entered a thick forest... "What\u2019s the matter?" asked Sir Francis'
)
CH12_BROKEN = '{\n"a": 1,\n"evidence": "' + CH12_EVIDENCE + '"\n}'

MINIMAL = {
    "chapter": 18,
    "summary_hover": "They sail for Yokohama.",
    "summary_detail": "They sail for Yokohama. The boat has already gone.",
}


def write(tmp_path, number, text):
    path = tmp_path / f"chapter_{number:02d}.json"
    path.write_text(
        text if isinstance(text, str) else json.dumps(text), encoding="utf-8"
    )
    return path


class TestUnescapedQuotes:
    def test_an_unescaped_quote_in_a_title_is_recovered(self):
        data, repaired = repair_text(CH21_BROKEN)
        assert repaired
        assert data["title"] == CH21_TITLE

    def test_an_unescaped_quote_in_an_evidence_string_is_recovered(self):
        data, repaired = repair_text(CH12_BROKEN)
        assert repaired
        assert data["evidence"] == CH12_EVIDENCE

    def test_a_repair_never_shortens_a_string(self):
        """The truncation guard, and the reason this can be trusted at all.

        The real hazard is a repairer that ends the string at the first stray mark
        instead of escaping it, silently losing everything after it. Both recovered
        strings must still carry every word they started with.
        """
        for broken, key, original in (
            (CH21_BROKEN, "title", CH21_TITLE),
            (CH12_BROKEN, "evidence", CH12_EVIDENCE),
        ):
            recovered = repair_text(broken)[0][key]
            assert recovered.split() == original.split()

    def test_the_keys_after_the_break_survive(self):
        """A truncating repair tends to swallow the rest of the object too."""
        recovered = repair_text(CH21_BROKEN)[0]
        assert recovered["next"] == "ok"
        assert recovered["summary_hover"].startswith("A typhoon")


class TestLeavingGoodFilesAlone:
    def test_a_valid_document_is_not_repaired(self):
        data, repaired = repair_text('{"chapter": 1, "title": "A TITLE"}')
        assert not repaired
        assert data == {"chapter": 1, "title": "A TITLE"}

    def test_a_fenced_document_is_not_repaired_either(self):
        """The strict tiers already handle fences; the repairer never sees them."""
        _, repaired = repair_text('```json\n{"chapter": 1}\n```')
        assert not repaired

    def test_a_valid_file_is_left_alone(self, tmp_path):
        path = write(tmp_path, 1, {**MINIMAL, "chapter": 1})
        result = repair_file(path)
        assert not result.changed
        assert result.problem is None


class TestForbiddenFields:
    def test_the_chapter_eighteen_role_is_dropped(self):
        data = {
            **MINIMAL,
            "places_mentioned": [
                {"name_in_text": "Yokohama", "role": "mention", "evidence": "the boat"}
            ],
        }
        cleaned, dropped = drop_forbidden_fields(data)
        assert dropped == ["places_mentioned[0].role"]
        assert cleaned["places_mentioned"][0] == {
            "name_in_text": "Yokohama",
            "evidence": "the boat",
        }

    def test_only_fields_pydantic_rejected_are_dropped(self):
        """A legitimate field beside a forbidden one must survive untouched."""
        data = {
            **MINIMAL,
            "places_visited": [
                {
                    "name_in_text": "Yokohama",
                    "role": "arrival",
                    "evidence": "they landed",
                    "invented": "x",
                }
            ],
        }
        cleaned, dropped = drop_forbidden_fields(data)
        assert dropped == ["places_visited[0].invented"]
        assert cleaned["places_visited"][0]["role"] == "arrival"

    def test_every_dropped_field_is_named(self):
        data = {
            **MINIMAL,
            "places_mentioned": [
                {"name_in_text": f"P{i}", "role": "mention", "evidence": "x"}
                for i in range(8)
            ],
        }
        cleaned, dropped = drop_forbidden_fields(data)
        assert len(dropped) == 8
        assert not any("role" in entry for entry in cleaned["places_mentioned"])

    def test_a_valid_document_loses_nothing(self):
        cleaned, dropped = drop_forbidden_fields(dict(MINIMAL))
        assert dropped == []
        assert cleaned == MINIMAL

    def test_a_failure_that_is_not_a_forbidden_field_drops_nothing(self):
        """A missing required field is a real problem, not something to prune."""
        cleaned, dropped = drop_forbidden_fields({"chapter": 18})
        assert dropped == []
        assert cleaned == {"chapter": 18}


class TestUnrecoverable:
    def test_a_file_that_cannot_be_repaired_is_reported_not_guessed_at(self, tmp_path):
        path = write(tmp_path, 4, "I could not complete that request.")
        result = repair_file(path)
        assert result.problem
        assert result.text == ""

    def test_an_empty_file_is_reported(self, tmp_path):
        assert "empty" in (repair_file(write(tmp_path, 5, "   ")).problem or "")

    def test_a_missing_file_is_reported(self, tmp_path):
        assert repair_file(tmp_path / "absent.json").problem == "not found"

    def test_a_document_still_invalid_after_repair_names_the_field(self, tmp_path):
        path = write(tmp_path, 6, {"chapter": 6})
        result = repair_file(path)
        assert "still invalid after repair" in (result.problem or "")
        assert "summary_hover" in (result.problem or "")


class TestFormatting:
    def test_a_flat_document_stays_flat(self):
        """Gemini writes these files unindented; re-indenting buries the repair."""
        assert sniff_indent('{\n"chapter": 1\n}') == 0

    def test_an_indented_document_keeps_its_width(self):
        assert sniff_indent('{\n    "chapter": 1\n}') == 4

    def test_a_one_line_document_falls_back_to_the_default(self):
        assert sniff_indent('{"chapter": 1}') == 2

    def test_accented_characters_are_not_escaped(self):
        assert "café" in render_json({"note": "café"})

    def test_the_repaired_file_keeps_the_original_indentation(self, tmp_path):
        path = write(tmp_path, 21, CH21_BROKEN.replace(',\n"next": "ok"', ""))
        result = repair_file(path)
        assert result.syntax_repaired
        assert result.problem is None
        assert '\n"chapter": 21,' in result.text


class TestRepairProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.dictionaries(
            st.text(alphabet="abcdef", min_size=1, max_size=6),
            st.one_of(st.integers(), st.text(max_size=20), st.none()),
            max_size=5,
        )
    )
    def test_repairing_valid_json_round_trips(self, payload):
        data, repaired = repair_text(json.dumps(payload))
        assert data == payload
        assert not repaired

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=120))
    def test_only_value_error_escapes(self, text):
        try:
            data, _ = repair_text(text)
        except ValueError:
            return
        assert isinstance(data, dict)

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=120))
    def test_repair_is_idempotent(self, text):
        try:
            once, _ = repair_text(text)
        except ValueError:
            return
        twice, again = repair_text(json.dumps(once))
        assert twice == once
        assert not again

    @settings(max_examples=150, deadline=None)
    @given(st.integers(min_value=0, max_value=8))
    def test_rendered_json_reparses_at_any_indent(self, indent):
        payload = {"chapter": 1, "note": "café"}
        assert json.loads(render_json(payload, indent=indent)) == payload


class TestTheRealFiles:
    """The committed extractions, after repair: all thirty-seven readable."""

    def test_every_committed_extraction_parses_and_validates(self):
        from pathlib import Path

        directory = Path("data/extractions")
        paths = sorted(directory.glob("chapter_*.json"))
        if len(paths) != 37:
            pytest.skip("not all thirty-seven chapters are pasted")
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            ChapterExtraction.model_validate(data)

    def test_no_committed_extraction_still_needs_repair(self):
        from pathlib import Path

        directory = Path("data/extractions")
        paths = sorted(directory.glob("chapter_*.json"))
        if len(paths) != 37:
            pytest.skip("not all thirty-seven chapters are pasted")
        assert [p.name for p in paths if repair_file(p).changed] == []

    def test_the_repaired_chapter_twelve_quote_is_whole(self):
        from pathlib import Path

        path = Path("data/extractions/chapter_12.json")
        if not path.exists():
            pytest.skip("chapter 12 is not pasted")
        text = path.read_text(encoding="utf-8")
        assert "asked Sir Francis" in text
        assert re.search(r'\\"What\u2019s the matter\?\\"', text)
