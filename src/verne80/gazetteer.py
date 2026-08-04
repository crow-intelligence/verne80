r"""Resolve 1872 place names to modern entities, coordinates and names.

Spec §2.3 asks for both names plus coordinates plus ``name_changed``, because the change
itself is the content: Bombay→Mumbai, Calcutta→Kolkata, Yokohama→Yokohama. This module
does the resolving; :mod:`verne80.reviewmap` does the looking-at, which is where the
errors actually get caught.

Everything here except :class:`GazetteerClient` is pure. :func:`resolve_place` takes
candidates rather than fetching them, so the ranking, the confidence and the name
comparison are all testable with no network, no cache and no fixture file. That split is
deliberate: the ranking is where the wrong answers come from, and it is retired offline.

**How a candidate wins.** :func:`score_candidate` returns a tuple, sorted
lexicographically, so each term dominates the ones below it absolutely rather than being
traded off against them:

0. **is_place** — a gate, not a nudge. "Mongolia" the country and "Mongolia" the steamer
   are separated by one of them not being a place, not by being three thousand
   kilometres from the route.
1. **name** — bucketed, not continuous, so proximity can break ties *within* a bucket
   and never across one. A differently-named place near the route must not beat an
   exactly-named one further off; the text named a station, and its name is stronger
   evidence than its neighbourhood.
2. **route proximity** — the signal that is ours alone. A "Springfield" two hundred
   kilometres off the Pacific Railroad beats a "Springfield" in Queensland, and no
   measure of Wikidata prominence would ever have said so.
3. **prominence** — last, on purpose. Prominence is exactly what sends a village on
   the route to the wrong continent's capital city, so it may only break a tie the
   first three terms left standing.

**Confidence is not the winner's score.** It is the score discounted by how close the
runner-up came, so a photo finish is reported as uncertain even when both candidates
score well. That is the number the map colours by, because "there were two of these
and I picked one" is precisely what a reviewer needs to see and precisely what a plain
score hides.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from verne80.normalize import match_key, normalize_quote, place_key

__all__ = [
    "GazetteerCache",
    "GazetteerClient",
    "OfflineError",
    "RateLimiter",
    "PlaceCandidate",
    "Resolution",
    "best_candidate",
    "haversine_km",
    "merge_candidates",
    "name_changed",
    "nearest_km",
    "place_search_query",
    "resolve_place",
    "score_candidate",
    "sparql_string",
]

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
USER_AGENT = (
    "verne80/0.1 (https://github.com/crow-intelligence/verne80; "
    "zoltan.varju@crowintelligence.org) python-httpx"
)

# Bumped by hand when a query's shape changes, which invalidates the cache. Manual on
# purpose: hashing the query text would invalidate on a whitespace edit and cost 350
# requests for nothing, whereas incrementing an integer is a decision visible in the
# diff.
QUERY_VERSION = 1

# The statuses worth trying again: rate limiting, and the transient server faults
# a public endpoint occasionally returns under load.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

EARTH_RADIUS_KM = 6371.0088

# The distance at which route proximity is worth half its maximum. Chosen so that a
# stop a few hundred kilometres off the line still scores usefully — Verne's American
# towns are strung along a railway, not sitting on a mathematical line.
PROXIMITY_HALF_LIFE_KM = 500.0

# Wikidata classes that are emphatically not somewhere the party can be. The query
# already requires coordinates, which removes most of the noise; these are the things
# that have coordinates and still are not places.
NOT_A_PLACE_QIDS = frozenset(
    {
        "Q5",  # human
        "Q11424",  # film
        "Q7725634",  # literary work
        "Q571",  # book
        "Q4830453",  # business
        "Q476028",  # association football club
        "Q215380",  # musical group
        "Q11446",  # ship — a vessel is LOCAL, never a pin
        "Q2235308",  # steamship
    }
)


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    """One thing a source thinks a name might mean.

    Attributes:
        qid: ``"Q1156"`` for Wikidata, ``"osm:relation/2088990"`` for Nominatim.
            Prefixed so an OSM identifier can never masquerade as a Wikidata entity —
            the two carry different licences, and that distinction has to survive into
            the attribution.
        label: The modern English label, e.g. ``"Mumbai"``.
        matched_alias: The string that actually matched, e.g. ``"Bombay"``. This is what
            makes the 1872→modern change legible: the alias is the old name and the
            label is the new one, out of the same entity rather than a second lookup.
        entity_type: The ``P31`` label, e.g. ``"megacity"``.
        entity_type_qid: That class's own QID, which is what :func:`is_place` tests.
        sitelinks: A prominence signal, and the last term in the ranking.
        source: ``"wikidata"`` or ``"nominatim"``.
    """

    qid: str
    label: str
    matched_alias: str = ""
    lat: float = 0.0
    lon: float = 0.0
    description: str | None = None
    entity_type: str | None = None
    entity_type_qid: str | None = None
    country: str | None = None
    country_qid: str | None = None
    population: int | None = None
    sitelinks: int = 0
    source: str = "wikidata"

    @property
    def point(self) -> tuple[float, float]:
        """The coordinate pair, for distance work.

        Returns:
            ``(lat, lon)``.
        """
        return (self.lat, self.lon)


@dataclass(frozen=True, slots=True)
class Resolution:
    """One place name, answered, with the reason and the doubt recorded beside it.

    Attributes:
        modern_name: The entity's present-day label, or ``None`` when nothing resolved.
        name_changed: Whether the 1872 spelling and the modern label differ.
        confidence: How sure, discounted by how close the runner-up came.
        n_candidates: How many the source offered. More than one means the popup shows
            runners-up, which is what makes a correction a ten-second decision.
        source: ``wikidata`` | ``nominatim`` | ``curated`` | ``local`` | ``none``.
        why: One line saying how this was arrived at, in the house register.
    """

    key: str
    name_in_text: str
    modern_name: str | None = None
    name_changed: bool = False
    qid: str | None = None
    lat: float | None = None
    lon: float | None = None
    entity_type: str | None = None
    country: str | None = None
    confidence: float = 0.0
    n_candidates: int = 0
    source: str = "none"
    why: str = ""
    candidates: tuple[PlaceCandidate, ...] = field(default=())

    @property
    def resolved(self) -> bool:
        """Whether this name got coordinates.

        Returns:
            True when there is a point to plot.

        Examples:
            >>> Resolution("kholby", "Kholby").resolved
            False
            >>> Resolution("suez", "Suez", lat=29.97, lon=32.53).resolved
            True
        """
        return self.lat is not None and self.lon is not None


def sparql_string(value: str) -> str:
    r"""Escape a Python string as a SPARQL string literal, delimiters included.

    Not cosmetic. The extractions genuinely carry ``'"Mongolia"'`` with the quotation
    marks inside the name, and interpolating that into a query unescaped is an injection
    bug rather than merely a parse error.

    Args:
        value: Any string.

    Returns:
        The value as a quoted SPARQL literal.

    Contract:
        - The result starts and ends with ``"``.
        - Contains no unescaped quote, backslash, newline or tab.
        - Total: never raises.

    Examples:
        >>> sparql_string("Bombay")
        '"Bombay"'
        >>> sparql_string('the "Mongolia"')
        '"the \\"Mongolia\\""'
        >>> sparql_string("a\nb")
        '"a\\nb"'
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def qid_from_uri(uri: str) -> str:
    """The bare identifier from a Wikidata entity URI.

    Args:
        uri: e.g. ``"http://www.wikidata.org/entity/Q1156"``.

    Returns:
        e.g. ``"Q1156"``. Returns the input unchanged if it is already bare.

    Examples:
        >>> qid_from_uri("http://www.wikidata.org/entity/Q1156")
        'Q1156'
        >>> qid_from_uri("Q1156")
        'Q1156'
    """
    return uri.rsplit("/", 1)[-1]


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two ``(lat, lon)`` pairs, in kilometres.

    Args:
        a: The first point.
        b: The second.

    Returns:
        The distance.

    Contract:
        - Symmetric, and zero for identical points.
        - Never exceeds half the Earth's circumference, about 20,038 km.
        - Never raises for any finite pair.

    Examples:
        >>> round(haversine_km((51.5072, -0.1276), (19.0761, 72.8775)))
        7192
        >>> haversine_km((0.0, 0.0), (0.0, 0.0))
        0.0
    """
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    inner = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, inner)))


def nearest_km(
    point: tuple[float, float], anchors: Sequence[tuple[float, float]]
) -> float | None:
    """How far a point is from the closest of several anchors.

    Args:
        point: The candidate's coordinate.
        anchors: Known points on the route.

    Returns:
        The smallest distance, or ``None`` when there are no anchors.

    Examples:
        >>> nearest_km((51.5, 0.0), [(19.0, 72.8), (51.4, -0.1)]) < 20
        True
        >>> nearest_km((51.5, 0.0), []) is None
        True
    """
    if not anchors:
        return None
    return min(haversine_km(point, anchor) for anchor in anchors)


def is_place(candidate: PlaceCandidate) -> bool:
    """Whether a candidate is somewhere rather than something.

    Args:
        candidate: The candidate.

    Returns:
        False for a person, a ship, a film, a football club.

    Examples:
        >>> is_place(PlaceCandidate("Q1156", "Mumbai", entity_type_qid="Q1637706"))
        True
        >>> is_place(PlaceCandidate("Q42", "Henrietta", entity_type_qid="Q5"))
        False
    """
    return candidate.entity_type_qid not in NOT_A_PLACE_QIDS


def name_changed(name_in_text: str, modern_name: str | None) -> bool:
    """Whether the 1872 spelling and the modern label are different names.

    A trailing parenthetical is dropped first: Wikidata's ``"Suez (city)"`` is its own
    disambiguation housekeeping, not a rename, and reporting it as one would put a false
    "renamed" badge on the dashboard.

    Args:
        name_in_text: The name as the 1872 text prints it.
        modern_name: The entity's present-day label.

    Returns:
        True when they are genuinely different names.

    Contract:
        - False whenever ``modern_name`` is missing.
        - Insensitive to case and typography.
        - Never raises.

    Examples:
        >>> name_changed("Bombay", "Mumbai")
        True
        >>> name_changed("Yokohama", "Yokohama")
        False
        >>> name_changed("Suez", "Suez (city)")
        False
        >>> name_changed("Kholby", None)
        False
    """
    if not modern_name:
        return False
    left = match_key(name_in_text)
    right = match_key(normalize_quote(modern_name).split(" (")[0])
    return bool(left) and bool(right) and left != right


def place_search_query(name: str, *, limit: int = 10, language: str = "en") -> str:
    r"""Search Wikidata by label or alias, keeping only things with coordinates.

    Search and fetch are fused through ``wikibase:mwapi``, one round-trip per name
    rather than two. That halves ~700 requests to ~350, and request count is the
    etiquette budget here.

    Three decisions are load-bearing:

    ``wdt:P625`` is **required, not OPTIONAL**. An entity without a coordinate is not
    something this project can plot, so gating in the query costs nothing and removes a
    whole class of candidate before it is ever ranked — the person called Henrietta, the
    component called a battery.

    ``?alias`` is selected. It is the string that actually matched, and ``Bombay`` lives
    as an alias on ``Q1156`` — so the 1872→modern change comes out of a single entity.

    The label is bound with an explicit ``FILTER(LANG(?enLabel) = "en")`` rather than
    through the label service's fallback chain. A Bengali or Hungarian label reaching
    ``modern_name`` would make :func:`name_changed` report a rename when all that
    happened is that nobody wrote an English label.

    Args:
        name: The place as the 1872 text spells it.
        limit: How many candidates to ask the search API for.
        language: The label language. Not a knob to turn casually; see above.

    Returns:
        A SPARQL query string.

    Contract:
        - The name is escaped, so a quoted vessel name cannot break the query.
        - Requires a coordinate rather than making it optional.

    Examples:
        >>> query = place_search_query("Bombay")
        >>> 'mwapi:search "Bombay"' in query
        True
        >>> "?item wdt:P625 ?coord ." in query
        True
        >>> 'mwapi:search "the \\"Mongolia\\""' in place_search_query('the "Mongolia"')
        True
    """
    return f"""SELECT ?item ?enLabel ?alias ?description ?lat ?lon
       ?type ?typeLabel ?country ?countryLabel ?population ?sitelinks
WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam mwapi:search {sparql_string(name)} .
    bd:serviceParam mwapi:language "{language}" .
    bd:serviceParam mwapi:limit "{limit}" .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P625 ?coord .
  BIND(geof:latitude(?coord) AS ?lat)
  BIND(geof:longitude(?coord) AS ?lon)
  ?item rdfs:label ?enLabel . FILTER(LANG(?enLabel) = "{language}")
  OPTIONAL {{ ?item skos:altLabel ?alias . FILTER(LANG(?alias) = "{language}") }}
  OPTIONAL {{ ?item schema:description ?description .
             FILTER(LANG(?description) = "{language}") }}
  OPTIONAL {{ ?item wdt:P31 ?type . }}
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{ ?item wdt:P1082 ?population . }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sitelinks . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{language}" . }}
}}
LIMIT 200
"""


def parse_binding(binding: Mapping[str, Mapping[str, str]]) -> PlaceCandidate:
    """Turn one SPARQL result row into a candidate.

    Pure, so the whole parse is testable from a literal.

    Args:
        binding: One entry of ``results.bindings``.

    Returns:
        The candidate.

    Examples:
        >>> row = {
        ...     "item": {"value": "http://www.wikidata.org/entity/Q1156"},
        ...     "enLabel": {"value": "Mumbai"},
        ...     "alias": {"value": "Bombay"},
        ...     "lat": {"value": "19.0761"},
        ...     "lon": {"value": "72.8775"},
        ... }
        >>> parse_binding(row).qid, parse_binding(row).matched_alias
        ('Q1156', 'Bombay')
    """

    def value(key: str) -> str | None:
        entry = binding.get(key)
        return entry.get("value") if entry else None

    def number(key: str) -> int | None:
        raw = value(key)
        try:
            return int(float(raw)) if raw is not None else None
        except ValueError:
            return None

    return PlaceCandidate(
        qid=qid_from_uri(value("item") or ""),
        label=value("enLabel") or "",
        matched_alias=value("alias") or "",
        lat=float(value("lat") or 0.0),
        lon=float(value("lon") or 0.0),
        description=value("description"),
        entity_type=value("typeLabel"),
        entity_type_qid=qid_from_uri(value("type") or "") or None,
        country=value("countryLabel"),
        country_qid=qid_from_uri(value("country") or "") or None,
        population=number("population"),
        sitelinks=number("sitelinks") or 0,
        source="wikidata",
    )


def merge_candidates(candidates: Iterable[PlaceCandidate]) -> list[PlaceCandidate]:
    """Collapse the row fan-out that multi-valued properties produce.

    One entity with three aliases and two ``P31`` values comes back as six rows. They
    are one candidate, and the aliases have to be kept together because the *best* of
    them is what the name score is measured against.

    Args:
        candidates: Rows as parsed.

    Returns:
        One entry per entity, in first-seen order, each carrying every alias seen for it
        joined by ``" | "``.

    Contract:
        - The result has one entry per distinct ``qid``.
        - No alias is lost.
        - Order is stable.

    Examples:
        >>> rows = [
        ...     PlaceCandidate("Q1156", "Mumbai", "Bombay"),
        ...     PlaceCandidate("Q1156", "Mumbai", "Bombai"),
        ... ]
        >>> merged = merge_candidates(rows)
        >>> len(merged), merged[0].matched_alias
        (1, 'Bombay | Bombai')
    """
    out: dict[str, PlaceCandidate] = {}
    aliases: dict[str, list[str]] = {}
    for candidate in candidates:
        seen = out.get(candidate.qid)
        names = aliases.setdefault(candidate.qid, [])
        if candidate.matched_alias and candidate.matched_alias not in names:
            names.append(candidate.matched_alias)
        if seen is None:
            out[candidate.qid] = candidate
        elif seen.entity_type_qid is None and candidate.entity_type_qid:
            out[candidate.qid] = replace(candidate, matched_alias=seen.matched_alias)
    return [
        replace(candidate, matched_alias=" | ".join(aliases[qid]))
        for qid, candidate in out.items()
    ]


def _name_score(candidate: PlaceCandidate, name_in_text: str) -> float:
    """How well a candidate's names match the 1872 spelling, in buckets."""
    from rapidfuzz import fuzz

    wanted = match_key(name_in_text)
    spellings = [candidate.label, *candidate.matched_alias.split(" | ")]
    keys = [match_key(spelling) for spelling in spellings if spelling]
    if any(key == wanted for key in keys):
        return 1.0
    best = max((fuzz.ratio(wanted, key) for key in keys), default=0.0)
    if best >= 90:
        return 0.8
    if best >= 75:
        return 0.5
    return 0.2


