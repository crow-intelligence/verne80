import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.gazetteer import (
    GazetteerCache,
    PlaceCandidate,
    best_candidate,
    haversine_km,
    is_place,
    merge_candidates,
    name_changed,
    nearest_km,
    parse_binding,
    place_search_query,
    resolve_place,
    score_candidate,
    sparql_string,
)

# The eight resolved itinerary nodes, so proximity is scored against a real route rather
# than a contrivance. This is the state everything after the nine-node pass runs in.
ROUTE = [
    (51.51, -0.13),  # London
    (29.97, 32.53),  # Suez
    (19.08, 72.88),  # Bombay
    (22.57, 88.36),  # Calcutta
    (22.32, 114.17),  # Hong Kong
    (35.44, 139.64),  # Yokohama
    (37.77, -122.42),  # San Francisco
    (40.71, -74.01),  # New York
]

MUMBAI = PlaceCandidate(
    "Q1156",
    "Mumbai",
    "Bombay",
    19.07,
    72.87,
    entity_type="megacity",
    entity_type_qid="Q1637706",
    country="India",
    sitelinks=280,
)
BOMBAY_BEACH = PlaceCandidate(
    "Q1361",
    "Bombay Beach",
    "Bombay",
    33.35,
    -115.73,
    entity_type="CDP",
    entity_type_qid="Q498162",
    country="United States",
    sitelinks=20,
)


class TestTheQuery:
    def test_a_quoted_vessel_name_does_not_break_the_query(self):
        """The extractions really do carry '"Mongolia"' with the marks in the name."""
        assert 'mwapi:search "the \\"Mongolia\\""' in place_search_query(
            'the "Mongolia"'
        )

    def test_a_coordinate_is_required_not_optional(self):
        """Gating here removes the person and the film before ranking ever sees them."""
        query = place_search_query("Bombay")
        assert "?item wdt:P625 ?coord ." in query
        assert "OPTIONAL { ?item wdt:P625" not in query

    def test_the_english_label_is_pinned(self):
        """A Bengali label in modern_name would report a rename that never happened."""
        assert 'FILTER(LANG(?enLabel) = "en")' in place_search_query("Bombay")

    def test_the_alias_is_selected(self):
        """The alias is where 'Bombay' lives on Q1156 — the old name and the new one."""
        assert "?item skos:altLabel ?alias" in place_search_query("Bombay")

    def test_a_backslash_is_escaped_before_the_quote(self):
        assert sparql_string("a\\b") == '"a\\\\b"'


