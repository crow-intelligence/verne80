"""Download the raw novel into ``data/raw/``.

Project Gutenberg #103, kept byte-for-byte as served. This file is the provenance record
for everything downstream and is never edited in place; if it needs to change, re-fetch
it with ``--force`` and expect the chapter hashes in ``index.json`` to move with it.

Run: ``uv run python scripts/00_fetch.py``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from verne80.sources import BOOK, DEFAULT_RAW_DIR

MIN_BYTES = 100_000


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20))
def download(url: str) -> bytes:
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
    return response.content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Project Gutenberg #103.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--force", action="store_true", help="re-download even if the file exists"
    )
    args = parser.parse_args(argv)

    dest = args.raw_dir / BOOK.path.name
    if dest.exists() and not args.force:
        print(f"  skip  {dest} ({dest.stat().st_size:,} bytes)")
        return 0

    for url in BOOK.urls:
        try:
            content = download(url)
        except Exception as error:  # noqa: BLE001 - try the next URL shape
            print(f"  miss  {url} ({type(error).__name__})")
            continue
        if len(content) < MIN_BYTES:
            print(f"  miss  {url} (only {len(content):,} bytes — an error page?)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        print(f"  got   {dest} ({len(content):,} bytes)")
        print(f"  from  {url}")
        return 0

    print(
        f"  FAIL  none of {len(BOOK.urls)} Gutenberg URLs served #103", file=sys.stderr
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