def score_candidate(
    candidate: PlaceCandidate,
    name_in_text: str,
    near: Sequence[tuple[float, float]] = (),
) -> tuple[float, float, float, float]:
    """Rank one candidate. Higher sorts first.

    A tuple, deliberately, so the priorities are a fact of the type rather than of a
    weighting somebody will retune. See the module docstring for what each term is for
    and why they are in this order.

    Args:
        candidate: The candidate.
        name_in_text: The 1872 spelling.
        near: Known route coordinates to measure proximity against.

    Returns:
        ``(is_place, name, route, prominence)``, each in ``[0.0, 1.0]``.

    Contract:
        - Every element is finite and in ``[0.0, 1.0]``.
        - Pure and deterministic; the order of ``near`` does not affect the result.

    Examples:
        >>> mumbai = PlaceCandidate("Q1156", "Mumbai", "Bombay", 19.07, 72.87)
        >>> score_candidate(mumbai, "Bombay")[:2]
        (1.0, 1.0)
        >>> person = PlaceCandidate("Q42", "Henrietta", entity_type_qid="Q5")
        >>> score_candidate(person, "Henrietta")[0]
        0.0
    """
    gate = 1.0 if is_place(candidate) else 0.0
    name = _name_score(candidate, name_in_text)

    distance = nearest_km(candidate.point, near)
    route = (
        PROXIMITY_HALF_LIFE_KM / (PROXIMITY_HALF_LIFE_KM + distance)
        if distance is not None
        else 0.0
    )
    prominence = min(1.0, math.log10(1 + max(0, candidate.sitelinks)) / 2.5)
    return (gate, name, route, prominence)