class TestRanking:
    def test_a_person_named_henrietta_is_not_a_place(self):
        person = PlaceCandidate(
            "Q42", "Henrietta", "", 51.5, -0.1, entity_type_qid="Q5"
        )
        assert not is_place(person)
        assert score_candidate(person, "Henrietta")[0] == 0.0

    def test_a_ship_is_never_a_pin(self):
        ship = PlaceCandidate("Q9", "Mongolia", "", 0.0, 0.0, entity_type_qid="Q11446")
        assert not is_place(ship)

    def test_a_namesake_on_the_route_beats_a_more_famous_one_off_it(self):
        """The signal that is ours alone; no measure of prominence would say this."""
        ogden_utah = PlaceCandidate("Q49255", "Ogden", "", 41.22, -111.97, sitelinks=60)
        ogden_australia = PlaceCandidate(
            "Q999", "Ogden", "", -27.5, 153.0, sitelinks=300
        )
        winner, _ = best_candidate([ogden_australia, ogden_utah], "Ogden", near=ROUTE)
        assert winner.qid == "Q49255"

    def test_an_exactly_named_place_beats_a_nearer_one_named_differently(self):
        """Name buckets dominate proximity; the text named a station, not a district."""
        exact = PlaceCandidate("Q1", "Ogden", "", -27.5, 153.0)
        near_but_wrong = PlaceCandidate("Q2", "Ogden Valley", "", 41.3, -111.8)
        winner, _ = best_candidate([near_but_wrong, exact], "Ogden", near=ROUTE)
        assert winner.qid == "Q1"

    def test_bombay_resolves_to_mumbai_and_is_marked_renamed(self):
        answer = resolve_place("bombay", "Bombay", [BOMBAY_BEACH, MUMBAI], near=ROUTE)
        assert answer.modern_name == "Mumbai"
        assert answer.name_changed
        assert answer.confidence > 0.9

    def test_two_close_candidates_are_reported_as_uncertain(self):
        """Both score well. One of them is wrong and we cannot say which."""
        one = PlaceCandidate("Q1", "Green River", "", 41.5, -109.4, sitelinks=30)
        other = PlaceCandidate("Q2", "Green River", "", 41.6, -109.3, sitelinks=28)
        _, confidence = best_candidate([one, other], "Green River", near=ROUTE)
        assert confidence < 0.7

    def test_a_lone_exact_match_is_confident(self):
        aden = PlaceCandidate("Q3492", "Aden", "", 12.79, 45.03, sitelinks=140)
        _, confidence = best_candidate([aden], "Aden", near=ROUTE)
        assert confidence > 0.7

    def test_the_winner_is_always_one_of_the_candidates(self):
        winner, _ = best_candidate([BOMBAY_BEACH, MUMBAI], "Bombay", near=ROUTE)
        assert winner in (BOMBAY_BEACH, MUMBAI)

    def test_an_empty_list_resolves_to_nothing(self):
        assert best_candidate([], "Kholby") == (None, 0.0)


class TestNames:
    def test_a_rename_is_a_rename(self):
        assert name_changed("Bombay", "Mumbai")

    def test_an_unchanged_name_is_not(self):
        assert not name_changed("Yokohama", "Yokohama")

    def test_a_disambiguating_parenthetical_is_not_a_rename(self):
        """Wikidata housekeeping must not put a 'renamed' badge on the dashboard."""
        assert not name_changed("Suez", "Suez (city)")

    def test_typography_is_not_a_rename(self):
        assert not name_changed("Yokohama", "yokohama")

    def test_nothing_resolved_is_not_a_rename(self):
        assert not name_changed("Kholby", None)


class TestResolution:
    def test_a_place_with_no_modern_referent_resolves_to_nothing(self):
        answer = resolve_place("kholby", "Kholby", [])
        assert not answer.resolved
        assert answer.source == "none"
        assert answer.why

    def test_candidates_that_are_none_of_them_places_resolve_to_nothing(self):
        person = PlaceCandidate(
            "Q42", "Henrietta", "", 51.5, -0.1, entity_type_qid="Q5"
        )
        answer = resolve_place("henrietta", "Henrietta", [person])
        assert not answer.resolved
        assert "none of them a place" in answer.why

    def test_a_curated_spelling_is_recorded_in_the_why(self):
        """A resolution that only worked because a human typed a hint should say so."""
        burhanpur = PlaceCandidate("Q1", "Burhanpur", "", 21.3, 76.23, sitelinks=20)
        answer = resolve_place(
            "burhampoor",
            "Burhampoor",
            [burhanpur],
            near=ROUTE,
            modern_hint="Burhanpur",
        )
        assert "curated spelling" in answer.why
        assert answer.name_changed

    def test_the_runners_up_are_kept_for_the_popup(self):
        """The correction you most want is 'no, the other one' — it must be to hand."""
        answer = resolve_place("bombay", "Bombay", [BOMBAY_BEACH, MUMBAI], near=ROUTE)
        assert answer.n_candidates == 2
        assert {c.qid for c in answer.candidates} == {"Q1156", "Q1361"}

    def test_a_low_confidence_answer_says_so(self):
        one = PlaceCandidate("Q1", "Green River", "", 41.5, -109.4)
        other = PlaceCandidate("Q2", "Green River", "", 41.6, -109.3)
        answer = resolve_place("green river", "Green River", [one, other], near=ROUTE)
        assert "check this one" in answer.why


