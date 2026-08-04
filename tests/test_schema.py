import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from verne80.schema import (
    ChapterExtraction,
    PlaceRole,
    ScheduleStatus,
    TransportLeg,
    TransportMode,
    check_extraction,
)

MINIMAL = {
    "chapter": 1,
    "summary_hover": "Fogg wagers twenty thousand pounds.",
    "summary_detail": "Fogg wagers twenty thousand pounds. He leaves at once.",
}


class TestTheFromKeyword:
    def test_from_is_aliased_not_dropped(self):
        leg = TransportLeg(
            **{
                "mode": "steamer",
                "from": "Suez",
                "to": "Bombay",
                "evidence": "the Mongolia",
            }
        )
        assert leg.from_ == "Suez"

    def test_dumping_by_alias_round_trips(self):
        leg = TransportLeg(
            **{
                "mode": "railway",
                "from": "Bombay",
                "to": "Calcutta",
                "evidence": "the train",
            }
        )
        assert TransportLeg(**leg.model_dump(by_alias=True)) == leg


class TestNullTolerance:
    def test_null_money_becomes_empty(self):
        extraction = ChapterExtraction(**MINIMAL, money=None)
        assert extraction.money.amounts == []
        assert extraction.money.fogg_remaining_stated is None

    def test_null_amounts_becomes_empty(self):
        extraction = ChapterExtraction(**MINIMAL, money={"amounts": None})
        assert extraction.money.amounts == []

    def test_null_lists_become_empty(self):
        extraction = ChapterExtraction(
            **MINIMAL,
            places_visited=None,
            places_mentioned=None,
            people=None,
            transport=None,
        )
        assert extraction.places_visited == []
        assert extraction.transport == []

    def test_null_time_becomes_unknown(self):
        extraction = ChapterExtraction(**MINIMAL, time=None)
        assert extraction.time.schedule_status is ScheduleStatus.UNKNOWN

    def test_null_schedule_status_becomes_unknown(self):
        extraction = ChapterExtraction(**MINIMAL, time={"schedule_status": None})
        assert extraction.time.schedule_status is ScheduleStatus.UNKNOWN

    def test_money_defaults_to_empty_without_being_mentioned(self):
        """The correct and expected answer for most chapters."""
        extraction = ChapterExtraction(**MINIMAL)
        assert extraction.money.amounts == []


class TestCoercion:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("train", TransportMode.RAILWAY),
            ("Rail", TransportMode.RAILWAY),
            ("steamship", TransportMode.STEAMER),
            ("wind-sled", TransportMode.SLEDGE),
            ("on foot", TransportMode.ON_FOOT),
            ("palanquin", TransportMode.CARRIAGE),
        ],
    )
    def test_spelling_variants_fold_onto_schema_terms(self, written, expected):
        leg = TransportLeg(mode=written, evidence="x")
        assert leg.mode is expected

    def test_an_unknown_mode_becomes_other_rather_than_failing(self):
        assert TransportLeg(mode="balloon", evidence="x").mode is TransportMode.OTHER

    def test_unknown_place_role_raises(self):
        """Only four values, and a wrong one silently corrupts the route."""
        with pytest.raises(ValidationError):
            ChapterExtraction(
                **MINIMAL,
                places_visited=[
                    {"name_in_text": "Suez", "role": "stopover", "evidence": "at Suez"}
                ],
            )


class TestStrictness:
    def test_extra_field_is_rejected(self):
        with pytest.raises(ValidationError):
            ChapterExtraction(**MINIMAL, invented_field="surprise")

    def test_chapter_number_must_be_in_range(self):
        with pytest.raises(ValidationError):
            ChapterExtraction(**{**MINIMAL, "chapter": 38})

    def test_an_empty_evidence_string_is_rejected(self):
        with pytest.raises(ValidationError):
            ChapterExtraction(
                **MINIMAL,
                places_mentioned=[{"name_in_text": "Suez", "evidence": ""}],
            )