def best_candidate(
    candidates: Sequence[PlaceCandidate],
    name_in_text: str,
    *,
    near: Sequence[tuple[float, float]] = (),
) -> tuple[PlaceCandidate | None, float]:
    """Pick the winner, and say how sure it is.

    Confidence is the winner's weighted score discounted by how close the runner-up
    came, so a photo finish is reported as uncertain even when both candidates score
    well.

    The name term carries most of the weight because route proximity is a
    *discriminator* between candidates, not evidence about any one of them: a
    correctly-identified place genuinely far from the route should not read as
    doubtful. Proximity earns its keep in the margin, where it separates two
    candidates that share a name.

    Note the bootstrap. The nine itinerary nodes are resolved with no anchors at all —
    there are no coordinates yet — so for them the margin comes from prominence alone,
    and nine pins get eyeballed before anything else is run. Everything after that is
    scored against a route that exists.

    Args:
        candidates: The candidates.
        name_in_text: The 1872 spelling.
        near: Known route coordinates.

    Returns:
        The winner and its confidence, or ``(None, 0.0)``.

    Contract:
        - Returns a member of ``candidates``, never a synthesised one.
        - ``(None, 0.0)`` for an empty list, and confidence ``0.0`` when the winner
          fails
          the is-a-place gate.
        - Confidence is in ``[0.0, 1.0]``, rounded to two places.
        - Deterministic: ties break on ``qid``, so two runs agree and the committed
          cache
          stays reproducible.

    Examples:
        >>> mumbai = PlaceCandidate("Q1156", "Mumbai", "Bombay", 19.07, 72.87,
        ...                         sitelinks=200)
        >>> beach = PlaceCandidate("Q1361", "Bombay Beach", "", 33.35, -115.73)
        >>> winner, confidence = best_candidate([beach, mumbai], "Bombay")
        >>> winner.qid, confidence > 0.5
        ('Q1156', True)
    """
    if not candidates:
        return None, 0.0

    ranked = sorted(
        candidates,
        key=lambda c: (*score_candidate(c, name_in_text, near), c.qid),
        reverse=True,
    )
    winner = ranked[0]
    gate, name, route, prominence = score_candidate(winner, name_in_text, near)
    if gate == 0.0:
        return winner, 0.0

    base = 0.70 * name + 0.20 * route + 0.10 * prominence
    if len(ranked) > 1:
        _, name2, route2, _ = score_candidate(ranked[1], name_in_text, near)
        margin = (name - name2) + 0.5 * (route - route2)
    else:
        margin = 1.0
    confidence = base * (0.55 + 0.45 * min(1.0, 4 * max(0.0, margin)))
    return winner, round(min(1.0, max(0.0, confidence)), 2)


