"""The per-chapter extraction schema, and the editorial checks that sit outside it.

Two jobs, kept apart on purpose. Pydantic validates *shape*: a field is a string or it
is not, an enum member or it is not. :func:`check_extraction` reports *policy*: a hover
summary that ran to forty words is well-shaped and still wrong. The same split as the
rest of the pipeline — structure enforced by code, judgement returned as a list of
problems for a human to read.

Two schema decisions are worth stating plainly, because both are about not putting a
thumb on the model's scale:

**Money is null by default.** Verne mentions sums irregularly, and most chapters state
no amount at all. An empty ``amounts`` array and a null ``fogg_remaining_stated`` are
the correct and expected answer for most chapters, so neither field is required and both
default to empty. A model asked thirty-seven times "how much is left?" will produce
thirty-seven plausible numbers; the schema is built so it is never asked.

**Coercion is recorded, never silent.** Transport modes get a small synonym table,
because "train" for "railway" is a spelling difference and not a claim. Place roles do
not: there are only four values, and a wrong one silently corrupts the route. Every
coercion that does happen is appended to the problems list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from verne80.normalize import match_key

__all__ = [
    "ChapterExtraction",
    "Narrative",
    "NamedElsewhere",
    "OnStage",
    "DateMention",
    "EvidenceRef",
    "MoneyAmount",
    "MoneyInfo",
    "Person",
    "PlaceMentioned",
    "PlaceRole",
    "PlaceVisited",
    "ScheduleStatus",
    "TimeInfo",
    "TransportLeg",
    "TransportMode",
    "check_extraction",
    "is_stale",
    "normalise_mode",
]

MAX_HOVER_WORDS = 25
DETAIL_SENTENCE_RANGE = (2, 6)


class PlaceRole(StrEnum):
    """What the travellers were doing at a place."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    PASSING_THROUGH = "passing_through"
    SETTING = "setting"


class TransportMode(StrEnum):
    """How a leg was travelled."""

    STEAMER = "steamer"
    RAILWAY = "railway"
    ELEPHANT = "elephant"
    SLEDGE = "sledge"
    CARRIAGE = "carriage"
    ON_FOOT = "on_foot"
    OTHER = "other"


class ScheduleStatus(StrEnum):
    """Whether Fogg is ahead of his itinerary, behind it, or the text is silent."""

    AHEAD = "ahead"
    BEHIND = "behind"
    ON_TIME = "on_time"
    UNKNOWN = "unknown"


# Spelling variants only. Each maps a word for the same thing onto the schema's term;
# none of them changes what the text claims.
_MODE_SYNONYMS = {
    "train": TransportMode.RAILWAY,
    "rail": TransportMode.RAILWAY,
    "train_railway": TransportMode.RAILWAY,
    "ship": TransportMode.STEAMER,
    "boat": TransportMode.STEAMER,
    "steamship": TransportMode.STEAMER,
    "steamboat": TransportMode.STEAMER,
    "schooner": TransportMode.STEAMER,
    "walking": TransportMode.ON_FOOT,
    "walked": TransportMode.ON_FOOT,
    "foot": TransportMode.ON_FOOT,
    "horse": TransportMode.CARRIAGE,
    "cart": TransportMode.CARRIAGE,
    "wagon": TransportMode.CARRIAGE,
    "palanquin": TransportMode.CARRIAGE,
    "sled": TransportMode.SLEDGE,
    "sleigh": TransportMode.SLEDGE,
    "wind_sled": TransportMode.SLEDGE,
    "wind_sledge": TransportMode.SLEDGE,
}

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


class _Base(BaseModel):
    """Shared configuration for every extraction model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        frozen=True,
    )


class Evidenced(_Base):
    """Anything the model extracted, carrying its verbatim quotation.

    Attributes:
        evidence: A quotation from the chapter that the extraction rests on. Validated
            against the chapter text by :mod:`verne80.evidence`.
    """

    evidence: str = Field(min_length=1)


class PlaceVisited(Evidenced):
    """A place the travellers are in or pass through."""

    name_in_text: str = Field(min_length=1)
    role: PlaceRole


class PlaceMentioned(Evidenced):
    """A place merely named."""

    name_in_text: str = Field(min_length=1)


class Person(Evidenced):
    """A person named in the chapter."""

    name_in_text: str = Field(min_length=1)
    role: str | None = None


class OnStage(Evidenced):
    """One person, and where this chapter puts them.

    A person who moves during a chapter gets one entry per place, in narrative order,
    so the last entry is where they are when the chapter ends. That is why this is its
    own array rather than fields on :class:`Person`: chapter 4 puts Fogg in four places,
    and one row per person cannot hold that.

    ``at_name_in_text`` and the ``between_`` pair are alternatives, not a pair. A model
    that fills both is well-shaped and confused, which is why
    :func:`check_extraction` reports it rather than a validator raising on it.
    """

    name_in_text: str = Field(min_length=1)
    at_name_in_text: str | None = None
    between_from: str | None = None
    between_to: str | None = None

    @field_validator("at_name_in_text", "between_from", "between_to", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Treat a blank place name as "not stated", which is what it means.

        The other optional strings here tolerate ``""`` because a blank purpose or role
        is merely useless. A blank place name is worse than useless: it would key a
        phantom row into the containment map that resolves positions.
        """
        return None if isinstance(value, str) and not value.strip() else value