class TestParsing:
    def test_a_binding_becomes_a_candidate(self):
        row = {
            "item": {"value": "http://www.wikidata.org/entity/Q1156"},
            "enLabel": {"value": "Mumbai"},
            "alias": {"value": "Bombay"},
            "lat": {"value": "19.0761"},
            "lon": {"value": "72.8775"},
            "sitelinks": {"value": "280"},
        }
        candidate = parse_binding(row)
        assert (candidate.qid, candidate.label, candidate.sitelinks) == (
            "Q1156",
            "Mumbai",
            280,
        )

    def test_a_missing_optional_does_not_break_the_parse(self):
        row = {"item": {"value": "Q1"}, "enLabel": {"value": "X"}}
        assert parse_binding(row).country is None

    def test_the_row_fan_out_collapses_to_one_candidate(self):
        """Three aliases and two P31 values are six rows and one place."""
        rows = [
            PlaceCandidate("Q1156", "Mumbai", "Bombay"),
            PlaceCandidate("Q1156", "Mumbai", "Bombai"),
            PlaceCandidate("Q1361", "Bombay Beach", ""),
        ]
        merged = merge_candidates(rows)
        assert len(merged) == 2
        assert merged[0].matched_alias == "Bombay | Bombai"

    def test_no_alias_is_lost_in_the_merge(self):
        rows = [PlaceCandidate("Q1", "X", f"a{i}") for i in range(4)]
        assert merge_candidates(rows)[0].matched_alias == "a0 | a1 | a2 | a3"


class TestTheCache:
    def test_the_cache_key_is_the_same_key_the_csv_uses(self):
        """So an entry joins to a row by eye, and the three Mongolias are one entry."""
        assert GazetteerCache.key("wikidata", "“Mongolia”") == (
            GazetteerCache.key("wikidata", "Mongolia")
        )

    def test_the_two_sources_never_collide(self):
        assert GazetteerCache.key("wikidata", "Aden") != GazetteerCache.key(
            "nominatim", "Aden"
        )

    def test_a_cached_empty_answer_is_not_a_miss(self):
        """An endpoint that had nothing is a real answer, not a cache miss."""
        cache = GazetteerCache(path=None, entries={})
        cache.put("wikidata:search:v1:kholby", "Kholby", [], "endpoint")
        assert cache.get("wikidata:search:v1:kholby") == []
        assert cache.get("wikidata:search:v1:absent") is None

    def test_a_round_trip_keeps_every_field(self, tmp_path):
        cache = GazetteerCache(path=tmp_path / "cache.json")
        cache.put("wikidata:search:v1:bombay", "Bombay", [MUMBAI], "endpoint")
        cache.save()
        reloaded = GazetteerCache.load(tmp_path / "cache.json")
        assert reloaded.get("wikidata:search:v1:bombay") == [MUMBAI]

    def test_a_missing_cache_file_is_not_an_error(self, tmp_path):
        assert GazetteerCache.load(tmp_path / "absent.json").entries == {}

    def test_the_saved_file_records_its_attribution(self, tmp_path):
        cache = GazetteerCache(path=tmp_path / "cache.json")
        cache.save()
        data = json.loads((tmp_path / "cache.json").read_text())
        assert "CC0" in data["attribution"]["wikidata"]
        assert "OpenStreetMap" in data["attribution"]["nominatim"]


class TestGazetteerProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.floats(min_value=-89, max_value=89),
        st.floats(min_value=-179, max_value=179),
        st.floats(min_value=-89, max_value=89),
        st.floats(min_value=-179, max_value=179),
    )
    def test_distance_is_symmetric_and_bounded(self, lat1, lon1, lat2, lon2):
        one, other = (lat1, lon1), (lat2, lon2)
        forward = haversine_km(one, other)
        assert forward == pytest.approx(haversine_km(other, one))
        assert 0.0 <= forward <= 20038.0

    @settings(max_examples=150, deadline=None)
    @given(
        st.floats(min_value=-89, max_value=89), st.floats(min_value=-179, max_value=179)
    )
    def test_distance_to_itself_is_zero(self, lat, lon):
        assert haversine_km((lat, lon), (lat, lon)) == pytest.approx(0.0, abs=1e-9)

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=40))
    def test_a_name_is_always_a_valid_literal(self, name):
        literal = sparql_string(name)
        assert literal.startswith('"') and literal.endswith('"')
        assert "\n" not in literal and "\r" not in literal

    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.text(alphabet="ABCDE", min_size=1, max_size=3),
                st.floats(min_value=-80, max_value=80),
                st.floats(min_value=-170, max_value=170),
                st.integers(min_value=0, max_value=500),
            ),
            min_size=1,
            max_size=6,
        ),
        st.text(alphabet="ABCDE", min_size=1, max_size=3),
    )
    def test_scores_stay_in_range(self, rows, wanted):
        for index, (label, lat, lon, links) in enumerate(rows):
            candidate = PlaceCandidate(
                f"Q{index}", label, "", lat, lon, sitelinks=links
            )
            assert all(
                0.0 <= term <= 1.0 for term in score_candidate(candidate, wanted)
            )

    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.text(alphabet="ABCDE", min_size=1, max_size=3),
                st.floats(min_value=-80, max_value=80),
                st.floats(min_value=-170, max_value=170),
            ),
            min_size=1,
            max_size=6,
            unique_by=lambda row: row[0],
        )
    )
    def test_ranking_does_not_depend_on_input_order(self, rows):
        candidates = [
            PlaceCandidate(f"Q{i}", label, "", lat, lon)
            for i, (label, lat, lon) in enumerate(rows)
        ]
        forward = best_candidate(candidates, "A", near=ROUTE)
        backward = best_candidate(list(reversed(candidates)), "A", near=ROUTE)
        assert forward == backward

    @settings(max_examples=150, deadline=None)
    @given(st.text(max_size=30), st.one_of(st.none(), st.text(max_size=30)))
    def test_resolution_never_raises(self, name, modern):
        answer = resolve_place("k", name, [], modern_hint=modern)
        assert answer.why
        assert not answer.resolved

    @settings(max_examples=150, deadline=None)
    @given(
        st.floats(min_value=-80, max_value=80), st.floats(min_value=-170, max_value=170)
    )
    def test_nearest_is_never_further_than_any_anchor(self, lat, lon):
        anchors = ROUTE
        nearest = nearest_km((lat, lon), anchors)
        assert nearest is not None
        assert all(
            nearest <= haversine_km((lat, lon), anchor) + 1e-6 for anchor in anchors
        )


