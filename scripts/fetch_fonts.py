"""Self-host the two typefaces, Latin subsets only.

The page is a dashboard, and the house rule for those is that it ships with no external
network dependency at view time — a missing stylesheet from someone else's CDN is a page
that has silently changed its mind about what century it is from.

Google serves each family already cut into subsets with a ``unicode-range`` on each,
which is exactly the split we would otherwise build by hand: an English reader
downloads only ``latin``, and the ``latin-ext`` file, which carries the Hungarian ő and
ű, is fetched only by a page that actually needs them. So this takes those files rather
than re-subsetting the originals, and keeps only ``latin`` and ``latin-ext`` of the
seven offered.

Both families are under the SIL Open Font License 1.1, which requires the licence to
travel with the fonts; ``web/fonts/OFL-*.txt`` is written beside them and is not
optional.

One thing this cannot check, and it matters: ``font-variant-numeric`` needs the
``onum``, ``lnum`` and ``tnum`` features to have survived subsetting. The day counts
are set in tabular figures and the prose in old-style ones, and if the features are
gone both silently fall back to the default. Look at the page, not at this script.

Run: ``uv run python scripts/fetch_fonts.py``
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import httpx

DEFAULT_OUT = Path("web/fonts")

# A modern browser's user agent, because the API serves woff2 to a browser it recognises
# and older, larger formats to one it does not.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Abril+Fatface"
    "&family=EB+Garamond:ital,wght@0,400;0,600;1,400"
    "&family=Playfair+Display:ital,wght@0,400;1,400"
    "&display=swap"
)

# Of the seven subsets Google cuts, these two. Cyrillic, Greek and Vietnamese are
# weight the page would ship and never use.
WANTED_SUBSETS = ("latin", "latin-ext")

SHORT_SUBSET = {"latin": "lat", "latin-ext": "ext"}

# The licence file for each family, so the OFL requirement travels with the bytes.
LICENCES = {
    # One weight, one style, used for exactly one thing: the numeral in the title. A fat
    # Didone is what a Victorian title page put a number in, and Playfair — which is a
    # Didone too, just not a fat one — cannot carry that on its own.
    "Abril Fatface": (
        "abrilfatface",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/abrilfatface/OFL.txt",
    ),
    "EB Garamond": (
        "ebgaramond",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/OFL.txt",
    ),
    "Playfair Display": (
        "playfairdisplay",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/OFL.txt",
    ),
}

_BLOCK = re.compile(
    r"/\*\s*(?P<subset>[a-z-]+)\s*\*/\s*@font-face\s*\{(?P<body>[^}]*)\}", re.S
)


def field(body: str, name: str) -> str:
    match = re.search(rf"{name}:\s*([^;]+);", body)
    return match.group(1).strip().strip("'\"") if match else ""


def _parse(block: re.Match[str]) -> dict[str, str] | None:
    """One @font-face block as a flat record, or None if it carries no usable source."""
    body = block.group("body")
    url = re.search(r"url\(([^)]+)\)", body)
    family = field(body, "font-family")
    if not (family and url):
        return None
    return {
        "subset": block.group("subset"),
        "family": family,
        "style": field(body, "font-style"),
        "weight": field(body, "font-weight"),
        "ranges": field(body, "unicode-range"),
        "url": url.group(1),
    }


def slug(family: str) -> str:
    return family.lower().replace(" ", "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-host the page's typefaces.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(CSS_URL, headers={"User-Agent": USER_AGENT})
        if response.status_code != 200:
            print(
                f"  FAIL  the font API answered {response.status_code}", file=sys.stderr
            )
            return 1
        css = response.text

        args.out.mkdir(parents=True, exist_ok=True)
        wanted = [
            face
            for face in (_parse(block) for block in _BLOCK.finditer(css))
            if face and face["subset"] in WANTED_SUBSETS
        ]

        # EB Garamond is a variable font, and the API serves the same bytes for 400 and
        # 600 — the browser picks the weight off the axis. Writing them under two names
        # would ship 158 KB twice, so faces are grouped by what they actually are and
        # collapsed wherever the downloads turn out to be the same file.
        downloads: dict[str, bytes] = {}
        for face in wanted:
            if face["url"] not in downloads:
                downloads[face["url"]] = client.get(face["url"]).content

        groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
        for face in wanted:
            digest = hashlib.sha256(downloads[face["url"]]).hexdigest()
            groups.setdefault(
                (face["family"], face["style"], face["subset"], digest), []
            ).append(face)

        faces: list[str] = []
        for (family, style, subset, _), members in sorted(groups.items()):
            weights = sorted({int(face["weight"]) for face in members})
            span = "" if len(weights) == 1 else f"-{weights[-1]}"
            letter = "i" if style == "italic" else "n"
            name = (
                f"{slug(family)}-{weights[0]}{span}"
                f"-{letter}-{SHORT_SUBSET[subset]}.woff2"
            )
            data = downloads[members[0]["url"]]
            (args.out / name).write_bytes(data)
            shared = (
                "" if len(weights) == 1 else f"  (one file, {len(weights)} weights)"
            )
            listed = "/".join(str(weight) for weight in weights)
            print(
                f"  got   {args.out / name} ({len(data):,} bytes)  "
                f"{family} {listed} {style}{shared}"
            )
            # A weight range rather than a single value: one variable file covers every
            # weight between them, and the browser interpolates.
            declared = (
                f"{weights[0]}" if len(weights) == 1 else f"{weights[0]} {weights[-1]}"
            )
            faces.append(
                "@font-face {\n"
                f"  font-family: '{family}';\n"
                f"  font-style: {style};\n"
                f"  font-weight: {declared};\n"
                "  font-display: swap;\n"
                f"  src: url('./{name}') format('woff2');\n"
                f"  unicode-range: {members[0]['ranges']};\n"
                "}"
            )
        kept = len(faces)

        for family, (directory, licence_url) in LICENCES.items():
            licence = client.get(licence_url).text
            path = args.out / f"OFL-{directory}.txt"
            path.write_text(licence, encoding="utf-8")
            print(f"  got   {path} ({len(licence):,} bytes)  {family}, SIL OFL 1.1")

    header = (
        "/* Self-hosted subsets, Latin and Latin-Ext. Generated by\n"
        " * scripts/fetch_fonts.py — edit that, not this.\n"
        " *\n"
        " * EB Garamond and Playfair Display are both under the SIL Open Font License\n"
        " * 1.1; see OFL-ebgaramond.txt and OFL-playfairdisplay.txt beside this file.\n"
        " *\n"
        " * The -ext files carry the Hungarian o- and u-double-acute, so an English\n"
        " * reader never downloads them. That is the whole reason for the split.\n"
        " */\n\n"
    )
    css_path = args.out / "fonts.css"
    css_path.write_text(header + "\n\n".join(faces) + "\n", encoding="utf-8")
    print("  ---")
    print(f"  wrote {css_path} ({kept} faces)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
