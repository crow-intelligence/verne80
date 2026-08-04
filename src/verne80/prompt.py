r"""The extraction prompt — one copy, for all thirty-seven runs.

The workflow document is explicit that everything except the chapter number and the
chapter text stays byte-identical across all thirty-seven runs, because that is what
makes the outputs mergeable. Keeping the template in one module constant is half of that
guarantee; ``tests/test_prompt.py`` supplies the other half by parsing the template back
out of ``specs/verne80_workflow.md`` and asserting the two agree. Edit the spec and the
constant together, or the test will say so.

Two notes on rendering:

**No ``str.format``.** The template body is a JSON schema, so it is full of braces. An
f-string or a ``.format`` call raises on it. Substitution is two literal
:meth:`str.replace` calls, and nothing else.

**The chapter number renders as a plain integer.** The workflow document says to
substitute the zero-padded number, but the template line is ``"chapter": {{N}},`` and
``"chapter": 07`` is not valid JSON. Rendering ``7`` keeps the model's expected output
parseable; zero-padding stays where it belongs, in filenames.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

__all__ = [
    "PLACEHOLDER_NUMBER",
    "PLACEHOLDER_TEXT",
    "PROMPT_TEMPLATE",
    "prompt_path",
    "render_prompt",
    "template_fingerprint",
]

PLACEHOLDER_NUMBER = "{{N}}"
PLACEHOLDER_TEXT = "{{CHAPTER_TEXT}}"

PROMPT_TEMPLATE = """\
You are extracting structured data from one chapter of Jules Verne's "Around the World in
Eighty Days" (1872). Work ONLY from the chapter text provided below. Do not use outside
knowledge of the novel, and do not infer beyond what the text states.

Return a SINGLE valid JSON object and NOTHING else — no markdown fences, no commentary,
no explanation before or after.

Write all prose output in ENGLISH.

CRITICAL RULES:
1. If a field is not explicitly stated in this chapter, use null (or an empty array).
   NEVER guess, estimate, or carry over information from other chapters.
2. For every extracted item, include a short verbatim quote from the chapter as evidence.
   The quote must appear word-for-word in the text.
3. Use the spellings AS THEY APPEAR in the 1872 text (e.g. "Bombay", not "Mumbai").
   Modernisation happens later, not here.
4. Distinguish places the travellers ARE IN or PASS THROUGH from places merely MENTIONED.
5. Distinguish people who ARE PRESENT in this chapter's scene from people who are
   only TALKED ABOUT, written to, or reported on.

Schema:

{
  "chapter": {{N}},
  "title": "<chapter title as printed, or null>",
  "summary_hover": "<ONE sentence, max 25 words. What happens in this chapter. Must fit in a hover tooltip. Present tense, plain English, no spoilers beyond this chapter.>",
  "summary_detail": "<3-4 sentences for the side panel: what happens, plus any historical or geographic context the chapter itself supplies. General adult reader, no specialist knowledge assumed.>",
  "places_visited": [
    {
      "name_in_text": "<as printed>",
      "role": "<arrival|departure|passing_through|setting>",
      "evidence": "<verbatim quote>"
    }
  ],
  "places_mentioned": [
    { "name_in_text": "<as printed>", "evidence": "<verbatim quote>" }
  ],
  "people": [
    {
      "name_in_text": "<as printed>",
      "role": "<short description from this chapter only>",
      "evidence": "<verbatim quote>"
    }
  ],
  "narrative": {
    "on_stage": [
      {
        "name_in_text": "<person, as printed — ONLY people physically present in this chapter>",
        "at_name_in_text": "<the place THIS CHAPTER puts them, as printed, or null>",
        "between_from": "<if in transit, the place left, as printed, or null>",
        "between_to": "<if in transit, the place bound for, as printed, or null>",
        "evidence": "<verbatim quote placing this person here>"
      }
    ],
    "named_but_not_present": [
      { "name_in_text": "<as printed>", "evidence": "<verbatim quote>" }
    ],
    "notes": "<anything ambiguous about who is where, or null>"
  },
  "transport": [
    {
      "mode": "<steamer|railway|elephant|sledge|carriage|on_foot|other>",
      "vessel_or_line_name": "<e.g. 'Mongolia', or null>",
      "from": "<place or null>",
      "to": "<place or null>",
      "evidence": "<verbatim quote>"
    }
  ],
  "time": {
    "dates_mentioned": [
      { "as_written": "<verbatim date phrase>", "evidence": "<verbatim quote>" }
    ],
    "days_elapsed_or_remaining": "<only if the text states it, else null>",
    "schedule_status": "<ahead|behind|on_time|unknown>",
    "schedule_detail": "<e.g. 'gained two days', verbatim-ish, or null>",
    "evidence": "<verbatim quote, or null>"
  },
  "money": {
    "amounts": [
      {
        "amount_as_written": "<e.g. '£20,000', '2,000 pounds'>",
        "purpose": "<what it is for, from the text>",
        "evidence": "<verbatim quote>"
      }
    ],
    "fogg_remaining_stated": "<only if the text explicitly states a remaining sum, else null>"
  },
  "notes": "<anything ambiguous or worth a human check, or null>"
}