class TestTheClient:
    """The only part that touches the network — and never in a test."""

    @staticmethod
    def _transport(payload, status=200, calls=None):
        import httpx

        def handler(request):
            if calls is not None:
                calls.append(request)
            return httpx.Response(status, json=payload)

        return httpx.MockTransport(handler)

    def _client(self, tmp_path, payload, **kwargs):
        from verne80.gazetteer import GazetteerClient

        return GazetteerClient(
            cache=GazetteerCache(path=tmp_path / "cache.json"),
            transport=self._transport(payload),
            **kwargs,
        )

    def test_a_lookup_parses_what_the_endpoint_returned(self, tmp_path):
        payload = {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q1156"},
                        "enLabel": {"value": "Mumbai"},
                        "alias": {"value": "Bombay"},
                        "lat": {"value": "19.0761"},
                        "lon": {"value": "72.8775"},
                    }
                ]
            }
        }
        candidates = self._client(tmp_path, payload).lookup("Bombay")
        assert [c.qid for c in candidates] == ["Q1156"]

    def test_a_cached_name_never_reaches_the_network(self, tmp_path):
        import httpx

        calls = []
        from verne80.gazetteer import GazetteerClient

        cache = GazetteerCache(path=tmp_path / "cache.json")
        cache.put(GazetteerCache.key("wikidata", "Bombay"), "Bombay", [MUMBAI], "x")
        client = GazetteerClient(
            cache=cache, transport=httpx.MockTransport(lambda r: calls.append(r))
        )
        assert client.lookup("Bombay") == [MUMBAI]
        assert calls == []
        assert client.fetched == 0

    def test_a_cached_empty_answer_also_never_refetches(self, tmp_path):
        """An endpoint that had nothing is an answer; asking again would be rude."""
        from verne80.gazetteer import GazetteerClient

        cache = GazetteerCache(path=tmp_path / "cache.json")
        cache.put(GazetteerCache.key("wikidata", "Kholby"), "Kholby", [], "x")
        client = GazetteerClient(cache=cache, transport=self._transport({}))
        assert client.lookup("Kholby") == []
        assert client.fetched == 0

    def test_offline_names_the_key_it_is_missing(self, tmp_path):
        from verne80.gazetteer import GazetteerClient, OfflineError

        client = GazetteerClient(
            cache=GazetteerCache(path=tmp_path / "cache.json"), offline=True
        )
        with pytest.raises(OfflineError, match="wikidata:search:v1:kholby"):
            client.lookup("Kholby")

    def test_a_network_failure_is_no_candidates_not_a_crash(self, tmp_path):
        """A 400 is not worth retrying, so the failure path runs in no time."""
        client = self._client(tmp_path, {"error": "boom"}, offline=False)
        client.transport = self._transport({}, status=400)
        client.limiter.interval = 0.0
        assert client.lookup("Suez") == []

    def test_the_statuses_worth_retrying_are_the_ones_that_pass(self):
        """Rate limits and server faults. A 400 is our mistake, not theirs."""
        from verne80.gazetteer import _RETRY_STATUS

        assert 429 in _RETRY_STATUS and 503 in _RETRY_STATUS
        assert 400 not in _RETRY_STATUS and 404 not in _RETRY_STATUS

    def test_the_user_agent_names_a_contact(self):
        from verne80.gazetteer import USER_AGENT

        assert "crowintelligence.org" in USER_AGENT
        assert "verne80" in USER_AGENT

    def test_the_limiter_defaults_above_one_second(self):
        from verne80.gazetteer import RateLimiter

        assert RateLimiter().interval >= 1.0