def resolve_place(
    key: str,
    name_in_text: str,
    candidates: Sequence[PlaceCandidate],
    *,
    near: Sequence[tuple[float, float]] = (),
    modern_hint: str | None = None,
) -> Resolution:
    """Turn a candidate list into one answer, with the reason recorded beside it.

    Pure by design — it takes the candidates rather than fetching them — so the ranking,
    the confidence and the 1872→modern comparison are all testable with no network.

    Args:
        key: The place key, as used by the review table.
        name_in_text: The 1872 spelling.
        candidates: What the source offered.
        near: Known route coordinates.
        modern_hint: A curated modern spelling from ``route_places.json``, when the 1872
            transliteration is too far from it for any search to bridge. Recorded in
            ``why`` when it fired, so a resolution that only worked because a human
            typed a hint says so.

    Returns:
        The resolution.

    Contract:
        - Never raises.
        - ``source`` is ``"none"`` and ``resolved`` is False when nothing won.
        - ``why`` is never empty.

    Examples:
        >>> mumbai = PlaceCandidate("Q1156", "Mumbai", "Bombay", 19.07, 72.87,
        ...                         entity_type="megacity", country="India")
        >>> answer = resolve_place("bombay", "Bombay", [mumbai])
        >>> answer.modern_name, answer.name_changed, answer.source
        ('Mumbai', True, 'wikidata')
        >>> resolve_place("kholby", "Kholby", []).why
        'no candidate with coordinates under this spelling'
    """
    if not candidates:
        return Resolution(
            key=key,
            name_in_text=name_in_text,
            why="no candidate with coordinates under this spelling",
        )

    searched = modern_hint or name_in_text
    winner, confidence = best_candidate(candidates, searched, near=near)
    if winner is None or confidence == 0.0:
        return Resolution(
            key=key,
            name_in_text=name_in_text,
            n_candidates=len(candidates),
            candidates=tuple(candidates),
            why=(
                f"{len(candidates)} candidates, none of them a place — "
                "probably a person, a ship or a work"
            ),
        )

    distance = nearest_km(winner.point, near)
    parts = [f"{winner.source} {winner.qid} '{winner.label}'"]
    if modern_hint:
        parts.append(f"found via the curated spelling '{modern_hint}'")
    if distance is not None:
        parts.append(f"{distance:,.0f} km from the route")
    if len(candidates) > 1:
        parts.append(f"{len(candidates)} candidates")
    if confidence < 0.7:
        parts.append("check this one")

    return Resolution(
        key=key,
        name_in_text=name_in_text,
        modern_name=winner.label or None,
        name_changed=name_changed(name_in_text, winner.label),
        qid=winner.qid,
        lat=winner.lat,
        lon=winner.lon,
        entity_type=winner.entity_type,
        country=winner.country,
        confidence=confidence,
        n_candidates=len(candidates),
        source=winner.source,
        why=", ".join(parts),
        candidates=tuple(candidates),
    )


