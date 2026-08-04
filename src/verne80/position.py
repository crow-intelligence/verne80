r"""Where each of the three tracked characters is, chapter by chapter.

``places_visited`` cannot answer this, and the five real chapters show why in both
directions. Chapter 5 lists London, the Reform Club and Scotland Yard as its settings
while Fogg is already on a train to Paris — the camera is *behind* the party. Chapter
6 is set at Suez, where Fix is waiting and the party has not arrived — the camera is
*ahead*. A rule that only allowed forward movement would catch the first and miss the
second.

So position comes from ``narrative.on_stage``: who is physically in the scene, and
where the chapter puts them. Everything else follows from three ideas.

**A position is a point on a leg, not a node.** :class:`RoutePoint` is ``(leg,
along)``. Node *k* is ``RoutePoint(k, 0.0)`` and the closing London is ``RoutePoint(7,
1.0)``. That is the entire cycle handling: the two Londons are different points that
happen to share a name, and ordering is plain tuple comparison. It also means
waypoints the chapter-3 table never names — Paris, Aden, Allahabad, Singapore, Omaha —
sit *on* a leg rather than in the node sequence, so that table's
eight-legs-eighty-days oracle stays true however many of them turn up.

**Carrying forward is recorded, not implied.** Every chapter yields a row for every
track, and a row whose position was inherited says so, along with the chapter that
last stated it. Chapter 5's Fogg row reads ``carried, stated_at_chapter=4``. That is
what lets the dashboard dim the pin, or write "last seen, ch. 4", instead of quietly
asserting a position nobody wrote down.

**Monotonicity is a check, never a mechanism.** Nothing here pushes a position
forwards. :func:`check_positions` reports a backwards step afterwards, and only as a
warning, because Verne really does double back — the rescue party in chapter 30, the
Atlantic diversion in 32–33, the arrest at Liverpool in 34. A resolver that
"corrected" those would be lying about the book.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from verne80.normalize import match_key, place_key
from verne80.route import RouteSpine
from verne80.schema import ChapterExtraction, PlaceRole

__all__ = [
    "Containment",
    "PlaceKind",
    "PositionSource",
    "RoutePoint",
    "TemporalClass",
    "TrackPosition",
    "check_positions",
    "classify_mentions",
    "load_tracks",
    "resolve_positions",
]

TRACKS_JSON = Path(__file__).with_name("tracks.json")

# Where a transit lands when only the origin is known: just past it, far enough to order
# after the origin and nowhere near claiming an arrival.
_JUST_UNDER_WAY = 0.1


class PositionSource(StrEnum):
    """How a row's position was arrived at."""

    STATED = "stated"
    """The chapter put this track at this place."""

    INFERRED = "inferred"
    """The track was on stage with no place given; taken from ``places_visited``."""

    CARRIED = "carried"
    """The track was not on stage; the previous position was carried forward."""

    UNKNOWN = "unknown"
    """The track has not appeared yet. Not the same as being at the start."""


class PlaceKind(StrEnum):
    """What a place name refers to, once a human has confirmed it."""

    NODE = "node"
    """A stop the chapter-3 itinerary names."""

    MICRO = "micro"
    """Somewhere inside a stop — the Reform Club, Saville Row. Rolls up to a parent."""

    WAYPOINT = "waypoint"
    """Somewhere on a leg that the itinerary does not name — Paris, Aden, Omaha."""

    OFF_ROUTE = "off_route"
    """A region or institution, not a position — India, the Bank of England."""

    UNKNOWN = "unknown"
    """Not yet classified. Proposed rows start here."""


class TemporalClass(StrEnum):
    """Where a mentioned place sits relative to the party."""

    PAST = "past"
    HERE = "here"
    FUTURE = "future"
    CYCLIC = "cyclic"
    """Both behind and ahead — London, which the route visits twice."""

    OFF_ROUTE = "off_route"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True, slots=True)