class TestTheChecklist:
    """What earns a second opinion, and what a block must carry to be pasteable."""

    @staticmethod
    def _row(**cells):
        base = {
            "key": "ogden",
            "name_in_text": "Ogden",
            "used_as": "on_stage:5 visited:1",
            "first_chapter": "26",
            "confirmed": "",
            "lat": "41.23",
            "lon": "-111.96",
            "confidence": "0.95",
            "n_gazetteer_candidates": "1",
            "gazetteer_source": "wikidata",
            "modern_name": "Ogden",
            "qid": "Q52471",
            "name_changed": "",
            "country": "United States",
            "entity_type": "city",
        }
        return {**base, **cells}

    def test_a_confident_lone_candidate_does_not_need_checking(self):
        from verne80.checklist import reasons_to_check

        assert reasons_to_check(self._row(), [(41.2, -111.9)]) == []

    def test_low_confidence_earns_a_block(self):
        from verne80.checklist import reasons_to_check

        reasons = reasons_to_check(self._row(confidence="0.55"), [(41.2, -111.9)])
        assert reasons[0].startswith("low confidence")

    def test_a_contested_answer_earns_a_block_even_when_fairly_sure(self):
        from verne80.checklist import reasons_to_check

        row = self._row(confidence="0.80", n_gazetteer_candidates="5")
        assert "5 candidates" in reasons_to_check(row, [(41.2, -111.9)])[0]

    def test_a_renamed_place_always_earns_a_block(self):
        """A wrong rename is embarrassing; per spec 2.3 the rename is the content."""
        from verne80.checklist import reasons_to_check

        row = self._row(name_changed="y", modern_name="Prayagraj")
        assert any("renamed" in reason for reason in reasons_to_check(row, []))

    def test_a_place_far_from_the_route_that_the_party_visits_earns_a_block(self):
        from verne80.checklist import reasons_to_check

        reasons = reasons_to_check(self._row(), [(51.5, -0.1)])
        assert any("from the route" in reason for reason in reasons)

    def test_a_mentioned_place_far_from_the_route_does_not(self):
        """The book name-drops geography anywhere; only a visit implies proximity."""
        from verne80.checklist import reasons_to_check

        row = self._row(used_as="mentioned:2")
        assert not any(
            "from the route" in reason
            for reason in reasons_to_check(row, [(51.5, -0.1)])
        )

    def test_something_we_need_and_do_not_have_comes_first(self):
        from verne80.checklist import reasons_to_check

        row = self._row(lat="", lon="", confidence="")
        assert reasons_to_check(row, []) == [
            "nothing found, and the party is placed by it"
        ]

    def test_a_confirmed_row_is_never_flagged(self):
        from verne80.checklist import reasons_to_check

        assert reasons_to_check(self._row(confidence="0.1", confirmed="y"), []) == []

    def test_a_never_queried_row_is_not_flagged_as_missing(self):
        from verne80.checklist import reasons_to_check

        row = self._row(lat="", lon="", confidence="", gazetteer_source="")
        assert reasons_to_check(row, []) == []

    def test_a_block_carries_a_quote_from_the_chapter(self):
        """Without it, "the Indian town or the American one?" is unanswerable."""
        from verne80.checklist import Doubt, render_checklist

        doubt = Doubt(
            "ogden",
            "Ogden",
            ("low confidence (0.55)",),
            "the Central Pacific, between San Francisco and Ogden",
            26,
        )
        text = render_checklist([doubt], {"ogden": self._row()}, {})
        assert "between San Francisco and Ogden" in text
        assert "ch. 26" in text

    def test_every_runner_up_is_listed_with_its_qid(self):
        from verne80.checklist import Doubt, render_checklist

        others = [
            PlaceCandidate("Q541950", "Ogden", country="Canada"),
            PlaceCandidate("Q52471", "Ogden", country="United States"),
        ]
        text = render_checklist(
            [Doubt("ogden", "Ogden", ("5 candidates",))],
            {"ogden": self._row()},
            {"ogden": others},
        )
        runners = [line for line in text.splitlines() if line.startswith("- `Q")]
        assert runners == [
            "- `Q541950` — Ogden, Canada"
        ]  # the winner is not among them

    def test_the_question_asks_for_a_qid(self):
        from verne80.checklist import Doubt, render_checklist

        text = render_checklist(
            [Doubt("ogden", "Ogden", ("low confidence (0.55)",))],
            {"ogden": self._row()},
            {},
        )
        assert "which QID is?" in text

    def test_the_ones_that_position_the_party_come_first(self):
        from verne80.checklist import Doubt, rank_doubts

        aside = Doubt("bengal", "Bengal", ("low confidence (0.40)",), positional=False)
        matters = Doubt("ogden", "Ogden", ("5 candidates",), positional=True)
        assert [d.key for d in rank_doubts([aside, matters])] == ["ogden", "bengal"]

    def test_a_quote_comes_from_the_chapter_that_introduces_the_place(self):
        from verne80.checklist import collect_quotes
        from verne80.schema import ChapterExtraction

        def chapter(number, evidence):
            return ChapterExtraction(
                chapter=number,
                summary_hover="x",
                summary_detail="One. Two.",
                places_mentioned=[{"name_in_text": "Ogden", "evidence": evidence}],
            )

        quotes = collect_quotes([chapter(27, "later"), chapter(26, "first")])
        assert quotes["ogden"] == ("first", 26)
