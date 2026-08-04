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
    is_stale,
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
        assert len(extraction.evidence_items()) == 5

    def test_a_null_time_evidence_contributes_nothing(self):
        extraction = ChapterExtraction(**MINIMAL)
        assert extraction.evidence_items() == []


def narrative_data(**narrative):
    """A minimal extraction whose people roster covers whoever the narrative names."""
    names = {
        item["name_in_text"]
        for key in ("on_stage", "named_but_not_present")
        for item in narrative.get(key, [])
    }
    places = {
        item[field]
        for item in narrative.get("on_stage", [])
        for field in ("at_name_in_text", "between_from", "between_to")
        if item.get(field) and item[field].strip()
    }
    return {
        **MINIMAL,
        "people": [{"name_in_text": n, "evidence": "x"} for n in sorted(names)],
        "places_mentioned": [
            {"name_in_text": p, "evidence": "x"} for p in sorted(places)
        ],
        "narrative": narrative,
    }


class TestNarrative:
    def test_a_null_narrative_becomes_empty(self):
        extraction = ChapterExtraction(**MINIMAL, narrative=None)
        assert extraction.narrative.on_stage == []
        assert extraction.narrative.named_but_not_present == []

    def test_null_narrative_lists_become_empty(self):
        extraction = ChapterExtraction(
            **MINIMAL, narrative={"on_stage": None, "named_but_not_present": None}
        )
        assert extraction.narrative.on_stage == []

    def test_a_blank_place_name_becomes_none(self):
        """A blank would key a phantom row into the containment map."""
        data = narrative_data(
            on_stage=[
                {"name_in_text": "Fogg", "at_name_in_text": "  ", "evidence": "x"}
            ]
        )
        assert ChapterExtraction(**data).narrative.on_stage[0].at_name_in_text is None

    def test_an_absent_narrative_still_validates(self):
        """An old file must load, or the migration is unsurvivable mid-paste."""
        assert ChapterExtraction(**MINIMAL).narrative.on_stage == []

    def test_evidence_items_covers_the_narrative_block(self):
        data = narrative_data(
            on_stage=[
                {
                    "name_in_text": "Fix",
                    "at_name_in_text": "Suez",
                    "evidence": "at Suez",
                }
            ],
            named_but_not_present=[{"name_in_text": "Fogg", "evidence": "of Mr. Fogg"}],
        )
        paths = [ref.path for ref in ChapterExtraction(**data).evidence_items()]
        assert "narrative.on_stage[0].evidence" in paths
        assert "narrative.named_but_not_present[0].evidence" in paths

    def test_a_person_on_stage_and_not_present_is_reported(self):
        data = narrative_data(
            on_stage=[{"name_in_text": "Fogg", "evidence": "x"}],
            named_but_not_present=[{"name_in_text": "fogg", "evidence": "y"}],
        )
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("both on stage and not present" in p for p in problems)

    def test_a_place_and_a_transit_together_are_reported(self):
        data = narrative_data(
            on_stage=[
                {
                    "name_in_text": "Fogg",
                    "at_name_in_text": "Suez",
                    "between_to": "Bombay",
                    "evidence": "x",
                }
            ]
        )
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("they are alternatives" in p for p in problems)

    def test_a_journey_to_the_same_place_is_reported(self):
        data = narrative_data(
            on_stage=[
                {
                    "name_in_text": "Fogg",
                    "between_from": "Suez",
                    "between_to": "suez",
                    "evidence": "x",
                }
            ]
        )
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("to itself" in p for p in problems)

    def test_a_roster_disagreement_is_reported(self):
        data = {
            **MINIMAL,
            "people": [{"name_in_text": "Fogg", "evidence": "x"}],
            "narrative": {"on_stage": [{"name_in_text": "Fix", "evidence": "y"}]},
        }
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("the two rosters" in p for p in problems)

    def test_a_place_invented_in_the_narrative_block_is_reported(self):
        """The strongest cross-check: a location that appears in no other array."""
        data = {
            **MINIMAL,
            "people": [{"name_in_text": "Fogg", "evidence": "x"}],
            "places_mentioned": [{"name_in_text": "London", "evidence": "x"}],
            "narrative": {
                "on_stage": [
                    {
                        "name_in_text": "Fogg",
                        "at_name_in_text": "Atlantis",
                        "evidence": "y",
                    }
                ]
            },
        }
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert any("Atlantis" in p and "places_mentioned" in p for p in problems)

    def test_an_extraction_from_the_old_template_is_reported_as_stale(self):
        data = {**MINIMAL, "people": [{"name_in_text": "Fogg", "evidence": "x"}]}
        extraction = ChapterExtraction(**data)
        assert is_stale(extraction)
        problems = check_extraction(extraction, expected_number=1)
        assert any("re-paste" in p for p in problems)

    def test_a_chapter_with_nobody_in_it_is_not_stale(self):
        """No people means no question to have been asked — not a missing block."""
        assert not is_stale(ChapterExtraction(**MINIMAL))

    def test_a_chapter_the_party_is_absent_from_is_not_an_error(self):
        """Chapter 5: an empty on_stage beside a full places_visited is correct."""
        data = {
            **MINIMAL,
            "people": [{"name_in_text": "Lord Albemarle", "evidence": "x"}],
            "places_visited": [
                {"name_in_text": "London", "role": "setting", "evidence": "in London"}
            ],
            "narrative": {
                "named_but_not_present": [
                    {"name_in_text": "Lord Albemarle", "evidence": "x"}
                ]
            },
        }
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert problems == []

    def test_the_same_person_twice_is_movement_not_an_error(self):
        data = narrative_data(
            on_stage=[
                {
                    "name_in_text": "Fogg",
                    "at_name_in_text": "Saville Row",
                    "evidence": "x",
                },
                {
                    "name_in_text": "Fogg",
                    "at_name_in_text": "Reform Club",
                    "evidence": "y",
                },
            ]
        )
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert problems == []

    def test_an_entry_with_no_place_at_all_is_not_an_error(self):
        """Rule 1 being obeyed: the chapter did not say where."""
        data = narrative_data(on_stage=[{"name_in_text": "Fogg", "evidence": "x"}])
        problems = check_extraction(ChapterExtraction(**data), expected_number=1)
        assert problems == []


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
