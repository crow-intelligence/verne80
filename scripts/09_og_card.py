"""Draw the card that appears when somebody shares the page.

The head has promised ``assets/og.png`` at 1200x630 since the first commit and the file
has never existed, so every share has unfurled without it. This draws it, from the same
words and the same palette as the page, so the card and the title cannot disagree.

Pillow reads TrueType and the page ships woff2, so the two typefaces are fetched again
here in a format Pillow can open. They land in a gitignored build directory: they are
not the fonts the page serves, they are a tool for making one image, and committing a
second copy of a typeface is how a repository ends up with two answers to the question
of what its own title looks like.

Requires the ``og`` extra: ``uv sync --extra og``.

Run: ``uv run python scripts/09_og_card.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from verne80.strings import STRINGS

DEFAULT_OUT = Path("web/assets/og.png")
DEFAULT_FONTS = Path("build/og-fonts")

WIDTH, HEIGHT = 1200, 630

# The page's own tokens, from web/style.css. Written out rather than parsed: three hex
# values are not worth a CSS parser, and a test asserts they still match.
PAPER = (247, 245, 239)
INK = (26, 26, 23)
ACCENT = (122, 31, 31)
MUTED = (90, 83, 70)

FONTS = {
    "display": (
        "PlayfairDisplay.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/"
        "PlayfairDisplay%5Bwght%5D.ttf",
    ),
    "numeral": (
        "AbrilFatface.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/abrilfatface/"
        "AbrilFatface-Regular.ttf",
    ),
    "text": (
        "EBGaramond.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/"
        "EBGaramond%5Bwght%5D.ttf",
    ),
}


def fetch_fonts(directory: Path) -> dict[str, Path]:
    """Download the TrueType originals Pillow needs, once."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        for role, (name, url) in FONTS.items():
            path = directory / name
            if not path.exists():
                path.write_bytes(client.get(url).content)
                print(f"  got   {path} ({path.stat().st_size:,} bytes)")
            paths[role] = path
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the share card.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fonts", type=Path, default=DEFAULT_FONTS)
    args = parser.parse_args(argv)

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print(
            "  FAIL  Pillow is not installed — run `uv sync --extra og`",
            file=sys.stderr,
        )
        return 1

    faces = fetch_fonts(args.fonts)
    card = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(card)

    # The brick rule along the top, the same accent the page uses for its numeral.
    draw.rectangle([(0, 0), (WIDTH, 14)], fill=ACCENT)

    world = ImageFont.truetype(str(faces["display"]), 96)
    eighty = ImageFont.truetype(str(faces["numeral"]), 210)
    small = ImageFont.truetype(str(faces["display"]), 54)
    body = ImageFont.truetype(str(faces["text"]), 34)
    brand = ImageFont.truetype(str(faces["text"]), 28)

    _centre(draw, STRINGS["title.line1"], world, 140, INK)

    # The second line is laid out by hand rather than centred as one string: the numeral
    # is four times the height of the words beside it and shares their baseline, which
    # is the whole look and is not something a single draw call can do.
    widths = [
        draw.textlength(STRINGS["title.in"], font=small),
        draw.textlength(STRINGS["title.eighty"], font=eighty),
        draw.textlength(STRINGS["title.days"], font=small),
    ]
    gap = 28
    left = (WIDTH - sum(widths) - 2 * gap) / 2
    baseline = 430
    draw.text(
        (left, baseline), STRINGS["title.in"], font=small, fill=MUTED, anchor="ls"
    )
    left += widths[0] + gap
    draw.text(
        (left, baseline), STRINGS["title.eighty"], font=eighty, fill=ACCENT, anchor="ls"
    )
    left += widths[1] + gap
    draw.text(
        (left, baseline), STRINGS["title.days"], font=small, fill=MUTED, anchor="ls"
    )

    _centre(draw, STRINGS["site.subtitle"], body, 500, MUTED)
    _centre(draw, STRINGS["nav.brand"], brand, 570, ACCENT)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    card.save(args.out, "PNG", optimize=True)
    print(f"  wrote {args.out} ({args.out.stat().st_size:,} bytes, {WIDTH}x{HEIGHT})")
    return 0


def _centre(draw, text: str, font, top: int, fill) -> None:
    """One line, centred on the card."""
    draw.text((WIDTH / 2, top), text, font=font, fill=fill, anchor="ma")


if __name__ == "__main__":
    sys.exit(main())
