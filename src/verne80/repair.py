r"""Recover extraction files a language model wrote slightly wrong.

Thirty-four of the thirty-seven chapters came back as valid JSON matching the schema.
The other three did not, in two different ways, and both are worth naming because they
are what this module exists for:

**An unescaped quotation mark inside a string.** Chapter 21's title is ``IN WHICH THE
MASTER OF THE "TANKADERE" RUNS GREAT RISK…`` and chapter 12 has an evidence quote
containing ``"What's the matter?"``. The model wrote the inner marks without escaping
them, so the document stops being JSON partway through a string.

**A field the schema forbids.** Chapter 18 puts ``"role": "mention"`` on every one of
its ``places_mentioned`` entries. ``extra="forbid"`` exists precisely so an invented
field is loud rather than silent, and it did its job.

Two rules keep this from becoming a way to launder bad data.

**Repair is a tool, not a tier in the loader.** :mod:`verne80.extractions` stays
strict: nothing is repaired invisibly on the way in. This rewrites the file once, and
because the extractions are committed, ``git diff`` then shows exactly what changed.
The alternative — repairing silently on every read — produces precisely the
plausible-but-unchecked extraction the loader's docstring warns about.

**Nothing is dropped without being named.** :func:`drop_forbidden_fields` does not
walk the schema deciding what looks unnecessary. It asks pydantic to validate, takes
only the errors of type ``extra_forbidden``, deletes exactly those paths, and returns
a list of them. "Remove what pydantic explicitly rejected, and say which" is safe on
hand-verified data; "strip anything I do not recognise" is not.

The real hazard with any repair library is that it truncates a string at the first
stray mark rather than escaping it, silently losing the rest. That is checked rather
than trusted: chapter 12's broken string is an ``evidence`` field, so the evidence
validator greps it back against the chapter, and chapter 21's is the ``title``, which
:func:`~verne80.schema.check_extraction` compares against ``index.json``. Both repairs
have an independent witness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json_repair
from pydantic import ValidationError

from verne80.extractions import parse_extraction_json
from verne80.schema import ChapterExtraction

__all__ = [
    "RepairResult",
    "drop_forbidden_fields",
    "render_json",
    "repair_file",
    "sniff_indent",
    "repair_text",
]

# Dropping a field can expose another the first pass could not reach, but a document
# that needs many rounds is not a near miss — it is a different document.
_MAX_DROP_ROUNDS = 5


@dataclass(frozen=True, slots=True)
class RepairResult:
    """What one file needed, and what it looks like afterwards.

    Attributes:
        path: The file.
        syntax_repaired: Whether the document had to go through the repair library to
            parse at all.
        dropped_fields: Paths of the fields pydantic rejected and this removed, e.g.
            ``("places_mentioned[0].role",)``. Empty when nothing was dropped.
        problem: What is still wrong, if the file cannot be recovered.
        text: The repaired document, ready to write. Empty when unrecoverable.
    """

    path: Path
    syntax_repaired: bool = False
    dropped_fields: tuple[str, ...] = ()
    problem: str | None = None
    text: str = ""

    @property
    def changed(self) -> bool:
        """Whether writing this back would alter the file.

        Returns:
            True when the syntax needed repairing or a field was dropped.

        Examples:
            >>> RepairResult(Path("x.json")).changed
            False
            >>> RepairResult(Path("x.json"), syntax_repaired=True).changed
            True
        """
        return bool(self.syntax_repaired or self.dropped_fields)


def repair_text(text: str) -> tuple[dict[str, Any], bool]:
    """Parse a document, reaching for the repair library only if it will not parse.

    The strict tiers come first, so a file that is already valid is never handed to a
    repairer that might reformat it. Only a document that no strict tier can read is
    repaired.

    Args:
        text: The file contents.

    Returns:
        The parsed object, and whether repairing was needed.

    Raises:
        ValueError: If even the repair library cannot produce a JSON object.

    Contract:
        - A document the strict loader accepts is returned unchanged, with ``False``.
        - The result is always a ``dict``.
        - Idempotent: repairing a repaired document needs no second repair.

    Examples:
        >>> repair_text('{"chapter": 1}')
        ({'chapter': 1}, False)

        The real chapter-21 failure — an unescaped mark inside the title:

        >>> broken = '{"title": "THE MASTER OF THE "TANKADERE" RUNS A RISK"}'
        >>> data, repaired = repair_text(broken)
        >>> repaired
        True
        >>> data["title"]
        'THE MASTER OF THE "TANKADERE" RUNS A RISK'
    """
    try:
        return parse_extraction_json(text), False
    except ValueError:
        pass

    recovered = json_repair.loads(text)
    if not isinstance(recovered, dict):
        raise ValueError(
            f"repair produced {type(recovered).__name__}, not a JSON object — "
            "the document is too damaged to recover automatically"
        )
    if not recovered:
        raise ValueError(
            "repair produced an empty object — the document is too damaged to "
            "recover automatically"
        )
    return recovered, True


def drop_forbidden_fields(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove exactly the fields pydantic rejected, and name each one.

    Deliberately not a schema walk. Anything this deletes was explicitly reported as
    ``extra_forbidden`` by the model's own validation, so the set of removals is decided
    by the schema rather than guessed at — which is what makes it safe to run over
    hand-verified data.

    Args:
        data: A parsed extraction, possibly carrying fields the schema forbids.

    Returns:
        A copy without those fields, and their paths in the order removed.

    Contract:
        - Returns the input unchanged, with an empty list, when it already validates or
          fails for some reason other than a forbidden field.
        - Never removes a field the schema accepts.
        - Every removal appears in the returned list.

    Examples:
        The real chapter-18 failure — a ``role`` on a merely-mentioned place:

        >>> data = {
        ...     "chapter": 18,
        ...     "summary_hover": "They sail.",
        ...     "summary_detail": "They sail. Then they arrive.",
        ...     "places_mentioned": [
        ...         {
        ...             "name_in_text": "Yokohama",
        ...             "role": "mention",
        ...             "evidence": "the boat",
        ...         }
        ...     ],
        ... }
        >>> cleaned, dropped = drop_forbidden_fields(data)
        >>> dropped
        ['places_mentioned[0].role']
        >>> cleaned["places_mentioned"][0]
        {'name_in_text': 'Yokohama', 'evidence': 'the boat'}
    """
    working = json.loads(json.dumps(data))
    dropped: list[str] = []

    for _ in range(_MAX_DROP_ROUNDS):
        try:
            ChapterExtraction.model_validate(working)
        except ValidationError as error:
            paths = [
                item["loc"]
                for item in error.errors()
                if item["type"] == "extra_forbidden"
            ]
            if not paths:
                break
            for path in paths:
                if _delete_at(working, path):
                    dropped.append(_render_path(path))
        else:
            break

    return working, dropped


