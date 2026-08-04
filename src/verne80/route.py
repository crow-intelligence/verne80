r"""Fogg's own itinerary, parsed out of chapter 3.

The novel contains its own dataset, and this is the load-bearing piece of it. In chapter
3 Fogg answers his doubters by reading out a table: eight legs, the mode of travel for
each, a day count for each, and a printed total. That table is the canonical route — and
because the leg days must sum to the number printed underneath them, it is a
**self-verifying oracle**, in the same way the book's table of contents was for the
chapter split. Parse it strictly, add the parts up, and the text tells you whether you
read it correctly.

Four traps in the printed form, each of which looks like an encoding bug:

1. **The first entry wraps.** It ends ``by rail and`` and continues ``steamboats
   ................. 7 days`` on the next line, so no line-anchored pattern spans it.
2. **A ditto mark stands in for the unit.** Only the first entry and the total print the
   word "days"; entries two to eight end ``13 ”`` with U+201D.
3. **``_viâ_``** carries both Gutenberg's underscore italics and a circumflex.
4. **``Yokohama (Japan)``** is the destination of one leg and ``Yokohama`` the origin
   of the next. The same node, two printed spellings.

And one structural fact that shapes the whole module: **London appears at both ends.**
The route is a cycle, so a node's identity is its position in the sequence, never its
name. The only lookup by name here is :meth:`RouteSpine.indices_named`, which returns a
tuple —
``"London"`` gives ``(0, 8)``. There is deliberately no ``node_by_name`` returning one
node, because that function's whole purpose would be to let a caller collapse the two
Londons without noticing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from verne80.normalize import fold_typography, match_key, normalize_quote
from verne80.schema import TransportMode, normalise_mode

__all__ = [
    "EXPECTED_LEGS",
    "EXPECTED_TOTAL_DAYS",
    "RouteLeg",
    "RouteNode",
    "RouteSpine",
    "check_spine",
    "itinerary_block",
    "parse_itinerary",
    "split_via",
]

EXPECTED_LEGS = 8
EXPECTED_TOTAL_DAYS = 80

# The two anchors matching far apart means we swallowed prose, not a table.
MAX_BLOCK_CHARS = 2000

_BLOCK_START = re.compile(r"^From\s+.+?\s+to\s+.+?,\s+by\s+", re.MULTILINE)
_BLOCK_END = re.compile(r"^Total\s*\.{3,}\s*(?P<days>\d+)\s+days\.", re.MULTILINE)

# Inside the block, a continuation line begins with a lowercase letter; every real entry
# begins with "From" or "Total". Unwrapping is a decision made here, not an accident of
# some pattern happening to match across a newline.
_CONTINUATION = re.compile(r"\n(?=[a-z])")

# The unit is "days" on the first entry and the total, and a ditto mark on the rest.
# Both the curly and the straight double quote are accepted so this works on raw text
# and on text that has already been through normalize_quote.
TABLE_LEG = re.compile(
    r"^From\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+?),\s+by\s+(?P<mode>[^.]+?)"
    r"\s*\.{3,}\s*(?P<days>\d+)\s*(?:days|”|\")\s*$",
    re.MULTILINE,
)

_VIA = re.compile(r"\s+_?vi[aâ]_?\s+", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
_AND = re.compile(r"\s+and\s+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RouteNode:
    """One stop on the canonical route.

    Attributes:
        index: Position in the sequence, ``0..8``. **This is the node's identity** — the
            route is a cycle and London occupies both index 0 and index 8.
        name_in_text: The first printed spelling, e.g. ``"Yokohama (Japan)"``.
        key: The canonical name under :func:`~verne80.normalize.match_key`, with any
            parenthetical dropped — ``"yokohama"``.
        printed_forms: Every spelling the table used for this position.
    """

    index: int
    name_in_text: str
    key: str
    printed_forms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteLeg:
    """One leg of the itinerary, as Fogg read it out.

    Attributes:
        index: Position in the sequence, ``0..7``.
        origin: Where the leg starts.
        destination: Where it ends.
        days: The budgeted days, as printed.
        mode_as_written: The mode phrase, e.g. ``"rail and steamboats"``.
        modes: Those words coerced onto the schema's terms.
        origin_as_written: The origin exactly as this entry printed it. Kept separate
            from ``origin`` because the node sequence is built from destinations: if a
            leg's printed origin disagrees with the previous leg's destination, the
            chain is broken, and only this field can still show it.
        via_as_written: Intermediate places the table itself names, e.g.
            ``("Mont Cenis", "Brindisi")`` for the first leg.
    """

    index: int
    origin: RouteNode
    destination: RouteNode
    origin_as_written: str
    days: int
    mode_as_written: str
    modes: tuple[TransportMode, ...]
    via_as_written: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteSpine:
    """The whole route: nine node slots, eight legs, eighty days.

    Attributes:
        nodes: The stops, in order. ``nodes[0]`` and ``nodes[-1]`` are both London.
        legs: The legs, in order.
        total_days_printed: The figure printed under the table.
        source_chapter: Which chapter the table was read from.
        source_sha256: Hex digest of that chapter's file — the drift alarm, matching the
            per-chapter hashes in ``data/chapters/index.json``.
    """

    nodes: tuple[RouteNode, ...]
    legs: tuple[RouteLeg, ...]
    total_days_printed: int
    source_chapter: int = 3
    source_sha256: str = ""

    def node(self, index: int) -> RouteNode:
        """The node at a position.

        Args:
            index: A node index.

        Returns:
            That node.

        Raises:
            IndexError: If the index is out of range.
        """
        return self.nodes[index]

    def leg(self, index: int) -> RouteLeg:
        """The leg at a position.

        Args:
            index: A leg index.

        Returns:
            That leg.

        Raises:
            IndexError: If the index is out of range.
        """
        return self.legs[index]

    def indices_named(self, name: str) -> tuple[int, ...]:
        """Every node position a name refers to.

        Returns a tuple, always, because London refers to two. This is the only lookup
        by name in the module, and its signature is the reason the cycle cannot be
        collapsed by accident.

        Args:
            name: A place name, in any spelling.

        Returns:
            The matching node indices, in order. Empty if the name is not on the route.

        Contract:
            - ``len(result) == 0`` for a place that is not a route node.
            - The result is sorted and its entries index :attr:`nodes`.
            - Matching folds typography and case, so ``"yokohama (japan)"`` finds
              ``Yokohama``.

        Examples:
            >>> spine = parse_itinerary(_EXAMPLE_TABLE)
            >>> spine.indices_named("London")
            (0, 2)
            >>> spine.indices_named("Suez")
            (1,)
            >>> spine.indices_named("Timbuktu")
            ()
        """
        wanted = _node_key(name)
        return tuple(node.index for node in self.nodes if node.key == wanted)

    def cumulative_days(self) -> tuple[int, ...]:
        """The planned arrival day at each node, counting from zero at the start.

        Becomes the planned column of the timeline ledger later, which is why the spine
        earns its keep twice.

        Returns:
            One entry per node; the first is ``0`` and the last is the total.

        Contract:
            - ``len(result) == len(nodes)``.
            - Non-decreasing, ``result[0] == 0``, and ``result[-1] == sum(leg.days)``.

        Examples:
            >>> parse_itinerary(_EXAMPLE_TABLE).cumulative_days()
            (0, 7, 20)
        """
        running = 0
        out = [0]
        for leg in self.legs:
            running += leg.days
            out.append(running)
        return tuple(out)


def itinerary_block(chapter_text: str) -> str:
    """Cut the itinerary table out of a chapter, and unwrap its continuation lines.

    Args:
        chapter_text: The chapter to search.

    Returns:
        The table, from the first ``From ...`` entry through the ``Total`` line, with
        wrapped entries joined.

    Raises:
        ValueError: If either anchor is missing, or they match so far apart that what
        lies
            between them cannot be a table.

    Contract:
        - The result starts with ``From`` and ends with the total line.
        - No entry in the result spans a newline.
    """
    start = _BLOCK_START.search(chapter_text)
    if start is None:
        raise ValueError(
            "no itinerary table found — expected a line like "
            "'From London to Suez ... 7 days'"
        )
    end = _BLOCK_END.search(chapter_text, start.start())
    if end is None:
        raise ValueError(
            "the itinerary table has no 'Total ... N days.' line — "
            "without it there is nothing to check the legs against"
        )
    block = fold_typography(chapter_text[start.start() : end.end()])
    if len(block) > MAX_BLOCK_CHARS:
        raise ValueError(
            f"the itinerary table would be {len(block):,} characters "
            f"(limit {MAX_BLOCK_CHARS:,}) — the anchors matched across prose"
        )
    return _CONTINUATION.sub(" ", block)


def split_via(destination: str) -> tuple[str, tuple[str, ...]]:
    """Separate a destination from the *via* clause the table attaches to it.

    Args:
        destination: A destination as printed, possibly with a via clause and a
            parenthetical.

    Returns:
        A ``(destination, via)`` pair, both with typography folded.

    Contract:
        - The destination never contains "via" or a trailing parenthetical.
        - ``via`` is empty when the entry names no intermediate places.

    Examples:
        >>> split_via("Suez _viâ_ Mont Cenis and Brindisi")
        ('Suez', ('Mont Cenis', 'Brindisi'))
        >>> split_via("Yokohama (Japan)")
        ('Yokohama', ())
    """
    parts = _VIA.split(normalize_quote(destination), maxsplit=1)
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else ""
    via = tuple(part.strip() for part in _AND.split(tail) if part.strip())
    return _PARENTHETICAL.sub("", head).strip(), via


def _node_key(name: str) -> str:
    """The key a node is identified by: folded, case-less, parenthetical dropped."""
    return match_key(_PARENTHETICAL.sub("", normalize_quote(name)))


def parse_itinerary(
    chapter_text: str, *, chapter: int = 3, source_sha256: str = ""
) -> RouteSpine:
    """Read Fogg's itinerary table into a route spine.

    Raises rather than guessing, in the same spirit as
    :func:`~verne80.chapters.roman_to_int`: a lenient parse here yields a plausible
    wrong route, and a plausible wrong route reorders the map without anything looking
    amiss. Softer problems — a leg count that is not eight, days that do not add up —
    are for :func:`check_spine` to report.

    Args:
        chapter_text: The chapter containing the table.
        chapter: Which chapter that is, recorded for provenance.
        source_sha256: Hex digest of the chapter file, recorded as the drift alarm.

    Returns:
        The parsed spine.

    Raises:
        ValueError: If the table cannot be found, or contains no parsable entry.

    Contract:
        - ``len(nodes) == len(legs) + 1``.
        - Node indices are ``0..len(nodes) - 1``, in document order.
        - ``legs[i].destination is nodes[i + 1]`` and ``legs[i].origin is nodes[i]``.
        - Pure and deterministic.

    Examples:
        >>> spine = parse_itinerary(_EXAMPLE_TABLE)
        >>> [(leg.origin.name_in_text, leg.destination.name_in_text) for leg in
        ...  spine.legs]
        [('London', 'Suez'), ('Suez', 'London')]
        >>> spine.legs[0].via_as_written
        ('Mont Cenis',)
        >>> spine.legs[0].modes
        (<TransportMode.RAILWAY: 'railway'>, <TransportMode.STEAMER: 'steamer'>)
    """
    block = itinerary_block(chapter_text)
    matches = list(TABLE_LEG.finditer(block))
    if not matches:
        raise ValueError(
            "the itinerary table was found but no leg could be read from it — "
            "the printed form has changed"
        )

    nodes: list[RouteNode] = []
    legs: list[RouteLeg] = []
    for position, match in enumerate(matches):
        origin_name = normalize_quote(match.group("origin"))
        # The via clause is not part of the name; a parenthetical is a spelling of it.
        printed_destination = _VIA.split(
            normalize_quote(match.group("destination")), 1
        )[0]
        destination_name, via = split_via(match.group("destination"))
        if position == 0:
            nodes.append(_make_node(0, origin_name))
        else:
            # The same slot as the previous destination: record the spelling variant
            # rather than adding a node, which is what unifies "Yokohama (Japan)".
            if _node_key(origin_name) == nodes[-1].key:
                nodes[-1] = _with_form(nodes[-1], origin_name)
        # Record the parenthetical spelling too: "Yokohama (Japan)" and "Yokohama" are
        # one node, and printed_forms is where that fact is kept.
        nodes.append(
            _with_form(_make_node(position + 1, destination_name), printed_destination)
        )
        legs.append(
            RouteLeg(
                index=position,
                origin=nodes[-2],
                destination=nodes[-1],
                origin_as_written=origin_name,
                days=int(match.group("days")),
                mode_as_written=normalize_quote(match.group("mode")),
                modes=_parse_modes(match.group("mode")),
                via_as_written=via,
            )
        )

    # The legs were built against nodes that have since gained spelling variants;
    # rebuild them so `leg.origin is spine.nodes[i]` holds, which the contract promises.
    frozen = tuple(nodes)
    legs = [
        RouteLeg(
            index=leg.index,
            origin=frozen[leg.index],
            destination=frozen[leg.index + 1],
            origin_as_written=leg.origin_as_written,
            days=leg.days,
            mode_as_written=leg.mode_as_written,
            modes=leg.modes,
            via_as_written=leg.via_as_written,
        )
        for leg in legs
    ]

    total = _BLOCK_END.search(block)
    return RouteSpine(
        nodes=frozen,
        legs=tuple(legs),
        total_days_printed=int(total.group("days")) if total else 0,
        source_chapter=chapter,
        source_sha256=source_sha256,
    )


def _make_node(index: int, name: str) -> RouteNode:
    """Build a node from one printed spelling."""
    return RouteNode(
        index=index,
        name_in_text=name,
        key=_node_key(name),
        printed_forms=(name,),
    )


def _with_form(node: RouteNode, name: str) -> RouteNode:
    """Record another printed spelling for a node already in the sequence."""
    if name in node.printed_forms:
        return node
    return RouteNode(
        index=node.index,
        name_in_text=node.name_in_text,
        key=node.key,
        printed_forms=(*node.printed_forms, name),
    )


def _parse_modes(phrase: str) -> tuple[TransportMode, ...]:
    """Coerce a mode phrase like "rail and steamboats" onto the schema's terms."""
    seen: list[TransportMode] = []
    for word in _AND.split(normalize_quote(phrase)):
        mode = normalise_mode(word.strip().rstrip("s"))
        if isinstance(mode, str):
            mode = TransportMode(mode)
        if mode not in seen:
            seen.append(mode)
    return tuple(seen)


