r"""Who is in a chapter, and what to call them.

The extraction records a person as the chapter printed them, which is right and is also
why a reader stepping through the book watches Phileas Fogg become Mr. Fogg and back
again. Chapters 20 and 21 name the pilot of the *Tankadere* John Bunsby; chapter 24
names him John Busby, because that is what Gutenberg #103 says there. The book is
inconsistent and the extraction is faithful to it. Tidying that away in the data would
destroy the evidence, so the reconciliation happens here, at the point of display, and
**both spellings survive into the payload**.

Two ideas, and keeping them apart is the whole design.

**A person is somebody the book names.** Curated in ``people.json``, but only where the
book prints more than one spelling — 13 of the 159 names on stage. The other 146 pass
through untouched, because a curated entry that says "call Aouda 'Aouda'" is an
assertion with nothing behind it and one more thing to keep in step.

**A role is somebody the book identifies only by what they are.** An engineer, a
conductor, the cabman. These are never folded across chapters: the engineer of chapter
26 is not the engineer of chapter 34, there are nine of them and they are nine men.
Chapter 26 settles it by example, having Fix *and* a detective on stage at once.

Telling the two apart is a rule rather than a list, because this translation
capitalises a proper name: a name that begins lower case, once a leading article is
dropped, is a role. That is right for 146 of 159 names, and ``people.json``'s ``roles``
is the list of the thirteen it is wrong about — capitalised because they carry a proper
adjective or name a people, generic all the same.

One field is deliberately not used. ``Person.role`` in the extraction is free prose:
221 distinct values across 248 entries, inconsistently capitalised, split between
"traveling" and "travelling". It is not a facet, it cannot be filtered on, and shown as
a label it would read as a caption somebody wrote once. The evidence quotes in
``data/extractions/`` are the place to look instead.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verne80.normalize import match_key

__all__ = [
    "Cast",
    "Folded",
    "PEOPLE_JSON",
    "check_cast",
    "load_cast",
    "looks_like_a_role",
]

PEOPLE_JSON = Path(__file__).with_name("people.json")

# One decoded entry from people.json. `Any` is the honest annotation: the file is
# hand-written project data whose shape check_cast enforces at run time, rather than a
# structure a checker could promise anything about.
Entry = Mapping[str, Any]

_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Folded:
    """One printed name, resolved for display.

    Attributes:
        key: A stable identifier — the curated ``person`` where there is one, otherwise
            the name's own :func:`~verne80.normalize.match_key`. Two chapters that print
            a person differently share a key; two chapters that name an engineer do not.
        display: What to show. Always one of the printed spellings, never a name the
        book
            does not use.
        name_in_text: The spelling this chapter used, exactly. A quotation.
        kind: ``"person"`` or ``"role"``.
    """

    key: str
    display: str
    name_in_text: str
    kind: str


def looks_like_a_role(name: str) -> bool:
    """Whether a printed name identifies somebody by what they are.

    The rule is orthographic: this translation capitalises a proper name, so a name that
    begins lower case is a description. A leading article is dropped first, so "the
    cabman" is read as "cabman" and "the Reverend Samuel Wilson" as a person.

    Right 146 times out of 159 on the real data. The exceptions run one way only —
    capitalised names that are still generic, like "Sioux" or "British consul" — and
    :func:`load_cast` takes those from ``people.json`` rather than guessing at them.

    Args:
        name: A name as printed in the chapter.

    Returns:
        True when the name reads as a role.

    Examples:
        >>> looks_like_a_role("engineer"), looks_like_a_role("the cabman")
        (True, True)
        >>> looks_like_a_role("Phileas Fogg"), looks_like_a_role("the Barings")
        (False, False)

        Empty input is not a person:

        >>> looks_like_a_role("")
        True
    """
    stripped = _ARTICLE.sub("", name.strip())
    return not stripped[:1].isupper()


class Cast:
    """The roster: curated spellings, known role-nouns, and a rule for everything else.

    Attributes:
        people: Curated entries, keyed by their ``person`` identifier.
        roles: Names that look like proper nouns and are not, under ``match_key``.
    """

    __slots__ = ("_by_alias", "_roles", "people", "roles")

    def __init__(self, people: Iterable[Entry], roles: Iterable[Entry]) -> None:
        self.people: dict[str, Entry] = {
            str(entry["person"]): entry for entry in people
        }
        self.roles: list[Entry] = list(roles)
        self._roles = {match_key(str(entry["name"])) for entry in self.roles}
        self._by_alias: dict[str, str] = {}
        for identifier, entry in self.people.items():
            for alias in entry.get("aliases", ()):
                self._by_alias[match_key(str(alias))] = identifier

    def is_role(self, name: str) -> bool:
        """Whether this printed name is one of the listed generic exceptions.

        Args:
            name: A name as printed.

        Returns:
            True when ``people.json`` lists it under ``roles``. The orthographic rule in
            :func:`looks_like_a_role` is separate and catches the other 146.

        Examples:
            >>> load_cast().is_role("Sioux"), load_cast().is_role("Phileas Fogg")
            (True, False)
        """
        return match_key(name) in self._roles

    def fold(self, name: str) -> Folded:
        """Resolve one printed name.

        Args:
            name: A name as the chapter printed it.

        Returns:
            The folded form. The printed spelling always survives in
            :attr:`Folded.name_in_text`.

        Contract:
            - ``fold(name).name_in_text == name``, always and for any input. This is the
              property the whole module exists to keep.
            - A role never shares a key with a person, and two roles printed the same
              way in different chapters are not thereby the same person — the caller
              keeps them apart by not merging across chapters.
            - Never raises.

        Examples:
            A curated fold, with the quotation intact:

            >>> cast = load_cast()
            >>> fogg = cast.fold("Mr. Fogg")
            >>> fogg.key, fogg.display, fogg.name_in_text, fogg.kind
            ('fogg', 'Phileas Fogg', 'Mr. Fogg', 'person')

            The book's own inconsistency, reconciled without being erased:

            >>> cast.fold("John Busby").display
            'John Bunsby'

            An uncurated name passes through:

            >>> aouda = cast.fold("Aouda")
            >>> aouda.key, aouda.display, aouda.kind
            ('aouda', 'Aouda', 'person')

            And a role stays a role:

            >>> cast.fold("engineer").kind, cast.fold("Sioux").kind
            ('role', 'role')
        """
        key = match_key(name)
        identifier = self._by_alias.get(key)
        if identifier is not None:
            entry = self.people[identifier]
            return Folded(identifier, str(entry["display"]), name, "person")
        kind = "role" if key in self._roles or looks_like_a_role(name) else "person"
        return Folded(key, name, name, kind)


def load_cast(path: Path = PEOPLE_JSON) -> Cast:
    """Read the roster.

    Args:
        path: The curation file.

    Returns:
        The cast.

    Raises:
        FileNotFoundError: If the file is missing. It is committed project data, and a
            silent empty roster would rename half the book's characters back.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return Cast(data.get("people", ()), data.get("roles", ()))


