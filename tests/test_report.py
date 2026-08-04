import json
from pathlib import Path

from verne80.evidence import MatchKind, QuoteCheck
from verne80.report import (
    build_report,
    count_blocking,
    render_markdown,
    write_json_report,
    write_markdown,
)
from verne80.schema import EvidenceRef

CHAPTERS = Path("data/chapters")


def check(
    kind,
    ratio=1.0,
    path="transport[0].evidence",
    quote="a quote",
    span=None,
    line=None,
):
    return QuoteCheck(EvidenceRef(3, path, quote), kind, ratio, span, line)


class TestCleanRuns:
    def test_a_clean_run_says_there_is_nothing_to_fix(self):
        report = build_report([check(MatchKind.EXACT)], [])
        assert "Nothing to fix" in render_markdown(report, CHAPTERS)

    def test_a_clean_run_blocks_nothing(self):
        assert count_blocking([check(MatchKind.EXACT)], strict=False) == 0
        assert count_blocking([check(MatchKind.NORMALISED)], strict=True) == 0

    def test_a_clean_run_has_no_unresolved_items(self):
        assert build_report([check(MatchKind.EXACT)], []).unresolved == []


class TestFailingRuns:
    def test_every_failing_ref_appears_in_the_markdown(self):
        checks = [
            check(MatchKind.MISSING, 0.3, "money.amounts[0].evidence", "invented"),
            check(
                MatchKind.NEAR_MISS, 0.9, "people[1].evidence", "nearly", "close", 12
            ),
        ]
        markdown = render_markdown(build_report(checks, []), CHAPTERS)
        assert "money.amounts[0].evidence" in markdown
        assert "people[1].evidence" in markdown

    def test_a_near_miss_carries_its_line_and_diff(self):
        checks = [
            check(
                MatchKind.NEAR_MISS,
                0.94,
                quote="They mounted the elephant",
                span="They mounted upon the elephant",
                line=112,
            )
        ]
        markdown = render_markdown(build_report(checks, []), CHAPTERS)
        assert "chapter_03.txt:112" in markdown
        assert "{+upon +}" in markdown

    def test_an_invented_quote_gets_no_misleading_diff(self):
        """Diffing two unrelated sentences implies a near miss where there was none."""
        checks = [
            check(MatchKind.MISSING, 0.36, quote="invented", span="unrelated", line=10)
        ]
        markdown = render_markdown(build_report(checks, []), CHAPTERS)
        assert "closest" not in markdown
        assert "quote real text, or delete the item" in markdown

    def test_load_problems_get_their_own_section(self):
        report = build_report([], ["chapter_04.json: invalid JSON"])
        markdown = render_markdown(report, CHAPTERS)
        assert "Load and schema problems" in markdown
        assert "chapter_04.json: invalid JSON" in markdown

    def test_unresolved_puts_the_worst_first(self):
        checks = [check(MatchKind.NEAR_MISS, 0.9), check(MatchKind.MISSING, 0.1)]
        kinds = [c.kind for c in build_report(checks, []).unresolved]
        assert kinds == [MatchKind.MISSING, MatchKind.NEAR_MISS]


class TestBlocking:
    def test_only_missing_blocks_by_default(self):
        checks = [check(MatchKind.MISSING, 0.1), check(MatchKind.NEAR_MISS, 0.9)]
        assert count_blocking(checks, strict=False) == 1

    def test_strict_blocks_on_anything_short_of_a_clean_match(self):
        checks = [
            check(MatchKind.MISSING, 0.1),
            check(MatchKind.NEAR_MISS, 0.9),
            check(MatchKind.CASE_INSENSITIVE),
            check(MatchKind.EXACT),
        ]
        assert count_blocking(checks, strict=True) == 3


class TestTheJsonReport:
    def test_it_is_json_serialisable(self, tmp_path):
        report = build_report(
            [check(MatchKind.EXACT), check(MatchKind.MISSING, 0.2)], ["x"]
        )
        path = tmp_path / "report.json"
        write_json_report(report, path)
        assert json.loads(path.read_text(encoding="utf-8"))["total_quotes"] == 2

    def test_every_verdict_is_recorded_passing_or_not(self):
        report = build_report(
            [check(MatchKind.EXACT), check(MatchKind.MISSING, 0.2)], []
        ).to_dict()
        assert len(report["quotes"]) == 2
        assert sum(report["summary"].values()) == 2

    def test_the_ratio_distribution_covers_the_failures(self):
        report = build_report(
            [check(MatchKind.EXACT), check(MatchKind.NEAR_MISS, 0.912)], []
        )
        assert report.to_dict()["ratio_distribution"] == [0.912]

    def test_the_per_chapter_rows_add_up(self):
        report = build_report(
            [check(MatchKind.EXACT), check(MatchKind.MISSING, 0.2)], []
        )
        assert [row.quotes for row in report.per_chapter] == [2]
        assert report.chapters == (3,)

    def test_writing_the_markdown_creates_the_directory(self, tmp_path):
        report = build_report([check(MatchKind.EXACT)], [])
        path = tmp_path / "review" / "queue.md"
        write_markdown(report, path, CHAPTERS)
        assert path.exists()
