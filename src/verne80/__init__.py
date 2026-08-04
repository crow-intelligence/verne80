"""Around the World in Eighty Days as a route + calendar dataset.

The pipeline is four filesystem stages under ``scripts/``: fetch the Gutenberg text,
slice it into thirty-seven chapters, render one extraction prompt per chapter, and
validate the JSON that comes back — schema first, then every evidence quote grepped
against the chapter it claims to come from.
"""

from importlib.metadata import PackageNotFoundError, version

from verne80.chapters import Chapter, check_chapters, split_chapters
from verne80.evidence import MatchKind, QuoteCheck, check_quote
from verne80.extractions import load_extraction, parse_extraction_json
from verne80.normalize import fold_typography, match_key, normalize_quote
from verne80.prompt import PROMPT_TEMPLATE, render_prompt
from verne80.route import RouteLeg, RouteNode, RouteSpine, check_spine, parse_itinerary
from verne80.schema import ChapterExtraction, Narrative, check_extraction, is_stale
from verne80.sources import BOOK, GutenbergSource

try:
    __version__ = version("verne80")
except PackageNotFoundError:  # pragma: no cover - only when running uninstalled
    __version__ = "0.0.0+unknown"

__all__ = [
    "BOOK",
    "PROMPT_TEMPLATE",
    "Chapter",
    "ChapterExtraction",
    "GutenbergSource",
    "MatchKind",
    "Narrative",
    "QuoteCheck",
    "RouteLeg",
    "RouteNode",
    "RouteSpine",
    "__version__",
    "check_chapters",
    "check_extraction",
    "check_quote",
    "check_spine",
    "fold_typography",
    "is_stale",
    "load_extraction",
    "match_key",
    "normalize_quote",
    "parse_extraction_json",
    "parse_itinerary",
    "render_prompt",
    "split_chapters",
]