def _delete_at(data: Any, path: tuple[Any, ...]) -> bool:  # noqa: ANN401
    """Delete one location, addressed the way pydantic reports it.

    ``Any`` is honest here: the target is whatever nested shape the model emitted,
    and narrowing it would be a claim about the untrusted input this exists to walk.
    """
    target = data
    for step in path[:-1]:
        try:
            target = target[step]
        except (KeyError, IndexError, TypeError):
            return False
    last = path[-1]
    try:
        del target[last]
    except (KeyError, IndexError, TypeError):
        return False
    return True


def _render_path(path: tuple[Any, ...]) -> str:
    """Render a pydantic location the way the run log prints it."""
    out = ""
    for step in path:
        out += (
            f"[{step}]" if isinstance(step, int) else (f".{step}" if out else str(step))
        )
    return out


def sniff_indent(text: str, default: int = 2) -> int:
    r"""How far the document indents its own keys.

    Worth the trouble because the alternative is a four-hundred-line diff for a
    one-character repair. Gemini writes these files flat — every key at column zero —
    and re-serialising at two spaces reformats every line of a file whose actual fault
    was a single missing backslash, burying the repair in noise exactly where it most
    needs reading.

    Args:
        text: The original document.
        default: What to assume when the shape cannot be told.

    Returns:
        The number of leading spaces on the document's first key.

    Contract:
        - Returns ``0`` for a flat document, matching ``json.dumps(indent=0)``.
        - Never raises.

    Examples:
        >>> sniff_indent('{\n"chapter": 1\n}')
        0
        >>> sniff_indent('{\n    "chapter": 1\n}')
        4
        >>> sniff_indent('{"chapter": 1}')
        2
    """
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" ")
        if stripped.startswith('"'):
            return len(line) - len(stripped)
    return default


def render_json(data: dict[str, Any], indent: int = 2) -> str:
    r"""Serialise a repaired extraction for writing back.

    No ASCII escaping, so an accented character stays itself rather than turning into an
    escape and adding a line to the diff.

    Args:
        data: The repaired extraction.
        indent: Indentation width, normally from :func:`sniff_indent`.

    Returns:
        The document, ending in a newline.

    Examples:
        >>> render_json({"chapter": 1, "note": "café"})
        '{\n  "chapter": 1,\n  "note": "café"\n}\n'
        >>> render_json({"chapter": 1}, indent=0)
        '{\n"chapter": 1\n}\n'
    """
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n"


def repair_file(path: Path) -> RepairResult:
    """Work out what one extraction file needs.

    Reads only; writing is the caller's decision, which is what lets the stage script
    default to showing you the change before making it.

    Args:
        path: The extraction file.

    Returns:
        The result. ``changed`` is False when the file is already valid, in which case
        it should be left alone rather than rewritten.

    Contract:
        - Never writes.
        - A file that already parses and validates yields ``changed == False``.
        - A file that cannot be recovered yields a ``problem`` and no text.
    """
    if not path.exists() or not path.is_file():
        return RepairResult(path, problem="not found")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return RepairResult(path, problem="empty — the paste did not land")

    try:
        data, syntax_repaired = repair_text(raw)
    except ValueError as error:
        return RepairResult(path, problem=str(error))

    cleaned, dropped = drop_forbidden_fields(data)
    try:
        ChapterExtraction.model_validate(cleaned)
    except ValidationError as error:
        details = "; ".join(
            f"{_render_path(tuple(item['loc']))}: {item['msg']}"
            for item in error.errors()
        )
        return RepairResult(
            path,
            syntax_repaired=syntax_repaired,
            dropped_fields=tuple(dropped),
            problem=f"still invalid after repair — {details}",
        )

    return RepairResult(
        path,
        syntax_repaired=syntax_repaired,
        dropped_fields=tuple(dropped),
        text=render_json(cleaned, indent=sniff_indent(raw)),
    )