def check_spine(spine: RouteSpine) -> list[str]:
    """Report everything that looks wrong about a parsed route.

    Returns problems rather than raising, matching
    :func:`~verne80.chapters.check_chapters`; the stage script writes nothing when the
    list is non-empty.

    The third check is the oracle: the leg days must sum to the number printed under the
    table. Nothing else in the parse is cross-checked by the text itself.

    Args:
        spine: The parsed route.

    Returns:
        Human-readable problems, empty when the route looks sound.

    Contract:
        - Never raises, for any spine.

    Examples:
        >>> check_spine(parse_itinerary(_EXAMPLE_TABLE))[0]
        'found 2 legs, expected 8'
    """
    problems: list[str] = []
    if len(spine.legs) != EXPECTED_LEGS:
        problems.append(f"found {len(spine.legs)} legs, expected {EXPECTED_LEGS}")
    if len(spine.nodes) != len(spine.legs) + 1:
        problems.append(
            f"{len(spine.nodes)} nodes for {len(spine.legs)} legs — "
            "the chain is not a simple sequence"
        )

    total = sum(leg.days for leg in spine.legs)
    if total != spine.total_days_printed:
        problems.append(
            f"the legs add up to {total} days but the table prints "
            f"{spine.total_days_printed} — the parse dropped or misread an entry"
        )
    elif total != EXPECTED_TOTAL_DAYS:
        problems.append(
            f"the itinerary totals {total} days, expected {EXPECTED_TOTAL_DAYS}"
        )

    for leg in spine.legs:
        label = f"leg {leg.index}"
        if leg.days <= 0:
            problems.append(f"{label} takes {leg.days} days")
        if not leg.modes:
            problems.append(f"{label} names no mode of travel")
        if leg.origin.key == leg.destination.key:
            problems.append(f"{label} goes from {leg.origin.name_in_text!r} to itself")

    for first, second in zip(spine.legs, spine.legs[1:], strict=False):
        if first.destination.key != _node_key(second.origin_as_written):
            problems.append(
                f"leg {first.index} ends at {first.destination.name_in_text!r} but "
                f"leg {second.index} starts at {second.origin_as_written!r} — "
                "the chain is broken"
            )

    if spine.nodes:
        opening, closing = spine.nodes[0], spine.nodes[-1]
        if opening.key != closing.key:
            problems.append(
                f"the route starts at {opening.name_in_text!r} and ends at "
                f"{closing.name_in_text!r} — it should return to where it began"
            )
        elif opening.index == closing.index:
            problems.append(
                "the route's two endpoints share an index — the cycle collapsed"
            )

    interior = [node.key for node in spine.nodes[1:-1]]
    repeated = sorted({key for key in interior if interior.count(key) > 1})
    if repeated:
        problems.append(f"these stops appear more than once mid-route: {repeated}")

    return problems