MONEY WARNING: Verne mentions sums irregularly. Most chapters state NO amount at all.
An empty "amounts" array and a null "fogg_remaining_stated" are the CORRECT and EXPECTED
answer for most chapters. Do not invent figures to fill the schema.

NARRATIVE WARNING: "on_stage" is about THIS chapter's scene, not about the story. A
person the chapter discusses, writes to, telegraphs, or reports on is NOT on stage —
they go in "named_but_not_present". If the chapter does not say where someone is, leave
all three place fields null; do not work it out from anywhere else. A chapter in which
the travellers never appear is a real chapter, and an empty "on_stage" array is the
CORRECT and EXPECTED answer for it. If a person moves during the chapter, give one entry
for each place the text puts them in, in the order the chapter puts them there.

CHAPTER TEXT:
---
{{CHAPTER_TEXT}}
---
"""


def render_prompt(number: int, chapter_text: str) -> str:
    r"""Fill the template for one chapter.

    Args:
        number: The chapter number, rendered as a plain integer.
        chapter_text: The full contents of ``chapter_NN.txt``, embedded verbatim.

    Returns:
        The prompt, ready to paste.

    Raises:
        ValueError: If ``chapter_text`` is empty or itself contains a placeholder marker
        —
            either would make the rendered prompt ambiguous.

    Contract:
        - Neither placeholder survives in the output.
        - ``chapter_text`` appears in the output verbatim, exactly once.
        - The scaffold is identical across renders: for any two prompts, the text after
          the embedded chapter is the same, and the text before it differs only in the
          rendered number.
        - Pure and deterministic.

    Examples:
        >>> prompt = render_prompt(7, "CHAPTER 07\\nA TITLE\\n\\nThe body.")
        >>> "{{N}}" in prompt or "{{CHAPTER_TEXT}}" in prompt
        False
        >>> '"chapter": 7,' in prompt
        True
        >>> prompt.count("The body.")
        1
    """
    if not chapter_text.strip():
        raise ValueError(f"chapter {number}: empty chapter text")
    for marker in (PLACEHOLDER_NUMBER, PLACEHOLDER_TEXT):
        if marker in chapter_text:
            raise ValueError(f"chapter {number}: chapter text contains {marker!r}")
    rendered = PROMPT_TEMPLATE.replace(PLACEHOLDER_NUMBER, str(number))
    return rendered.replace(PLACEHOLDER_TEXT, chapter_text)


def prompt_path(directory: Path, number: int) -> Path:
    """Where the rendered prompt for chapter ``number`` lives.

    Args:
        directory: The prompts directory.
        number: The chapter number.

    Returns:
        The path, zero-padded to match ``data/chapters/`` and ``data/extractions/``.

    Examples:
        >>> prompt_path(Path("data/prompts"), 7)
        PosixPath('data/prompts/chapter_07.txt')
    """
    return directory / f"chapter_{number:02d}.txt"


def template_fingerprint() -> str:
    """Hex digest of the template, recorded in the prompts manifest.

    If this changes, every extraction produced under the old template was produced under
    a different set of instructions — which is worth knowing before merging them.

    Returns:
        The sha256 hex digest.

    Contract:
        - Deterministic, and depends only on :data:`PROMPT_TEMPLATE`.

    Examples:
        >>> len(template_fingerprint())
        64
    """
    return sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