class NamedElsewhere(Evidenced):
    """A person the chapter talks about who is not in its scene."""

    name_in_text: str = Field(min_length=1)


class Narrative(_Base):
    """Who is physically on stage in this chapter, and where the text puts them.

    This block exists because ``places_visited`` cannot say where the travellers are.
    Chapter 5 lists London, the Reform Club and Scotland Yard as settings while Fogg is
    already on a train to Paris; chapter 6 is set at Suez, where Fix is waiting and the
    party has not yet arrived. The chapter's setting and the party's position come apart
    in both directions, so the position has to be resolved from who was actually there.

    An empty ``on_stage`` is the correct answer for a chapter the travellers never
    appear in — and the silence is the signal, which is why nothing here asks "where is
    Fogg". Chapter 5 does not say, and asking would invite exactly the invention the
    prompt's first rule forbids.
    """

    on_stage: list[OnStage] = Field(default_factory=list)
    named_but_not_present: list[NamedElsewhere] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _absorb_nulls(cls, data: Any) -> Any:
        return _absorb(data, lists=("on_stage", "named_but_not_present"))


class TransportLeg(Evidenced):
    """One leg of the journey, and how it was travelled.

    ``from`` is a Python keyword, so the field is ``from_`` with an alias. Dumping by
    alias round-trips; dumping without it does not, which is what the round-trip
    property test in ``tests/test_schema.py`` exists to catch.
    """

    mode: TransportMode
    vessel_or_line_name: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    @field_validator("mode", mode="before")
    @classmethod
    def _coerce_mode(cls, value: Any) -> Any:
        """Fold spelling variants onto the schema's terms; unknowns become ``other``."""
        return normalise_mode(value)


class DateMention(Evidenced):
    """A date phrase, as written."""

    as_written: str = Field(min_length=1)


class TimeInfo(_Base):
    """What the chapter says about the calendar and the schedule."""

    dates_mentioned: list[DateMention] = Field(default_factory=list)
    days_elapsed_or_remaining: str | None = None
    schedule_status: ScheduleStatus = ScheduleStatus.UNKNOWN
    schedule_detail: str | None = None
    evidence: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _absorb_nulls(cls, data: Any) -> Any:
        return _absorb(data, lists=("dates_mentioned",))

    @field_validator("schedule_status", mode="before")
    @classmethod
    def _default_status(cls, value: Any) -> Any:
        return ScheduleStatus.UNKNOWN if value is None else value


class MoneyAmount(Evidenced):
    """One sum, as written, and what it was for."""

    amount_as_written: str = Field(min_length=1)
    purpose: str | None = None