@dataclass(slots=True)
class GazetteerCache:
    """What each endpoint said, keyed so a run is reproducible offline.

    The cache holds **what the endpoint said, never what we concluded**. The ranking
    weights, the route anchors and the confidence floor are deliberately not part of
    the key, so re-ranking after the anchors improve is free and offline — which it
    only is if the anchors are not in the key.

    Attributes:
        path: Where it lives.
        entries: Keyed by :meth:`key`.
    """

    path: Path
    entries: dict[str, dict] = field(default_factory=dict)

    @staticmethod
    def key(source: str, name: str, operation: str = "search") -> str:
        """The cache key for one lookup.

        Uses the same :func:`~verne80.normalize.place_key` the review table uses, so a
        cache entry joins to a CSV row by eye and ``Mongolia`` / ``"Mongolia"`` /
        ``“Mongolia”`` are one entry rather than three.

        Args:
            source: ``"wikidata"`` or ``"nominatim"``.
            name: The place name.
            operation: What was asked.

        Returns:
            The key.

        Examples:
            >>> GazetteerCache.key("wikidata", "“Mongolia”")
            'wikidata:search:v1:mongolia'
        """
        return f"{source}:{operation}:v{QUERY_VERSION}:{place_key(name)}"

    @classmethod
    def load(cls, path: Path) -> GazetteerCache:
        """Read the cache, or start an empty one.

        Args:
            path: The cache file.

        Returns:
            The cache. A missing file is not an error — the first run has nothing to
            read.
        """
        if not path.exists():
            return cls(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(path, dict(data.get("entries", {})))

    def get(self, key: str) -> list[PlaceCandidate] | None:
        """The candidates cached under a key.

        Args:
            key: From :meth:`key`.

        Returns:
            The candidates, or ``None`` when the key is absent. An entry that cached an
            empty list returns ``[]``, which is a real answer — the endpoint had
            nothing —
            and must not be confused with a cache miss.
        """
        entry = self.entries.get(key)
        if entry is None:
            return None
        return [PlaceCandidate(**row) for row in entry.get("candidates", [])]

    def put(
        self, key: str, query: str, candidates: Sequence[PlaceCandidate], endpoint: str
    ) -> None:
        """Record what an endpoint said.

        Args:
            key: From :meth:`key`.
            query: The name that was searched for.
            candidates: What came back.
            endpoint: Which service answered.
        """
        self.entries[key] = {
            "query": query,
            "source": key.split(":", 1)[0],
            "endpoint": endpoint,
            "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "candidates": [
                {
                    field_name: getattr(candidate, field_name)
                    for field_name in PlaceCandidate.__slots__
                }
                for candidate in candidates
            ],
        }

    def save(self) -> None:
        """Write the cache, entries sorted so the diff is readable."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_by": "scripts/07_gazetteer.py",
            "schema_version": QUERY_VERSION,
            "attribution": {
                "wikidata": "Wikidata — CC0 1.0 — https://www.wikidata.org/",
                "nominatim": (
                    "© OpenStreetMap contributors — ODbL — https://osm.org/copyright"
                ),
            },
            "entries": {key: self.entries[key] for key in sorted(self.entries)},
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def _worth_retrying(error: BaseException) -> bool:
    """Whether an error is one the endpoint might answer differently next time.

    Retrying every ``HTTPError`` would try a 400 four times over half a minute, which
    cannot succeed and is rude to a free public service. Only rate limiting, transient
    server faults and transport failures earn another attempt.

    Args:
        error: What was raised.

    Returns:
        True when trying again might help.
    """
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in _RETRY_STATUS
    return isinstance(error, httpx.TransportError)


class OfflineError(RuntimeError):
    """Raised when an answer is wanted, the cache does not have it, and we may not ask.

    Attributes:
        args: The key that was missing, so the message names what to fetch.
    """


@dataclass(slots=True)
class RateLimiter:
    """One request per interval, because both endpoints ask for that in writing.

    Wikidata's query service and Nominatim both publish usage policies with a one-per-
    second ceiling for unauthenticated clients. Three hundred and fifty lookups at that
    rate is six minutes, which is a coffee — and the cache means it happens once.

    Attributes:
        interval: Seconds between requests.
    """

    interval: float = 1.1
    _last: float = 0.0

    def wait(self) -> None:
        """Sleep for whatever is left of the interval."""
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()


@dataclass(slots=True)
class GazetteerClient:
    """Ask Wikidata for candidates, through the cache.

    The only part of this module that touches the network, and it is a thin shell: it
    finds candidates and hands them to :func:`resolve_place`, which decides. Everything
    interesting happens on the pure side.

    ``offline=True`` never opens a socket. A key the cache does not have raises
    :class:`OfflineError` rather than silently returning nothing, so an offline run
    missing data says which key it wants rather than quietly producing a thinner map.

    Attributes:
        cache: Where answers are kept.
        offline: Whether a cache miss may go to the network.
        limiter: The rate limiter, shared across every endpoint.
    """

    cache: GazetteerCache
    offline: bool = False
    limiter: RateLimiter = field(default_factory=RateLimiter)
    transport: object | None = None
    _fetched: int = 0

    @property
    def fetched(self) -> int:
        """How many requests this client has actually made.

        Returns:
            The count, which the run log prints so the etiquette budget is visible.
        """
        return self._fetched

    def lookup(self, name: str) -> list[PlaceCandidate]:
        """Candidates for one place name, from the cache or from Wikidata.

        Args:
            name: The place as the 1872 text spells it, or a curated modern spelling.

        Returns:
            The candidates, possibly empty — an endpoint that had nothing is an answer.

        Raises:
            OfflineError: If the cache lacks the key and the network is not allowed.

        Contract:
            - A cached key never goes to the network, including one that cached an
              empty list.
            - Never raises for a network failure: a failed fetch is reported as no
              candidates and is not cached, so a later run retries it.
        """
        key = GazetteerCache.key("wikidata", name)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.offline:
            raise OfflineError(
                f"{key} is not cached and --offline was given; "
                "re-run without it to fetch this one"
            )

        candidates = self._fetch(name)
        self.cache.put(key, name, candidates, WDQS_ENDPOINT)
        return candidates

    def _fetch(self, name: str) -> list[PlaceCandidate]:
        """One SPARQL round-trip, rate-limited and retried where that could help."""
        self.limiter.wait()
        self._fetched += 1
        try:
            response = self._get(place_search_query(name))
        except httpx.HTTPError:
            return []
        bindings = response.get("results", {}).get("bindings", [])
        return merge_candidates(parse_binding(row) for row in bindings)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, max=30),
        retry=retry_if_exception(_worth_retrying),
        reraise=True,
    )
    def _get(self, query: str) -> dict:
        """Send one query, honouring Retry-After when asked to slow down."""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
        }
        kwargs = {"transport": self.transport} if self.transport is not None else {}
        with httpx.Client(timeout=60.0, headers=headers, **kwargs) as client:
            response = client.get(
                WDQS_ENDPOINT, params={"query": query, "format": "json"}
            )
            if response.status_code in _RETRY_STATUS:
                after = response.headers.get("Retry-After")
                if after and after.isdigit():
                    time.sleep(min(int(after), 60))
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
