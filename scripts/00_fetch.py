"""Download the raw material into ``data/raw/``.

Project Gutenberg #103 and the Natural Earth coastline, each kept byte-for-byte as
served. These files are the provenance record for everything downstream and are never
edited in place; if one needs to change, re-fetch it with ``--force`` and expect the
hashes recorded beside it to move too.

The coastline is here rather than in the dashboard stage for the same reason the novel
is: a basemap fetched at build time is a basemap that can change without anyone
noticing, and the globe's committed geometry would then be derived from something no
longer on disk.

Run: ``uv run python scripts/00_fetch.py``
Run: ``uv run python scripts/00_fetch.py --only land``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from verne80.sources import DEFAULT_RAW_DIR, SOURCES, GeoJSONSource


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20))
def download(url: str) -> bytes:
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
    return response.content


def fetch(source, raw_dir: Path, force: bool) -> int:
    """Fetch one source. Returns 0 on success or skip, 1 if every URL failed."""
    dest = raw_dir / source.path.name
    if dest.exists() and not force:
        print(f"  skip  {dest} ({dest.stat().st_size:,} bytes)")
        return 0

    for url in source.urls:
        try:
            content = download(url)
        except Exception as error:  # noqa: BLE001 - try the next URL shape
            print(f"  miss  {url} ({type(error).__name__})")
            continue
        if len(content) < source.min_bytes:
            print(f"  miss  {url} (only {len(content):,} bytes — an error page?)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        print(f"  got   {dest} ({len(content):,} bytes)")
        print(f"  from  {url}")
        if isinstance(source, GeoJSONSource):
            print(f"  terms {source.attribution} — {source.licence}")
        return 0

    print(
        f"  FAIL  none of {len(source.urls)} URLs served {source.title}",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    names = [source.name for source in SOURCES]
    parser = argparse.ArgumentParser(description="Download the raw material.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--force", action="store_true", help="re-download even if the file exists"
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        choices=names,
        help=f"fetch just this source ({', '.join(names)}); repeatable",
    )
    args = parser.parse_args(argv)

    wanted = [s for s in SOURCES if not args.only or s.name in args.only]
    failures = sum(fetch(source, args.raw_dir, args.force) for source in wanted)
    if failures:
        print(
            f"  FAIL  {failures} of {len(wanted)} sources unavailable", file=sys.stderr
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