def route_to_dict(spine: RouteSpine) -> dict[str, object]:
    """Render a spine for ``data/processed/route_spine.json``.

    Args:
        spine: The parsed route.

    Returns:
        The spine, ready to serialise.
    """
    return {
        "generated_by": "scripts/04_route.py",
        "source": {
            "chapter": spine.source_chapter,
            "sha256": spine.source_sha256,
            "note": "Fogg's own itinerary, as he reads it out in chapter 3",
        },
        "total_days_printed": spine.total_days_printed,
        "cumulative_days": list(spine.cumulative_days()),
        "nodes": [
            {
                "index": node.index,
                "name_in_text": node.name_in_text,
                "key": node.key,
                "printed_forms": list(node.printed_forms),
            }
            for node in spine.nodes
        ],
        "legs": [
            {
                "index": leg.index,
                "origin": leg.origin.index,
                "destination": leg.destination.index,
                "days": leg.days,
                "mode_as_written": leg.mode_as_written,
                "modes": [mode.value for mode in leg.modes],
                "via_as_written": list(leg.via_as_written),
            }
            for leg in spine.legs
        ],
    }


def format_run_log(spine: RouteSpine) -> list[str]:
    """The per-leg lines a stage script prints.

    Args:
        spine: The parsed route.

    Returns:
        One line per leg, then a summary.
    """
    lines = []
    width = max((len(node.name_in_text) for node in spine.nodes), default=0)
    for leg in spine.legs:
        modes = "+".join(mode.value for mode in leg.modes)
        via = f"  via {', '.join(leg.via_as_written)}" if leg.via_as_written else ""
        lines.append(
            f"  leg {leg.index}   {leg.origin.name_in_text:<{width}} -> "
            f"{leg.destination.name_in_text:<{width}}  {leg.days:2d} days  "
            f"{modes:<16}{via}"
        )
    lines.append("  ---")
    ends = _describe_endpoints(spine)
    lines.append(
        f"  {len(spine.legs)} legs, {len(spine.nodes)} nodes, "
        f"{sum(leg.days for leg in spine.legs)} days "
        f"(printed {spine.total_days_printed}){ends}"
    )
    return lines


