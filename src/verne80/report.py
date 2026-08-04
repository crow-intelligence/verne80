"""Turn validation verdicts into a review queue somebody will actually work through.

Two artefacts, for two readers. The Markdown queue is for the human doing the fixing:
one block per problem, with the quotation, the closest real text, its line number and a
diff, so the repair is a copy-paste rather than an investigation. The JSON report is for
the next run: it carries every verdict including the passes, and the full distribution
of similarity ratios, so :data:`~verne80.evidence.NEAR_MISS_RATIO` can be set from what
the data actually looks like instead of from a guess.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from verne80.evidence import MatchKind, QuoteCheck, failing, inline_diff, summarise

__all__ = [
    "KIND_ORDER",
    "ChapterCounts",
    "Report",
    "build_report",
    "count_blocking",
    "print_run_log",
    "render_markdown",
    "write_json_report",
    "write_markdown",
]

# Best to worst, and the column order in every table.
KIND_ORDER = (
    MatchKind.EXACT,
    MatchKind.NORMALISED,
    MatchKind.CASE_INSENSITIVE,
    MatchKind.ELLIPSIS,
    MatchKind.NEAR_MISS,
    MatchKind.MISSING,
)

# Below this similarity there is no real relationship between the quotation and the span
# the matcher settled on, and printing a character-level diff of two unrelated sentences
# is worse than printing nothing: it implies a near miss where there was an invention.
SHOW_CLOSEST_ABOVE = 0.5

_ADVICE = {
    MatchKind.CASE_INSENSITIVE: (
        "the text matches apart from capitalisation — copy the chapter's spelling"
    ),
    MatchKind.ELLIPSIS: (
        "the quotation elides text; replace it with one continuous passage if you can"
    ),
    MatchKind.NEAR_MISS: "replace the evidence string with the closest text",
    MatchKind.MISSING: (
        "no such passage in this chapter — quote real text, or delete the item"
    ),
}


@dataclass(frozen=True, slots=True)
class ChapterCounts:
    """One chapter's row in the summary table.

    Attributes:
        chapter: The chapter number.
        quotes: How many quotations were checked.
        counts: How many landed on each rung of the ladder.
    """

    chapter: int
    quotes: int
    counts: dict[MatchKind, int]


@dataclass(frozen=True, slots=True)
class Report:
    """Everything one validation run found.

    Attributes:
        checks: Every quotation verdict, passing or not.
        problems: Load, schema and editorial problems, as human-readable strings.
        generated_by: The stage that produced this.
    """

    checks: tuple[QuoteCheck, ...] = ()
    problems: tuple[str, ...] = ()
    generated_by: str = "scripts/03_validate.py"

    @property
    def chapters(self) -> tuple[int, ...]:
        """The chapters covered, in order.

        Returns:
            The chapter numbers.

        Examples:
            >>> from verne80.schema import EvidenceRef
            >>> ref = EvidenceRef(3, "time.evidence", "x")
            >>> Report((QuoteCheck(ref, MatchKind.EXACT, 1.0),)).chapters
            (3,)
        """
        return tuple(sorted({check.ref.chapter for check in self.checks}))

    @property
    def summary(self) -> dict[MatchKind, int]:
        """How many quotations landed on each rung, over the whole run.

        Returns:
            A count per kind, zeroes included, in :data:`KIND_ORDER`.
        """
        counts = summarise(self.checks)
        return {kind: counts.get(kind, 0) for kind in KIND_ORDER}

    @property
    def per_chapter(self) -> list[ChapterCounts]:
        """The same counts, broken down by chapter.

        Returns:
            One row per chapter covered, in chapter order.
        """
        rows: list[ChapterCounts] = []
        for number in self.chapters:
            mine = [check for check in self.checks if check.ref.chapter == number]
            counts = summarise(mine)
            rows.append(
                ChapterCounts(
                    chapter=number,
                    quotes=len(mine),
                    counts={kind: counts.get(kind, 0) for kind in KIND_ORDER},
                )
            )
        return rows

    @property
    def unresolved(self) -> list[QuoteCheck]:
        """The verdicts a human still needs to look at, worst first.

        Returns:
            Every verdict that did not match cleanly.
        """
        return failing(self.checks)

    def to_dict(self) -> dict[str, object]:
        """Render the machine-readable form.

        Every verdict is recorded, passing or not, along with the distribution of
        similarity ratios for the ones that failed — which is what makes
        :data:`~verne80.evidence.NEAR_MISS_RATIO` tunable from evidence rather than
        intuition.

        Returns:
            The report, ready to serialise.

        Contract:
            - The counts in ``summary`` sum to ``len(checks)``.
            - ``quotes`` has one entry per check.
        """
        return {
            "generated_by": self.generated_by,
            "chapters_checked": list(self.chapters),
            "total_quotes": len(self.checks),
            "summary": {kind.value: count for kind, count in self.summary.items()},
            "per_chapter": [
                {
                    "chapter": row.chapter,
                    "quotes": row.quotes,
                    **{kind.value: count for kind, count in row.counts.items()},
                }
                for row in self.per_chapter
            ],
            "problems": list(self.problems),
            "ratio_distribution": sorted(
                round(check.ratio, 3) for check in self.checks if not check.passed
            ),
            "quotes": [
                {
                    "chapter": check.ref.chapter,
                    "path": check.ref.path,
                    "kind": check.kind.value,
                    "ratio": round(check.ratio, 4),
                    "quote": check.ref.quote,
                    "best_span": check.best_span,
                    "line_no": check.line_no,
                }
                for check in self.checks
            ],
        }


def build_report(
    checks: Sequence[QuoteCheck],
    problems: Sequence[str],
    generated_by: str = "scripts/03_validate.py",
) -> Report:
    """Assemble a report from one run's verdicts.

    Args:
        checks: Every quotation verdict.
        problems: Load, schema and editorial problems.
        generated_by: The stage that produced this.

    Returns:
        The report.

    Examples:
        >>> from verne80.schema import EvidenceRef
        >>> ref = EvidenceRef(1, "time.evidence", "x")
        >>> report = build_report([QuoteCheck(ref, MatchKind.EXACT, 1.0)], [])
        >>> report.summary[MatchKind.EXACT]
        1
    """
    return Report(tuple(checks), tuple(problems), generated_by)


def write_json_report(report: Report, path: Path) -> None:
    """Write the machine-readable report.

    Args:
        report: The run's report.
        path: Where to write it. Parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    path.write_text(payload + "\n", encoding="utf-8")