def check_cast(cast: Cast | None = None) -> list[str]:
    """Everything wrong with the roster, phrased so each line names its own fix.

    Args:
        cast: The roster. Loaded from :data:`PEOPLE_JSON` when omitted.

    Returns:
        The problems, sorted. Empty means the roster is sound.

    Examples:
        >>> check_cast()
        []

        A display name the book never prints:

        >>> bad = Cast([{"person": "x", "display": "Zed", "aliases": ["Ex"]}], [])
        >>> check_cast(bad)
        ["'x' displays as 'Zed', which is not one of its own printed spellings"]
    """
    roster = load_cast() if cast is None else cast
    problems: list[str] = []
    owner: dict[str, str] = {}

    for identifier, entry in roster.people.items():
        aliases = [str(alias) for alias in entry.get("aliases", ())]
        if not aliases:
            problems.append(f"{identifier!r} has no printed spelling to match on")
        if str(entry.get("display", "")) not in aliases:
            problems.append(
                f"{identifier!r} displays as {str(entry.get('display', ''))!r}, which "
                "is not one of its own printed spellings"
            )
        for alias in aliases:
            key = match_key(alias)
            if key in owner and owner[key] != identifier:
                problems.append(
                    f"{alias!r} is claimed by both {owner[key]!r} and {identifier!r}"
                )
            owner[key] = identifier
            if roster.is_role(alias):
                problems.append(
                    f"{alias!r} is both a person's spelling and a role — "
                    "one of the two entries is wrong"
                )
    return sorted(problems)