class RoutePoint:
    """A position on the route: which leg, and how far along it.

    ``along`` exists to **order pins along a line**. It is not a distance, not a speed,
    and not a fraction of the journey completed. The timeline's real progress figure
    will come from the dates in a later schedule module, and the two must never be
    confused — do not let this number reach the dashboard as a percentage of anything.

    Attributes:
        leg: Which leg of the itinerary, ``0..7``.
        along: ``0.0`` at that leg's origin, ``1.0`` at its destination.
    """

    leg: int
    along: float

    # Canonical form: a point that lands exactly on a node is written ``(k, 0.0)``, the
    # start of the next leg, rather than ``(k-1, 1.0)``, the end of the previous one.
    # They are the same place, and leaving both spellings in play would make two equal
    # positions compare unequal. The single exception is the closing node, which has no
    # next leg — and that exception is precisely what keeps the two Londons apart.

    @classmethod
    def at_node(cls, index: int, last_leg: int) -> RoutePoint:
        """The point corresponding to a node index.

        The closing node has no leg of its own, so it is the far end of the last one.
        That is the whole reason the two Londons never collide.

        Args:
            index: A node index.
            last_leg: The index of the final leg, normally ``7``.

        Returns:
            The point.

        Examples:
            >>> RoutePoint.at_node(0, 7)
            RoutePoint(leg=0, along=0.0)
            >>> RoutePoint.at_node(8, 7)
            RoutePoint(leg=7, along=1.0)
        """
        if index > last_leg:
            return cls(last_leg, 1.0)
        return cls(index, 0.0)

    def midpoint(self, other: RoutePoint) -> RoutePoint:
        """Halfway between this point and another, for a leg in transit.

        A transit never states an exact position — it states an interval — so the point
        taken from it is the interval's middle, and the fact that it is a guess is
        carried in the row's source rather than hidden in the number.

        Args:
            other: The far end of the interval.

        Returns:
            A point between the two, ordered no earlier than the smaller of them.

        Examples:
            >>> RoutePoint(0, 0.0).midpoint(RoutePoint(0, 1.0))
            RoutePoint(leg=0, along=0.5)
            >>> RoutePoint(0, 0.0).midpoint(RoutePoint(2, 0.0))
            RoutePoint(leg=1, along=0.0)
        """
        low, high = sorted((self, other))
        span = (high.leg - low.leg) + (high.along - low.along)
        target = low.along + span / 2
        leg = low.leg
        # `>=` not `>`: landing exactly on a boundary takes the canonical spelling, the
        # start of the next leg, so two ways of naming one place cannot compare unequal.
        while target >= 1.0 and leg < high.leg:
            target -= 1.0
            leg += 1
        return RoutePoint(leg, round(min(target, 1.0), 6))


@dataclass(frozen=True, slots=True)
class Containment:
    """How one place name resolves onto the route.

    Attributes:
        key: The place name under :func:`~verne80.normalize.match_key`.
        name_in_text: A printed spelling, for run logs and review rows.
        kind: What it turned out to be.
        node_indices: Node positions it names, empty unless ``kind`` is ``node``.
            London carries two, which is why this is a tuple.
        parent_key: For a micro-location, the key it rolls up to. A micro-location
            points at its parent rather than at a node index so that the Reform Club
            inherits London's *two* indices instead of being frozen to the first.
        leg: For a waypoint, which leg it sits on.
        along: For a waypoint, where along that leg.
        why: One line saying how this was arrived at, homer-style.
        confirmed: Whether a human has signed it off.
    """

    key: str
    name_in_text: str
    kind: PlaceKind = PlaceKind.UNKNOWN
    node_indices: tuple[int, ...] = ()
    parent_key: str | None = None
    leg: int | None = None
    along: float | None = None
    why: str = ""
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class TrackPosition:
    """Where one track is in one chapter, and how we know.

    Attributes:
        chapter: The chapter number.
        track: The track key, e.g. ``"fogg"``.
        point: The resolved position, or ``None`` when the track has not appeared.
        source: How the position was arrived at.
        place_name_in_text: What this chapter called the place, if it stated one.
        stated_at_chapter: The chapter that last stated a position for this track.
        evidence: The verbatim quotation that set it, so confirming a row is a read
            rather than a lookup.
        flags: Anything a human should glance at.
    """

    chapter: int
    track: str
    point: RoutePoint | None = None
    source: PositionSource = PositionSource.UNKNOWN
    place_name_in_text: str | None = None
    stated_at_chapter: int | None = None
    evidence: str | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChapterPositions:
    """One chapter's rows, plus the scene the chapter itself plays out in.

    Attributes:
        chapter: The chapter number.
        tracks: One row per track, in roster order.
        scene_places: Every place named by an ``on_stage`` entry, tracked or not.
            Chapter 5's is ``("office",)`` — the police office where the commissioner
            reads Fix's telegram, which is where the *chapter* is even though it is not
            where the *party* is. Stored so the side panel can say "meanwhile, at
            Scotland Yard" without the map pin moving.
    """

    chapter: int
    tracks: tuple[TrackPosition, ...]
    scene_places: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Track:
    """One trackable character.

    Attributes:
        key: The stable identifier, e.g. ``"fogg"``.
        display: How to label it.
        aliases: Every spelling the text uses.
        why: Why this character earns a series of its own.
    """

    key: str
    display: str
    aliases: tuple[str, ...] = ()
    why: str = ""

    def matches(self, name: str) -> bool:
        """Whether a printed name refers to this track.

        Args:
            name: A name as printed in the chapter.

        Returns:
            True when it is one of this track's aliases.

        Examples:
            >>> fogg = Track("fogg", "Phileas Fogg", ("Phileas Fogg", "Mr. Fogg"))
            >>> fogg.matches("mr. fogg"), fogg.matches("Passepartout")
            (True, False)
        """
        wanted = match_key(name)
        return any(match_key(alias) == wanted for alias in self.aliases)