def render_markdown(report: Report, chapters_dir: Path) -> str:
    """Render the human review queue.

    Args:
        report: The run's report.
        chapters_dir: Used to build ``path:line`` references.

    Returns:
        The Markdown document.

    Contract:
        - Every unresolved verdict appears in the output.
        - A clean run still produces a document, saying so.
    """
    lines = ["# Evidence review queue", ""]
    lines.append(
        f"{len(report.chapters)} chapters, {len(report.checks)} quotes checked."
    )
    lines.append("")
    lines.append(
        "| chapter | quotes | " + " | ".join(k.value for k in KIND_ORDER) + " |"
    )
    lines.append("|---:" * (len(KIND_ORDER) + 2) + "|")
    for row in report.per_chapter:
        cells = " | ".join(str(row.counts[kind]) for kind in KIND_ORDER)
        lines.append(f"| {row.chapter:02d} | {row.quotes} | {cells} |")
    lines.append("")

    if report.problems:
        lines.extend(["## Load and schema problems", ""])
        lines.extend(f"- {problem}" for problem in report.problems)
        lines.append("")

    unresolved = report.unresolved
    if not unresolved and not report.problems:
        lines.append(
            "Every evidence quotation was found in its chapter. Nothing to fix."
        )
        lines.append("")
        return "\n".join(lines)

    lines.extend(["## Quotations to fix", ""])
    for number in sorted({check.ref.chapter for check in unresolved}):
        mine = [check for check in unresolved if check.ref.chapter == number]
        lines.append(f"### chapter_{number:02d}.json — {len(mine)} to fix")
        lines.append("")
        for check in mine:
            lines.extend(_render_item(check, chapters_dir))
    return "\n".join(lines)


def _render_item(check: QuoteCheck, chapters_dir: Path) -> list[str]:
    """Render one problem block."""
    ratio = round(check.ratio, 4)
    lines = [f"#### `{check.ref.path}` — {check.kind.value} ({ratio})", ""]
    lines.append(f"- **quote:** `{check.ref.quote}`")
    if check.best_span and check.ratio >= SHOW_CLOSEST_ABOVE:
        where = chapters_dir / f"chapter_{check.ref.chapter:02d}.txt"
        lines.append(f"- **closest:** `{where}:{check.line_no}` — `{check.best_span}`")
        lines.append(f"- **diff:** `{inline_diff(check.ref.quote, check.best_span)}`")
    lines.append(f"- **fix:** {_ADVICE.get(check.kind, 'check this by hand')}.")
    lines.append("")
    return lines


def write_markdown(report: Report, path: Path, chapters_dir: Path) -> None:
    """Write the human review queue.

    Args:
        report: The run's report.
        path: Where to write it. Parent directories are created.
        chapters_dir: Used to build ``path:line`` references.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(report, chapters_dir) + "\n", encoding="utf-8")


def print_run_log(report: Report) -> None:
    """Print the per-chapter run log and the totals.

    Args:
        report: The run's report.
    """
    for row in report.per_chapter:
        parts = [
            f"{row.counts[kind]:2d} {kind.value}"
            for kind in KIND_ORDER
            if row.counts[kind]
        ]
        print(f"  ch {row.chapter:02d}   {row.quotes:3d} quotes   " + "   ".join(parts))

    if not report.checks:
        print("  no extractions loaded — nothing to check")
        return
    totals = ", ".join(
        f"{count} {kind.value}" for kind, count in report.summary.items() if count
    )
    print("  ---")
    print(f"  {len(report.chapters)} chapters, {len(report.checks)} quotes: {totals}")


def count_blocking(checks: Sequence[QuoteCheck], strict: bool) -> int:
    """How many verdicts should fail the run.

    By default only a genuinely absent quotation blocks. Warnings for typography and
    capitalisation still reach the queue, but they do not stop the pipeline — a report
    that fails on punctuation is a report people learn to ignore. ``--strict`` blocks on
    anything short of a clean pass, for when you want the hard guarantee.

    Args:
        checks: All verdicts.
        strict: Whether anything short of a clean pass should block.

    Returns:
        The number of blocking verdicts.

    Examples:
        >>> from verne80.schema import EvidenceRef
        >>> ref = EvidenceRef(1, "time.evidence", "x")
        >>> checks = [
        ...     QuoteCheck(ref, MatchKind.MISSING, 0.1),
        ...     QuoteCheck(ref, MatchKind.NEAR_MISS, 0.9),
        ... ]
        >>> count_blocking(checks, strict=False), count_blocking(checks, strict=True)
        (1, 2)
    """
    if strict:
        return len(failing(checks))
    return sum(1 for check in checks if check.kind is MatchKind.MISSING)
