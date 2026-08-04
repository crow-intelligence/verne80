from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.prompt import (
    PLACEHOLDER_NUMBER,
    PLACEHOLDER_TEXT,
    PROMPT_TEMPLATE,
    prompt_path,
    render_prompt,
    template_fingerprint,
)

SPEC = Path(__file__).resolve().parent.parent / "specs" / "verne80_workflow.md"

# The template's own delimiter, just before the embedded chapter. Splitting here is
# exact regardless of what the chapter text contains — partitioning on the text
# itself is not, because a one-character body collides with the digits inside the
# schema.
MARKER = "CHAPTER TEXT:\n---\n"


def split_at_marker(prompt: str) -> tuple[str, str]:
    head, marker, body = prompt.partition(MARKER)
    assert marker, "the template no longer contains its chapter-text delimiter"
    return head, body


def spec_template() -> str:
    """Pull the §4 template back out of the spec, as the source of truth."""
    lines = SPEC.read_text(encoding="utf-8").splitlines(keepends=True)
    fences = [i for i, line in enumerate(lines) if line.startswith("````")]
    assert len(fences) == 2, "expected exactly one four-backtick block in the spec"
    return "".join(lines[fences[0] + 1 : fences[1]])


class TestSingleSourceOfTruth:
    def test_template_matches_the_spec(self):
        """The whole point of one copy: spec-to-code drift is a test failure."""
        assert PROMPT_TEMPLATE == spec_template()

    def test_the_template_has_exactly_one_text_placeholder(self):
        assert PROMPT_TEMPLATE.count(PLACEHOLDER_TEXT) == 1

    def test_format_braces_would_have_broken_this(self):
        """Documents why substitution is str.replace and never str.format."""
        assert "{" in PROMPT_TEMPLATE
        with pytest.raises((KeyError, IndexError, ValueError)):
            PROMPT_TEMPLATE.format(N=1)


class TestRendering:
    def test_no_placeholders_survive(self):
        prompt = render_prompt(7, "CHAPTER 07\nA TITLE\n\nThe body.")
        assert PLACEHOLDER_NUMBER not in prompt
        assert PLACEHOLDER_TEXT not in prompt
        assert "{{" not in prompt

    def test_the_chapter_number_renders_as_valid_json(self):
        """`"chapter": 07` is a parse error; zero-padding cannot be literal."""
        assert '"chapter": 7,' in render_prompt(7, "body")

    def test_chapter_text_appears_verbatim_exactly_once(self):
        text = "CHAPTER 12\nA TITLE\n\nThey mounted upon the elephant."
        assert render_prompt(12, text).count(text) == 1

    def test_empty_chapter_text_raises(self):
        with pytest.raises(ValueError, match="empty chapter text"):
            render_prompt(1, "   \n  ")

    def test_chapter_text_containing_a_placeholder_raises(self):
        with pytest.raises(ValueError, match="chapter text contains"):
            render_prompt(1, "a body with {{CHAPTER_TEXT}} in it")

    def test_prompt_paths_are_zero_padded(self, tmp_path):
        assert prompt_path(tmp_path, 7).name == "chapter_07.txt"

    def test_the_fingerprint_is_a_sha256(self):
        assert len(template_fingerprint()) == 64


class TestPromptProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.integers(min_value=1, max_value=37),
        st.integers(min_value=1, max_value=37),
        st.text(min_size=1).filter(lambda s: s.strip() and "{{" not in s),
        st.text(min_size=1).filter(lambda s: s.strip() and "{{" not in s),
    )
    def test_the_scaffold_is_identical_across_renders(self, n1, n2, t1, t2):
        """Everything but the number and the chapter text stays byte-identical."""
        head1, body1 = split_at_marker(render_prompt(n1, t1))
        head2, body2 = split_at_marker(render_prompt(n2, t2))
        assert head1.replace(f'"chapter": {n1},', "") == head2.replace(
            f'"chapter": {n2},', ""
        )
        assert body1.removeprefix(t1) == body2.removeprefix(t2)

    @settings(max_examples=150, deadline=None)
    @given(
        st.integers(min_value=1, max_value=37),
        st.text(min_size=1).filter(lambda s: s.strip() and "{{" not in s),
    )
    def test_no_placeholder_ever_survives(self, number, text):
        prompt = render_prompt(number, text)
        assert PLACEHOLDER_NUMBER not in prompt
        assert PLACEHOLDER_TEXT not in prompt

    @settings(max_examples=150, deadline=None)
    @given(
        st.integers(min_value=1, max_value=37),
        st.text(min_size=1).filter(lambda s: s.strip() and "{{" not in s),
    )
    def test_rendering_is_deterministic(self, number, text):
        assert render_prompt(number, text) == render_prompt(number, text)