def load_tracks(path: Path = TRACKS_JSON) -> tuple[Track, ...]:
    """Read the track roster.

    Args:
        path: The roster file.

    Returns:
        The tracks, in the order the file lists them.

    Raises:
        FileNotFoundError: If the roster is missing.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Track(
            key=entry["track"],
            display=entry["display"],
            aliases=tuple(entry["aliases"]),
            why=entry.get("why", ""),
        )
        for entry in data["tracks"]
    )


def resolve_point(
    name: str,
    containment: Mapping[str, Containment],
    spine: RouteSpine,
    carried: RoutePoint | None,
) -> tuple[RoutePoint | None, tuple[str, ...]]:
    """Turn a place name into a point on the route.

    Where a name refers to more than one node — London, at both ends — the carried
    position picks between them. **It disambiguates a name; it never supplies one.** A
    place that is not on the route at all resolves to ``None`` whatever has been
    carried.

    Args:
        name: The place as the chapter printed it.
        containment: The confirmed place map.
        spine: The route.
        carried: Where this track was last known to be, if anywhere.

    Returns:
        The point, and any flags raised on the way.

    Contract:
        - Returns ``None`` for an unknown or off-route place, never a guess.
        - With several candidates, returns the earliest at or after ``carried``; if none
          qualifies, the nearest overall, flagged ``ambiguous_cycle_node``.
        - Never raises.
    """
    entry = containment.get(place_key(name))
    if entry is None:
        return None, ("unresolved_place",)
    flags: list[str] = []
    if not entry.confirmed:
        flags.append("unconfirmed_place")

    if entry.kind is PlaceKind.MICRO and entry.parent_key:
        parent = containment.get(entry.parent_key)
        if parent is None:
            return None, (*flags, "unresolved_parent")
        entry = parent

    if entry.kind is PlaceKind.WAYPOINT and entry.leg is not None:
        return RoutePoint(entry.leg, entry.along or 0.0), tuple(flags)

    if entry.kind is not PlaceKind.NODE or not entry.node_indices:
        return None, tuple(flags)

    last_leg = len(spine.legs) - 1
    candidates = [RoutePoint.at_node(index, last_leg) for index in entry.node_indices]
    if len(candidates) == 1:
        return candidates[0], tuple(flags)

    ahead = [point for point in candidates if carried is None or point >= carried]
    if ahead:
        return min(ahead), tuple(flags)
    return max(candidates), (*flags, "ambiguous_cycle_node")


def resolve_positions(
    extractions: Mapping[int, ChapterExtraction],
    spine: RouteSpine,
    containment: Mapping[str, Containment],
    tracks: Sequence[Track],
    chapters: Sequence[int] | None = None,
) -> list[ChapterPositions]:
    """Work out where every track is in every chapter.

    Args:
        extractions: The parsed extractions, keyed by chapter number.
        spine: The route from chapter 3.
        containment: The confirmed place map.
        tracks: The roster.
        chapters: Which chapters to cover. Defaults to those present in ``extractions``.

    Returns:
        One entry per chapter, each holding one row per track.

    Contract:
        - Emits a row for every (chapter, track) pair, so a carried position is visible
          rather than implied by a gap.
        - A track is ``UNKNOWN`` until the text first places it; it never defaults
          to the route's starting node.
        - The last resolvable ``on_stage`` entry for a track wins, so a chapter that
          moves someone ends where the chapter ends.
        - Never raises.
    """
    wanted = sorted(chapters if chapters is not None else extractions)
    carried: dict[str, RoutePoint | None] = {track.key: None for track in tracks}
    stated_at: dict[str, int | None] = {track.key: None for track in tracks}
    out: list[ChapterPositions] = []

    for number in wanted:
        extraction = extractions.get(number)
        rows: list[TrackPosition] = []
        scene: list[str] = []

        if extraction is not None:
            for item in extraction.narrative.on_stage:
                for place in (item.at_name_in_text, item.between_to, item.between_from):
                    if place and place not in scene:
                        scene.append(place)

        for track in tracks:
            row = _resolve_track(
                number, track, extraction, spine, containment, carried, stated_at
            )
            rows.append(row)
            if row.source in (PositionSource.STATED, PositionSource.INFERRED):
                carried[track.key] = row.point
                stated_at[track.key] = number

        out.append(
            ChapterPositions(
                chapter=number, tracks=tuple(rows), scene_places=tuple(scene)
            )
        )
    return out


def _resolve_track(
    number: int,
    track: Track,
    extraction: ChapterExtraction | None,
    spine: RouteSpine,
    containment: Mapping[str, Containment],
    carried: Mapping[str, RoutePoint | None],
    stated_at: Mapping[str, int | None],
) -> TrackPosition:
    """Resolve one track in one chapter, down the priority order."""
    held = carried[track.key]
    if extraction is None:
        return _carry(number, track, held, stated_at[track.key])

    on_stage = [
        item
        for item in extraction.narrative.on_stage
        if track.matches(item.name_in_text)
    ]
    if not on_stage:
        return _carry(number, track, held, stated_at[track.key])

    # Last entry first: a chapter that moves someone ends where the chapter ends.
    for item in reversed(on_stage):
        point, flags = _point_for(item, containment, spine, held)
        if point is not None:
            place = item.at_name_in_text or item.between_to or item.between_from
            return TrackPosition(
                chapter=number,
                track=track.key,
                point=point,
                source=PositionSource.STATED,
                place_name_in_text=place,
                stated_at_chapter=number,
                evidence=item.evidence,
                flags=flags,
            )

    # On stage, but the chapter never said where. Fall back to what it did say about
    # places — a fallback, not the mechanism.
    for place in extraction.places_visited:
        if place.role is PlaceRole.SETTING:
            continue
        point, flags = resolve_point(place.name_in_text, containment, spine, held)
        if point is not None:
            return TrackPosition(
                chapter=number,
                track=track.key,
                point=point,
                source=PositionSource.INFERRED,
                place_name_in_text=place.name_in_text,
                stated_at_chapter=number,
                evidence=place.evidence,
                flags=(*flags, "inferred_from_places_visited"),
            )

    return _carry(number, track, held, stated_at[track.key], on_stage=True)


def _point_for(
    item: object,
    containment: Mapping[str, Containment],
    spine: RouteSpine,
    held: RoutePoint | None,
) -> tuple[RoutePoint | None, tuple[str, ...]]:
    """Resolve one ``on_stage`` entry: a place, or an interval in transit."""
    at = getattr(item, "at_name_in_text", None)
    origin = getattr(item, "between_from", None)
    destination = getattr(item, "between_to", None)

    if at:
        return resolve_point(at, containment, spine, held)

    if origin and destination:
        start, flags_a = resolve_point(origin, containment, spine, held)
        end, flags_b = resolve_point(destination, containment, spine, start or held)
        if start is not None and end is not None:
            return start.midpoint(end), (*flags_a, *flags_b, "in_transit")
        return (end or start), (*flags_a, *flags_b, "in_transit")

    if destination:
        end, flags = resolve_point(destination, containment, spine, held)
        if end is None:
            return None, flags
        if held is None:
            return end, (*flags, "in_transit")
        return held.midpoint(end), (*flags, "in_transit")

    if origin:
        start, flags = resolve_point(origin, containment, spine, held)
        if start is None:
            return None, flags
        return RoutePoint(start.leg, min(start.along + _JUST_UNDER_WAY, 1.0)), (
            *flags,
            "in_transit",
        )

    return None, ()


def _carry(
    number: int,
    track: Track,
    held: RoutePoint | None,
    since: int | None,
    on_stage: bool = False,
) -> TrackPosition:
    """Build a carried-forward or still-unknown row."""
    if held is None:
        return TrackPosition(chapter=number, track=track.key)
    return TrackPosition(
        chapter=number,
        track=track.key,
        point=held,
        source=PositionSource.CARRIED,
        stated_at_chapter=since,
        flags=("on_stage_without_a_place",) if on_stage else (),
    )


def classify_mentions(
    extraction: ChapterExtraction,
    fogg_point: RoutePoint | None,
    containment: Mapping[str, Containment],
    spine: RouteSpine,
) -> dict[str, TemporalClass]:
    """Sort a chapter's mentioned places into past, here, future and off-route.

    The rule for a repeated name is deliberately **not** the one
    :func:`resolve_point` uses, and the difference is the point. Resolution leans on the
    carried position to pick a single London, because the party is in exactly one place.
    A mentioned place is not the party's position, so a name with candidates on both
    sides stays ``CYCLIC`` instead of being forced — which is what stops chapter 3's
    "I shall be due in London in this very room" from being labelled ``HERE`` when the
    text plainly means the return.

    Args:
        extraction: The chapter.
        fogg_point: Where Fogg is in this chapter.
        containment: The confirmed place map.
        spine: The route.

    Returns:
        One class per mentioned place, keyed by the name as printed.

    Contract:
        - Every ``places_mentioned`` entry appears in the result.
        - Everything is ``UNKNOWN`` when Fogg's position is unknown.
        - Never raises.
    """
    last_leg = len(spine.legs) - 1
    out: dict[str, TemporalClass] = {}
    for place in extraction.places_mentioned:
        name = place.name_in_text
        entry = containment.get(place_key(name))
        if entry is None:
            out[name] = TemporalClass.UNKNOWN
            continue
        points = _candidates(entry, containment, last_leg)
        if not points:
            out[name] = TemporalClass.OFF_ROUTE
            continue
        if fogg_point is None:
            out[name] = TemporalClass.UNKNOWN
            continue
        if any(point == fogg_point for point in points):
            out[name] = TemporalClass.HERE
        elif all(point < fogg_point for point in points):
            out[name] = TemporalClass.PAST
        elif all(point > fogg_point for point in points):
            out[name] = TemporalClass.FUTURE
        else:
            out[name] = TemporalClass.CYCLIC
    return out


def _candidates(
    entry: Containment, containment: Mapping[str, Containment], last_leg: int
) -> list[RoutePoint]:
    """Every point a place could refer to — all of them, so the cycle stays visible."""
    if entry.kind is PlaceKind.MICRO and entry.parent_key:
        parent = containment.get(entry.parent_key)
        return _candidates(parent, containment, last_leg) if parent else []
    if entry.kind is PlaceKind.WAYPOINT and entry.leg is not None:
        return [RoutePoint(entry.leg, entry.along or 0.0)]
    if entry.kind is PlaceKind.NODE:
        return [RoutePoint.at_node(index, last_leg) for index in entry.node_indices]
    return []


def check_positions(
    chapters: Sequence[ChapterPositions],
    spine: RouteSpine,
    final_chapter: int = 37,
) -> list[str]:
    """Report everything worth a human glance about a resolved series.

    Only the terminal check is an error. A backwards step is a warning and stays one:
    Verne doubles back for real, and a resolver that corrected chapters 30 and 32–34
    would be lying about the book.

    Args:
        chapters: The resolved series.
        spine: The route.
        final_chapter: The chapter Fogg must end at the closing London in.

    Returns:
        Human-readable problems and warnings, most severe first.

    Contract:
        - Never raises.
        - An empty result means every track moved plausibly and Fogg finished the cycle.
    """
    problems: list[str] = []
    warnings: list[str] = []
    last_leg = len(spine.legs) - 1
    closing = RoutePoint(last_leg, 1.0)

    by_track: dict[str, list[TrackPosition]] = {}
    for entry in chapters:
        for row in entry.tracks:
            by_track.setdefault(row.track, []).append(row)

    final = next(
        (row for row in by_track.get("fogg", []) if row.chapter == final_chapter), None
    )
    if final is not None and final.point is not None and final.point != closing:
        problems.append(
            f"fogg ends chapter {final_chapter} at leg {final.point.leg} "
            f"@{final.point.along} rather than the closing London — "
            "the cycle collapsed, and everything past Yokohama is suspect"
        )

    for track, rows in by_track.items():
        stated = [
            row
            for row in rows
            if row.source is PositionSource.STATED and row.point is not None
        ]
        for previous, current in zip(stated, stated[1:], strict=False):
            assert previous.point is not None and current.point is not None
            if current.point < previous.point:
                warnings.append(
                    f"{track} moves backwards at chapter {current.chapter:02d} "
                    f"(leg {previous.point.leg} -> {current.point.leg}) — "
                    "check this is one of the real doublings-back"
                )
            elif current.point.leg - previous.point.leg > 1:
                warnings.append(
                    f"{track} jumps {current.point.leg - previous.point.leg} legs at "
                    f"chapter {current.chapter:02d}"
                )
        if not stated:
            warnings.append(f"{track} is never placed by any chapter")

    for entry in chapters:
        rows = {row.track: row for row in entry.tracks}
        fogg, fix = rows.get("fogg"), rows.get("fix")
        if fogg and fix and fogg.point and fix.point and fix.point > fogg.point:
            warnings.append(
                f"fix is ahead of fogg at chapter {entry.chapter:02d} — "
                "expected at chapter 06, worth a look anywhere else"
            )
        pp = rows.get("passepartout")
        if fogg and pp and fogg.point and pp.point and fogg.point != pp.point:
            warnings.append(
                f"passepartout is apart from fogg at chapter {entry.chapter:02d}"
            )
        for row in entry.tracks:
            for flag in row.flags:
                if flag in {"unresolved_place", "unresolved_parent"}:
                    problems.append(
                        f"chapter {entry.chapter:02d} {row.track}: "
                        f"{row.place_name_in_text!r} does not resolve onto the route — "
                        "add it to data/review/places.csv"
                    )

    return problems + warnings


def coverage(
    chapters: Sequence[ChapterPositions], track: str = "fogg"
) -> tuple[int, int]:
    """How many chapters state a position for a track, out of how many.

    A number worth watching at chapter ten rather than discovering at chapter
    thirty-seven: if it stays low, the narrative block is not earning its keep.

    Args:
        chapters: The resolved series.
        track: Which track to count.

    Returns:
        A ``(stated, total)`` pair.

    Examples:
        >>> coverage([], "fogg")
        (0, 0)
    """
    rows = [row for entry in chapters for row in entry.tracks if row.track == track]
    stated = sum(1 for row in rows if row.source is PositionSource.STATED)
    return stated, len(rows)


def positions_to_dict(
    chapters: Sequence[ChapterPositions],
    spine: RouteSpine,
    mentions: Mapping[int, Mapping[str, TemporalClass]] | None = None,
) -> dict[str, object]:
    """Render the resolved series for ``data/processed/positions.json``.

    Args:
        chapters: The resolved series.
        spine: The route, for node labels.
        mentions: Per-chapter mentioned-place classes, if computed.

    Returns:
        The series, ready to serialise.
    """
    last_leg = len(spine.legs) - 1
    return {
        "generated_by": "scripts/06_positions.py",
        "chapters": [
            {
                "chapter": entry.chapter,
                "scene_places": list(entry.scene_places),
                "mentions": dict((mentions or {}).get(entry.chapter, {})),
                "tracks": [
                    {
                        "track": row.track,
                        "leg": row.point.leg if row.point else None,
                        "along": row.point.along if row.point else None,
                        "at_node": _node_label(row.point, spine, last_leg),
                        "source": row.source.value,
                        "place_name_in_text": row.place_name_in_text,
                        "stated_at_chapter": row.stated_at_chapter,
                        "evidence": row.evidence,
                        "flags": list(row.flags),
                    }
                    for row in entry.tracks
                ],
            }
            for entry in chapters
        ],
    }


def _node_label(
    point: RoutePoint | None, spine: RouteSpine, last_leg: int
) -> str | None:
    """The node name when a point sits exactly on one, else None."""
    if point is None:
        return None
    if point.along == 0.0:
        return spine.nodes[point.leg].name_in_text
    if point.leg == last_leg and point.along == 1.0:
        return spine.nodes[-1].name_in_text
    return None


def format_run_log(
    chapters: Sequence[ChapterPositions], tracks: Iterable[Track]
) -> list[str]:
    """The per-chapter lines a stage script prints."""
    keys = [track.key for track in tracks]
    lines: list[str] = []
    for entry in chapters:
        rows = {row.track: row for row in entry.tracks}
        cells = []
        for key in keys:
            row = rows.get(key)
            if row is None or row.point is None:
                cells.append(f"{key} —")
                continue
            where = row.place_name_in_text or ""
            if row.source is PositionSource.CARRIED:
                where = f"carried from {row.stated_at_chapter:02d}"
            cell = f"{key} leg {row.point.leg}@{row.point.along:.2f} {where}"
            cells.append(cell.strip())
        scene = ""
        if entry.scene_places:
            scene = f"   scene: {', '.join(entry.scene_places)}"
        lines.append(f"  ch {entry.chapter:02d}   " + "   ".join(cells) + scene)
    return lines