def _describe_endpoints(spine: RouteSpine) -> str:
    """Name the cycle explicitly in the run log, so it cannot be mistaken for a bug."""
    if not spine.nodes:
        return ""
    indices = spine.indices_named(spine.nodes[0].name_in_text)
    if len(indices) < 2:
        return ""
    return (
        f"   {spine.nodes[0].name_in_text} at index "
        f"{' and index '.join(str(i) for i in indices)}"
    )


# A two-leg table in the printed form, for the doctests: it carries the wrap, the ditto
# mark, the italicised via clause and the parenthetical, so the examples above exercise
# every trap without needing the committed chapter.
_EXAMPLE_TABLE = """\
From London to Suez _viâ_ Mont Cenis, by rail and
steamboats ................. 7 days
From Suez to London (England), by steamer .......... 13 ”
--------
Total ............................................ 20 days.”
"""


def spine_from_nodes(names: Sequence[str], days: Sequence[int]) -> RouteSpine:
    """Build a spine directly, for tests that need a route without a printed table.

    Args:
        names: Node names, in order.
        days: One day count per leg, so ``len(days) == len(names) - 1``.

    Returns:
        The spine.

    Raises:
        ValueError: If the lengths do not line up.

    Examples:
        >>> spine_from_nodes(["London", "Suez", "London"], [7, 13]).cumulative_days()
        (0, 7, 20)
    """
    if len(days) != len(names) - 1:
        raise ValueError(
            f"{len(names)} nodes need {len(names) - 1} legs, got {len(days)}"
        )
    nodes = tuple(_make_node(i, name) for i, name in enumerate(names))
    legs = tuple(
        RouteLeg(
            index=i,
            origin=nodes[i],
            destination=nodes[i + 1],
            origin_as_written=names[i],
            days=day,
            mode_as_written="steamer",
            modes=(TransportMode.STEAMER,),
            via_as_written=(),
        )
        for i, day in enumerate(days)
    )
    return RouteSpine(nodes=nodes, legs=legs, total_days_printed=sum(days))
