"""Render one paste-ready extraction prompt per chapter.

Each prompt embeds its chapter file verbatim, which is the invariant the evidence
validator depends on: what the model reads and what the validator greps are the same
bytes. The manifest records the template's fingerprint and each chapter's, so a later
run can tell whether an extraction was produced under these exact instructions and
against this exact text.

Run: ``uv run python scripts/02_prompts.py``
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

from verne80.chapters import chapter_path
from verne80.prompt import prompt_path, render_prompt, template_fingerprint

DEFAULT_CHAPTERS_DIR = Path("data/chapters")
DEFAULT_PROMPTS_DIR = Path("data/prompts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the 37 extraction prompts.")
    parser.add_argument("--chapters-dir", type=Path, default=DEFAULT_CHAPTERS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_PROMPTS_DIR)
    args = parser.parse_args(argv)

    index_path = args.chapters_dir / "index.json"
    if not index_path.exists():
        print(
            f"  FAIL  {index_path} not found — "
            "run `uv run python scripts/01_chapters.py` first",
            file=sys.stderr,
        )
        return 1
    index = json.loads(index_path.read_text(encoding="utf-8"))

    fingerprint = template_fingerprint()
    print(f"  template sha256 {fingerprint[:12]}…")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for entry in index["chapters"]:
        number = int(entry["number"])
        source = chapter_path(args.chapters_dir, number)
        if not source.exists():
            print(
                f"  FAIL  {source} not found — re-run scripts/01_chapters.py",
                file=sys.stderr,
            )
            return 1
        text = source.read_text(encoding="utf-8")

        try:
            rendered = render_prompt(number, text)
        except ValueError as error:
            print(f"  FAIL  {error}", file=sys.stderr)
            return 1
        if "{{" in rendered:
            print(
                f"  FAIL  chapter {number:02d}: a placeholder survived rendering",
                file=sys.stderr,
            )
            return 1

        destination = prompt_path(args.out_dir, number)
        destination.write_text(rendered, encoding="utf-8")
        entries.append(
            {
                "number": number,
                "file": destination.name,
                "chars": len(rendered),
                "sha256": sha256(rendered.encode("utf-8")).hexdigest(),
                "chapter_sha256": entry["sha256"],
            }
        )
        print(f"  ch {number:02d}   {len(rendered):6,} chars  {destination}")

    manifest = args.out_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_by": "scripts/02_prompts.py",
                "template_sha256": fingerprint,
                "prompts": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {manifest} ({len(entries)} prompts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