class TestEvidenceItems:
    def test_addresses_point_at_the_right_field(self, valid_extraction):
        paths = [
            ref.path for ref in ChapterExtraction(**valid_extraction).evidence_items()
        ]
        assert "places_visited[0].evidence" in paths
        assert "money.amounts[0].evidence" in paths
        assert "transport[0].evidence" in paths

    def test_the_count_matches_the_non_empty_evidence_strings(self, valid_extraction):
        extraction = ChapterExtraction(**valid_extraction)
        assert len(extraction.evidence_items()) == 4

    def test_a_null_time_evidence_contributes_nothing(self):
        extraction = ChapterExtraction(**MINIMAL)
        assert extraction.evidence_items() == []


class TestEditorialChecks:
    def test_a_mismatched_chapter_number_is_reported(self):
        problems = check_extraction(ChapterExtraction(**MINIMAL), expected_number=3)
        assert problems == ["chapter field says 1 but the file is chapter 03"]

    def test_an_overlong_hover_summary_is_reported(self):
        data = {**MINIMAL, "summary_hover": " ".join(["word"] * 30)}
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("summary_hover is 30 words" in problem for problem in problems)

    def test_a_one_sentence_detail_summary_is_reported(self):
        data = {**MINIMAL, "summary_detail": "Only one sentence here."}
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("summary_detail has 1 sentences" in problem for problem in problems)

    def test_a_remaining_sum_with_no_amounts_is_the_hallucination_smell(self):
        data = {**MINIMAL, "money": {"amounts": [], "fogg_remaining_stated": "£12,000"}}
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("invented figures look exactly like this" in p for p in problems)

    def test_a_place_listed_as_both_visited_and_mentioned_is_reported(self):
        data = {
            **MINIMAL,
            "places_visited": [
                {"name_in_text": "Suez", "role": "arrival", "evidence": "reached Suez"}
            ],
            "places_mentioned": [{"name_in_text": "suez", "evidence": "Suez again"}],
        }
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("both visited and mentioned" in problem for problem in problems)

    def test_a_duplicated_visited_place_is_reported(self):
        place = {"name_in_text": "Suez", "role": "arrival", "evidence": "reached Suez"}
        data = {**MINIMAL, "places_visited": [place, dict(place)]}
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("lists a place twice" in problem for problem in problems)

    def test_a_title_mismatch_against_the_index_is_reported(self):
        data = {**MINIMAL, "title": "A DIFFERENT TITLE"}
        problems = check_extraction(
            ChapterExtraction(**data),
            expected_number=1,
            expected_title="IN WHICH FOGG WAGERS",
        )
        assert any("does not match index.json" in problem for problem in problems)

    def test_a_clean_extraction_reports_nothing(self, valid_extraction):
        problems = check_extraction(
            ChapterExtraction(**valid_extraction),
            expected_number=3,
            expected_title="IN WHICH THE ELEPHANT IS BOUGHT",
        )
        assert problems == []


class TestSchemaProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.sampled_from(list(TransportMode)),
        st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    )
    def test_dumping_by_alias_always_round_trips(self, mode, origin, destination):
        leg = TransportLeg(
            mode=mode, evidence="some evidence", **{"from": origin, "to": destination}
        )
        assert TransportLeg(**leg.model_dump(by_alias=True)) == leg

    @settings(max_examples=150, deadline=None)
    @given(st.sampled_from(list(PlaceRole)), st.integers(min_value=1, max_value=37))
    def test_a_full_extraction_round_trips(self, role, number):
        data = {
            **MINIMAL,
            "chapter": number,
            "places_visited": [
                {"name_in_text": "Suez", "role": role.value, "evidence": "at Suez"}
            ],
        }
        model = ChapterExtraction(**data)
        assert ChapterExtraction(**model.model_dump(by_alias=True)) == model

    @settings(max_examples=150, deadline=None)
    @given(st.integers(min_value=1, max_value=37))
    def test_check_extraction_never_raises(self, number):
        problems = check_extraction(
            ChapterExtraction(**MINIMAL), expected_number=number
        )
        assert all(isinstance(problem, str) for problem in problems)
