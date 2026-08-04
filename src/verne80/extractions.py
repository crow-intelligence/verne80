r"""Load the JSON that comes back from Gemini, tolerantly.

The prompt asks for a single JSON object and nothing else. Models mostly comply, and
occasionally do not: a markdown fence around the object, or a line of "Here is the JSON
you asked for:" before it. Neither changes the data, and neither is worth a manual edit
thirty-seven times, so the loader peels them off.

What the loader does *not* do is repair the JSON itself. A truncated or malformed object
is a real problem with a real cause — the paste was cut short, the model ran out of room
— and guessing at the missing half would produce a plausible extraction that nobody
checked. Those raise, naming the file and the position, and land in the review queue.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from verne80.schema import ChapterExtraction

__all__ = [
    "extract_json_object",
    "load_all",
    "load_extraction",
    "parse_extraction_json",
    "strip_code_fences",
]

_FENCE = re.compile(
    r"\A\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n?\s*```\s*\Z", re.DOTALL
)


def strip_code_fences(text: str) -> str:
    r"""Remove a surrounding markdown code fence, if there is one.

    Args:
        text: The pasted response.

    Returns:
        The fenced body, or the input unchanged when there is no fence.

    Contract:
        - Identity when the input contains no triple backtick.
        - Idempotent.
        - Never raises.

    Examples:
        >>> strip_code_fences('```json\n{"chapter": 1}\n```')
        '{"chapter": 1}'
        >>> strip_code_fences('{"chapter": 1}')
        '{"chapter": 1}'
    """
    match = _FENCE.match(text)
    return match.group("body") if match else text


def extract_json_object(text: str) -> str:
    r"""Return the outermost balanced ``{...}`` in ``text``.

    Brace counting is string- and escape-aware, so a brace inside a quoted evidence
    quotation does not end the object early.

    Args:
        text: Any text containing a JSON object.

    Returns:
        The substring from the first ``{`` to its matching ``}``.

    Raises:
        ValueError: If there is no brace, or the braces never balance.

    Contract:
        - The result starts with ``{`` and ends with ``}``.
        - Identity for text that is exactly one JSON object.

    Examples:
        >>> extract_json_object('Here you go:\n{"a": "}"}\nHope that helps!')
        '{"a": "}"}'
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("no '{' found — the response contains no JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("braces never balance — the response looks truncated")


def parse_extraction_json(text: str, *, origin: str = "<string>") -> dict[str, object]:
    r"""Parse a pasted response into a dict, tolerating fences and preamble prose.

    Three tiers are tried in order and the first success wins: the raw text, the
    fence-stripped text, and the outermost balanced object.

    Args:
        text: The pasted response.
        origin: What to name in the error message — normally the file path.

    Returns:
        The parsed object.

    Raises:
        ValueError: If no tier yields a JSON object, with the decode position and an
            excerpt around it.

    Contract:
        - Returns a ``dict`` or raises; never a partial result, never a non-dict.
        - Round-trips: ``parse_extraction_json(json.dumps(d)) == d``.
        - Wrapping the same text in a fence does not change the result.

    Examples:
        >>> parse_extraction_json('```json\n{"chapter": 1}\n```')
        {'chapter': 1}
        >>> parse_extraction_json('Here is the JSON:\n{"chapter": 2}')
        {'chapter': 2}
    """
    last_error: json.JSONDecodeError | None = None
    for candidate in _candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as error:
            last_error = error
            continue
        if not isinstance(parsed, dict):
            raise ValueError(
                f"{origin}: expected a JSON object, got {type(parsed).__name__}"
            )
        return parsed

    if last_error is None:
        raise ValueError(f"{origin}: no JSON object found in the response")
    excerpt = text[max(0, last_error.pos - 40) : last_error.pos + 40].replace(
        "\n", "\\n"
    )
    raise ValueError(
        f"{origin}: invalid JSON at line {last_error.lineno} column {last_error.colno} "
        f"({last_error.msg}) near: …{excerpt}…"
    )


def _candidates(text: str) -> Iterable[str]:
    """Yield the tiers to try, skipping any that duplicates an earlier one."""
    seen: set[str] = set()
    tiers = [text, strip_code_fences(text)]
    try:
        tiers.append(extract_json_object(text))
    except ValueError:
        pass
    for candidate in tiers:
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def load_extraction(path: Path) -> ChapterExtraction:
    """Load and validate one extraction file.

    Args:
        path: The file, normally ``data/extractions/chapter_NN.json``.

    Returns:
        The validated extraction.

    Raises:
        FileNotFoundError: If the file is not there, pointing at the paste workflow.
        ValueError: If the JSON is malformed or fails schema validation. Validation
            failures are reported with their field addresses, which are what the review
            queue prints.

    Contract:
        - Never returns a partially validated model.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — paste Gemini's output there; "
            "see data/prompts/README.md"
        )
    data = parse_extraction_json(path.read_text(encoding="utf-8"), origin=str(path))
    try:
        # model_validate, not ChapterExtraction(**data): the input is an untyped dict
        # straight off disk, and this is the entry point pydantic types for that.
        return ChapterExtraction.model_validate(data)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        raise ValueError(f"{path}: schema validation failed — {details}") from error


def load_all(
    directory: Path, numbers: Iterable[int]
) -> tuple[dict[int, ChapterExtraction], list[str]]:
    """Load every requested extraction, collecting failures rather than raising.

    One bad paste should not stop the other thirty-six from being checked — the point of
    a review queue is to see all of it at once.

    Args:
        directory: The extractions directory.
        numbers: The chapter numbers to load.

    Returns:
        A ``(loaded, problems)`` pair, keyed by chapter number.

    Contract:
        - Never raises.
        - Every requested number appears in exactly one of the two results.
    """
    loaded: dict[int, ChapterExtraction] = {}
    problems: list[str] = []
    for number in numbers:
        path = directory / f"chapter_{number:02d}.json"
        try:
            loaded[number] = load_extraction(path)
        except (FileNotFoundError, ValueError) as error:
            problems.append(str(error))
    return loaded, problems