class MoneyInfo(_Base):
    """What the chapter says about money — usually nothing, which is correct."""

    amounts: list[MoneyAmount] = Field(default_factory=list)
    fogg_remaining_stated: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _absorb_nulls(cls, data: Any) -> Any:
        return _absorb(data, lists=("amounts",))


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One evidence quotation, and where in the extraction it came from.

    Attributes:
        chapter: The chapter number the quotation should be found in.
        path: An accessor into the extraction, e.g. ``places_visited[2].evidence``. This
            is what the review queue prints, so a human can go straight to the field.
        quote: The quotation itself, exactly as the model wrote it.
    """

    chapter: int
    path: str
    quote: str


class ChapterExtraction(_Base):
    """Everything extracted from one chapter."""

    chapter: int = Field(ge=1, le=37)
    title: str | None = None
    summary_hover: str = Field(min_length=1)
    summary_detail: str = Field(min_length=1)
    places_visited: list[PlaceVisited] = Field(default_factory=list)
    places_mentioned: list[PlaceMentioned] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    narrative: Narrative = Field(default_factory=Narrative)
    transport: list[TransportLeg] = Field(default_factory=list)
    time: TimeInfo = Field(default_factory=TimeInfo)
    money: MoneyInfo = Field(default_factory=MoneyInfo)
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _absorb_nulls(cls, data: Any) -> Any:
        """Turn ``null`` into the empty form for every container field.

        The prompt tells the model to use null when a field is not stated, and for lists
        and sub-objects it obliges. Rejecting that would fail validation on the roughly
        thirty chapters that mention no money at all.
        """
        data = _absorb(
            data,
            lists=("places_visited", "places_mentioned", "people", "transport"),
        )
        if isinstance(data, dict):
            for key in ("narrative", "time", "money"):
                if data.get(key) is None:
                    data[key] = {}
        return data

    def evidence_items(self) -> list[EvidenceRef]:
        """Every evidence quotation in this extraction, with its address.

        Returns:
            One reference per non-empty evidence string, in declaration order and then
            list order.

        Contract:
            - The count equals the number of non-empty evidence strings in the model.
            - Every ``path`` is a valid accessor into ``model_dump(by_alias=True)``.
            - Stable: the same extraction always yields the same order.

        Examples:
            >>> data = {
            ...     "chapter": 1,
            ...     "summary_hover": "Fogg wagers.",
            ...     "summary_detail": "Fogg wagers. He leaves.",
            ...     "places_visited": [
            ...         {"name_in_text": "London", "role": "setting",
            ...          "evidence": "in London"}
            ...     ],
            ... }
            >>> [ref.path for ref in ChapterExtraction(**data).evidence_items()]
            ['places_visited[0].evidence']
        """
        refs: list[EvidenceRef] = []
        listed = (
            ("places_visited", self.places_visited),
            ("places_mentioned", self.places_mentioned),
            ("people", self.people),
            ("narrative.on_stage", self.narrative.on_stage),
            ("narrative.named_but_not_present", self.narrative.named_but_not_present),
            ("transport", self.transport),
            ("time.dates_mentioned", self.time.dates_mentioned),
            ("money.amounts", self.money.amounts),
        )
        for name, items in listed:
            for position, item in enumerate(items):
                if item.evidence.strip():
                    refs.append(
                        EvidenceRef(
                            self.chapter, f"{name}[{position}].evidence", item.evidence
                        )
                    )
        if self.time.evidence and self.time.evidence.strip():
            refs.append(EvidenceRef(self.chapter, "time.evidence", self.time.evidence))
        return refs


def _absorb(data: Any, lists: tuple[str, ...]) -> Any:
    """Replace ``null`` with ``[]`` for the named list fields."""
    if not isinstance(data, dict):
        return data
    for key in lists:
        if data.get(key) is None and key in data:
            data[key] = []
    return data


def normalise_mode(value: Any) -> Any:
    """Fold a transport mode onto a schema term, or ``other`` if it is unrecognised.

    Public because :mod:`verne80.route` needs it to read "rail and steamboats" out of
    the itinerary table in chapter 3. A second copy of the synonym table is how you end
    up with two that disagree.

    Args:
        value: Whatever the model wrote, or anything else.

    Returns:
        The schema term, or the input unchanged when it is not a string.

    Examples:
        >>> normalise_mode("train")
        <TransportMode.RAILWAY: 'railway'>
        >>> normalise_mode("wind-sled")
        <TransportMode.SLEDGE: 'sledge'>
        >>> normalise_mode("balloon")
        <TransportMode.OTHER: 'other'>
    """
    if not isinstance(value, str):
        return value
    key = re.sub(r"[\s\-/]+", "_", value.strip().lower())
    if key in TransportMode.__members__.values() or key in {
        m.value for m in TransportMode
    }:
        return key
    if key in _MODE_SYNONYMS:
        return _MODE_SYNONYMS[key]
    return TransportMode.OTHER


def check_extraction(
    extraction: ChapterExtraction,
    expected_number: int,
    expected_title: str | None = None,
) -> list[str]:
    """Report everything questionable about an extraction that still validated.

    Args:
        extraction: The parsed extraction.
        expected_number: The chapter number implied by the filename.
        expected_title: The title from ``index.json``, if it should be cross-checked.

    Returns:
        Human-readable problems, empty when nothing looks off.

    Contract:
        - Never raises.
        - Reports, but does not modify, the extraction.

    Examples:
        >>> data = {
        ...     "chapter": 2,
        ...     "summary_hover": "Fogg wagers.",
        ...     "summary_detail": "Fogg wagers. He leaves at once.",
        ... }
        >>> check_extraction(ChapterExtraction(**data), expected_number=3)
        ['chapter field says 2 but the file is chapter 03']
    """
    problems: list[str] = []
    label = f"chapter {expected_number:02d}"

    if extraction.chapter != expected_number:
        problems.append(
            f"chapter field says {extraction.chapter} but the file is {label}"
        )

    hover_words = len(extraction.summary_hover.split())
    if hover_words > MAX_HOVER_WORDS:
        problems.append(
            f"{label} summary_hover is {hover_words} words (max {MAX_HOVER_WORDS})"
        )

    sentences = len(_SENTENCE_END.findall(extraction.summary_detail.strip()))
    low, high = DETAIL_SENTENCE_RANGE
    if not low <= sentences <= high:
        problems.append(
            f"{label} summary_detail has {sentences} sentences (expected {low}-{high})"
        )

    visited = [place.name_in_text for place in extraction.places_visited]
    duplicates = sorted({name for name in visited if visited.count(name) > 1})
    if duplicates:
        problems.append(
            f"{label} lists a place twice under places_visited: {duplicates}"
        )

    visited_keys = {match_key(name) for name in visited}
    both = sorted(
        place.name_in_text
        for place in extraction.places_mentioned
        if match_key(place.name_in_text) in visited_keys
    )
    if both:
        problems.append(f"{label} lists a place as both visited and mentioned: {both}")

    if extraction.money.fogg_remaining_stated and not extraction.money.amounts:
        problems.append(
            f"{label} states a remaining sum but lists no amounts — "
            "check this against the chapter; invented figures look exactly like this"
        )

    if (
        expected_title
        and extraction.title
        and match_key(extraction.title) != match_key(expected_title)
    ):
        problems.append(
            f"{label} title does not match index.json: "
            f"{extraction.title[:50]!r} vs {expected_title[:50]!r}"
        )

    problems.extend(_check_narrative(extraction, label))
    return problems


def _check_narrative(extraction: ChapterExtraction, label: str) -> list[str]:
    """Report what looks wrong about the narrative block.

    Deliberately silent about three things that look like errors and are not: the same
    person appearing twice in ``on_stage`` (that is movement within a chapter), an entry
    with every place field null (that is the "do not work it out" rule being obeyed),
    and an empty ``on_stage`` beside a non-empty ``places_visited`` (that is chapter 5
    being right about Fogg having left).
    """
    problems: list[str] = []
    narrative = extraction.narrative

    on_stage_keys = {match_key(item.name_in_text) for item in narrative.on_stage}
    both = sorted(
        item.name_in_text
        for item in narrative.named_but_not_present
        if match_key(item.name_in_text) in on_stage_keys
    )
    if both:
        problems.append(f"{label} says {both} are both on stage and not present")

    for position, item in enumerate(narrative.on_stage):
        where = f"{label} narrative.on_stage[{position}]"
        if item.at_name_in_text and (item.between_from or item.between_to):
            problems.append(
                f"{where} gives both a place and a transit — they are alternatives"
            )
        if (
            item.between_from
            and item.between_to
            and match_key(item.between_from) == match_key(item.between_to)
        ):
            problems.append(f"{where} travels from {item.between_from!r} to itself")

    people_keys = {match_key(person.name_in_text) for person in extraction.people}
    if people_keys:
        strangers = sorted(
            {
                item.name_in_text
                for item in (*narrative.on_stage, *narrative.named_but_not_present)
                if match_key(item.name_in_text) not in people_keys
            }
        )
        if strangers:
            problems.append(
                f"{label} names {strangers} in narrative but not in people — "
                "the two rosters for the same chapter disagree"
            )

    # The strongest cross-check here: it catches a location invented in the new block
    # that the model did not enumerate in the two it has been filling all along.
    known_places = {
        match_key(place.name_in_text)
        for place in (*extraction.places_visited, *extraction.places_mentioned)
    }
    if known_places:
        invented = sorted(
            {
                name
                for item in narrative.on_stage
                for name in (item.at_name_in_text, item.between_from, item.between_to)
                if name and match_key(name) not in known_places
            }
        )
        if invented:
            problems.append(
                f"{label} places someone at {invented}, which appears in neither "
                "places_visited nor places_mentioned"
            )

    if (
        extraction.people
        and not narrative.on_stage
        and not narrative.named_but_not_present
    ):
        problems.append(
            f"{label} has no narrative block — re-paste it under the current prompt "
            "(see data/prompts/README.md)"
        )

    return problems


def is_stale(extraction: ChapterExtraction) -> bool:
    """Whether an extraction predates the prompt's narrative block.

    Sound as a discriminator: if anyone is named in the chapter at all, then each of
    them is either in its scene or not, so both narrative arrays being empty means the
    question was never asked.

    Args:
        extraction: The parsed extraction.

    Returns:
        True when the file needs re-pasting.

    Examples:
        >>> old = ChapterExtraction(
        ...     chapter=1,
        ...     summary_hover="Fogg wagers.",
        ...     summary_detail="Fogg wagers. He leaves.",
        ...     people=[{"name_in_text": "Fogg", "evidence": "Mr. Fogg"}],
        ... )
        >>> is_stale(old)
        True
    """
    narrative = extraction.narrative
    return bool(
        extraction.people
        and not narrative.on_stage
        and not narrative.named_but_not_present
    )
