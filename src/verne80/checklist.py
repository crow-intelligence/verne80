r"""The places worth a second opinion, written so a second opinion is cheap to get.

The gazetteer resolves three hundred-odd names and gets most of them right. The ones it
gets wrong are concentrated and predictable: Verne names two dozen Pacific Railroad
towns —
Ogden, Reno, Elko, Sacramento, Julesburg, Cisco — and every one has namesakes across a
dozen states and three continents. Route proximity separates most of them; it cannot
separate a Green River from a Green Creek forty kilometres away.

So this writes out the doubtful ones in blocks self-contained enough to paste into
another
model — or to read yourself on a train — without the repository to hand. **The part that
makes it work is the verbatim quote from the chapter.** "Is this the Indian town or the
American one?" is unanswerable from a name and a coordinate, and obvious from the
sentence
Verne wrote around it. That quote costs nothing: the extractions already carry one for
every place they name, for the evidence validator, and this is the same trick applied to
judgement instead of transcription.

Every block ends with the actual question, phrased so an answer is a QID rather than an
essay, because the correction that goes back into ``places.csv`` is a QID.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from verne80.gazetteer import PlaceCandidate, haversine_km, nearest_km

__all__ = ["Doubt", "reasons_to_check", "render_checklist"]

# Below this, the runner-up was close enough that "we picked one" is the honest summary.
LOW_CONFIDENCE = 0.7

# A confident-looking answer with more than one candidate still deserves a glance.
CONTESTED_CONFIDENCE = 0.85

# A place the party actually visits should not be a thousand kilometres off their route.
# A place merely mentioned may be anywhere, so this only applies to positional ones.
FAR_FROM_ROUTE_KM = 1000.0


@dataclass(frozen=True, slots=True)
class Doubt:
    """One place worth checking, and why.

    Attributes:
        key: The row key, which is what a correction is filed against.
        name: The 1872 spelling.
        reasons: Why it earned a block, most important first.
        quote: A verbatim sentence from the chapter that names it.
        chapter: Which chapter that quote came from.
    """

    key: str
    name: str
    reasons: tuple[str, ...]
    quote: str = ""
    chapter: int | None = None
    positional: bool = True
    """Whether the party is actually placed by this name.

    A place the book merely mentions can be wrong without moving anything, and the spec
    puts those in tier +3 — so they go below the fold rather than competing for
    attention
    with the ones that position somebody.
    """


def reasons_to_check(
    row: Mapping[str, str], anchors: Sequence[tuple[float, float]]
) -> list[str]:
    """Why this place needs a second opinion, or an empty list if it does not.

    Args:
        row: A review-table row, after the gazetteer has run.
        anchors: The route coordinates, for the distance test.

    Returns:
        Human-readable reasons, most important first.

    Contract:
        - Empty for a confident, uncontested, on-route resolution that renamed nothing.
        - A row a human has already confirmed never earns a reason.
        - Never raises, whatever is missing from the row.

    Examples:
        >>> confident = {"confidence": "0.95", "n_gazetteer_candidates": "1",
        ...              "lat": "19.07", "lon": "72.87", "used_as": "visited:2"}
        >>> reasons_to_check(confident, [(19.07, 72.87)])
        []
        >>> shaky = {**confident, "confidence": "0.55"}
        >>> reasons_to_check(shaky, [(19.07, 72.87)])
        ['low confidence (0.55)']
    """
    if row.get("confirmed", "").strip():
        return []

    reasons: list[str] = []
    used = row.get("used_as", "")
    positional = "on_stage" in used or "visited" in used
    queried = bool(row.get("gazetteer_source", "").strip())
    resolved = bool(row.get("lat", "").strip() and row.get("lon", "").strip())

    if queried and not resolved and positional:
        # We need this one to place somebody, and we do not have it.
        return ["nothing found, and the party is placed by it"]
    if not resolved:
        return []

    confidence = float(row["confidence"]) if row.get("confidence", "").strip() else 0.0
    candidates = int(row.get("n_gazetteer_candidates") or 0)

    if confidence < LOW_CONFIDENCE:
        reasons.append(f"low confidence ({confidence:.2f})")
    elif candidates > 1 and confidence < CONTESTED_CONFIDENCE:
        reasons.append(f"{candidates} candidates, {confidence:.2f} confidence")

    if positional and anchors:
        distance = nearest_km((float(row["lat"]), float(row["lon"])), anchors)
        if distance is not None and distance > FAR_FROM_ROUTE_KM:
            reasons.append(
                f"{distance:,.0f} km from the route, but the party goes there"
            )

    if row.get("name_changed", "").strip():
        # A wrong rename is both embarrassing and, per spec §2.3, the content itself.
        reasons.append(f"reported as renamed to {row.get('modern_name', '')}")

    return reasons


def _distance_note(
    row: Mapping[str, str], anchors: Sequence[tuple[float, float]]
) -> str:
    """How far the winner sits from the route, phrased for the block."""
    if not anchors or not row.get("lat", "").strip():
        return ""
    distance = nearest_km((float(row["lat"]), float(row["lon"])), anchors)
    return f" · {distance:,.0f} km from the route" if distance is not None else ""


def render_checklist(
    doubts: Sequence[Doubt],
    rows: Mapping[str, Mapping[str, str]],
    candidates: Mapping[str, Sequence[PlaceCandidate]],
    anchors: Sequence[tuple[float, float]] = (),
) -> str:
    """Write the doubtful places as blocks that stand on their own.

    Args:
        doubts: What to write, in the order to write it.
        rows: The review table, keyed.
        candidates: Every candidate the gazetteer saw, keyed the same way, so the
            runners-up can be listed. The correction somebody most often wants to make
            is
            "no, it is the other one", and the other one is already in the cache.
        anchors: The route, for the distance note.

    Returns:
        The markdown document.

    Contract:
        - One block per doubt, in the given order.
        - Every block names the place, its reasons and its question.
        - A block with runners-up lists each with its QID.
    """
    matter = sum(1 for doubt in doubts if doubt.positional)
    lines = [
        "# Places worth a second opinion",
        "",
        f"{len(doubts)} of the place names in *Around the World in Eighty Days* "
        "that the "
        "gazetteer is unsure about, or sure about in a way worth confirming. "
        f"**{matter} of them put somebody somewhere** and come first; the rest are "
        "places the book merely names, which can be wrong without moving anything.",
        "",
        "Each block stands on its own — paste one into a chat, or read it on a "
        "train. The "
        "quote is from the chapter that names the place, which is usually what settles "
        "whether it is the Indian town or the American one.",
        "",
        "An answer is a Wikidata QID. Put it in the `corrected_qid` column of "
        "`data/review/places.csv` against the `key` given, write `y` in `confirmed`, "
        "and "
        "re-run `uv run python scripts/07_gazetteer.py` — it costs nothing, the "
        "answers are cached.",
        "",
        "---",
        "",
    ]

    divided = False
    for doubt in doubts:
        if not doubt.positional and not divided:
            divided = True
            lines.extend(
                [
                    "## Below the fold: places the book only mentions",
                    "",
                    "These never place anybody, so a wrong answer here costs "
                    "nothing until the mentioned-versus-visited layer is built. "
                    "Worth a pass eventually, not worth one now.",
                    "",
                    "---",
                    "",
                ]
            )
        row = rows.get(doubt.key, {})
        lines.append(f"### {doubt.name}  — {'; '.join(doubt.reasons)}")
        lines.append("")
        lines.append(
            f"`key: {doubt.key}` · first used in chapter "
            f"{row.get('first_chapter', '?')} · {row.get('used_as', '')}"
        )
        if doubt.quote:
            lines.append("")
            lines.append(f"> {doubt.quote}  — ch. {doubt.chapter}")
        lines.append("")

        if row.get("lat", "").strip():
            detail = " · ".join(
                part
                for part in (row.get("country", ""), row.get("entity_type", ""))
                if part
            )
            lines.append(
                f"We picked **{row.get('qid', '?')} — {row.get('modern_name', '?')}**"
                + (f", {detail}" if detail else "")
                + f" · {float(row['lat']):.4f}, {float(row['lon']):.4f}"
                + _distance_note(row, anchors)
            )
        else:
            lines.append("We found **nothing with coordinates** under this name.")
        lines.append("")

        others = [
            candidate
            for candidate in candidates.get(doubt.key, ())
            if candidate.qid != row.get("qid")
        ]
        if others:
            lines.append("Runners-up:")
            lines.extend(
                f"- `{candidate.qid}` — {candidate.label}"
                + (f", {candidate.country}" if candidate.country else "")
                + (f" · {candidate.entity_type}" if candidate.entity_type else "")
                for candidate in others[:5]
            )
            lines.append("")

        lines.append(f"**Question:** {_question(doubt, row)}")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _question(doubt: Doubt, row: Mapping[str, str]) -> str:
    """The actual question, phrased so the answer is a QID."""
    name = doubt.name
    if not row.get("lat", "").strip():
        return (
            f"Verne's *{name}* has no obvious modern referent. Is there a real place "
            "behind it, and if so which QID? If it is the translator's "
            "invention, say so."
        )
    picked = row.get("qid", "?")
    return (
        f"Verne's *{name}* is on Phileas Fogg's route round the world in 1872. "
        f"Is {picked} the right entity? If not, which QID is?"
    )


def collect_quotes(extractions: Iterable) -> dict[str, tuple[str, int]]:
    """One verbatim quote per place key, from whichever chapter first names it.

    The extractions already carry an evidence quotation for every place they name — it
    is
    what the evidence validator greps — so the context this file needs costs nothing to
    obtain.

    Args:
        extractions: Parsed :class:`~verne80.schema.ChapterExtraction` objects.

    Returns:
        ``{place_key: (quote, chapter)}``.

    Contract:
        - The earliest chapter wins, so the quote is from where the place is introduced.
        - Never raises.
    """
    from verne80.normalize import place_key

    out: dict[str, tuple[str, int]] = {}

    def note(name: str | None, evidence: str, chapter: int) -> None:
        if not name or not evidence:
            return
        key = place_key(name)
        if key not in out or chapter < out[key][1]:
            out[key] = (evidence.strip(), chapter)

    for extraction in extractions:
        chapter = extraction.chapter
        for place in extraction.places_visited:
            note(place.name_in_text, place.evidence, chapter)
        for place in extraction.places_mentioned:
            note(place.name_in_text, place.evidence, chapter)
        for item in extraction.narrative.on_stage:
            for name in (item.at_name_in_text, item.between_from, item.between_to):
                note(name, item.evidence, chapter)
    return out


def rank_doubts(doubts: Sequence[Doubt]) -> list[Doubt]:
    """Order the blocks so the most useful checking happens first.

    Args:
        doubts: The doubts.

    Returns:
        The same doubts, most worth checking first: everything that positions the party
        before anything that does not, and within each, the things we need and do not
        have, then the outright uncertain, then the merely contested.

    Examples:
        >>> missing = Doubt("a", "A", ("nothing found, and the party is placed by it",))
        >>> shaky = Doubt("b", "B", ("low confidence (0.55)",))
        >>> aside = Doubt("c", "C", ("low confidence (0.40)",), positional=False)
        >>> [d.key for d in rank_doubts([aside, shaky, missing])]
        ['a', 'b', 'c']
    """

    def order(doubt: Doubt) -> tuple[int, int, str]:
        first = doubt.reasons[0] if doubt.reasons else ""
        if first.startswith("nothing found"):
            rank = 0
        elif first.startswith("low confidence"):
            rank = 1
        elif "km from the route" in first:
            rank = 2
        else:
            rank = 3
        return (0 if doubt.positional else 1, rank, doubt.name)

    return sorted(doubts, key=order)


def haversine_note(a: tuple[float, float], b: tuple[float, float]) -> str:
    """A distance, phrased for a block.

    Args:
        a: One point.
        b: The other.

    Returns:
        e.g. ``"380 km"``.

    Examples:
        >>> haversine_note((51.5, -0.13), (48.86, 2.35))
        '343 km'
    """
    return f"{haversine_km(a, b):,.0f} km"
