# verne80

*Around the World in Eighty Days* (Verne, 1872) as a route + calendar dataset — and, downstream,
an interactive map that flips between the world as it was and the world as it is.

The novel already contains its own dataset. Fogg keeps an itinerary with a column of gains and
losses; the wager is a route *plus* a deadline. This package's job is not to impose structure on
the text but to make the text's own structure extractable, checkable, and joinable.

The pipeline splits the work the way it should be split: **deterministic work to code** (fetching,
slicing, joining, validating) and **reading-comprehension work to an LLM with a human check**
(who is where, when, and by what means). The join between the two is an evidence quote — every
extracted fact carries a verbatim quotation from the chapter, and a validator greps each one back
against the source. Hallucinations do not survive that check.

## Installation

```bash
uv sync --all-extras
```

## Quickstart

The pipeline is four stages that communicate only through the filesystem.

```bash
uv run python scripts/00_fetch.py       # Gutenberg #103 -> data/raw/pg103.txt
uv run python scripts/01_chapters.py    # -> data/chapters/chapter_01.txt .. _37.txt + index.json
uv run python scripts/02_prompts.py     # -> data/prompts/chapter_NN.txt (paste these into Gemini)
#   ... paste each prompt into the Gemini UI, save the JSON to data/extractions/chapter_NN.json
uv run python scripts/03_validate.py    # schema + evidence-quote check -> data/review/
```

See `data/prompts/README.md` for the paste workflow.

## Features

- **Chapter splitting that fails loudly.** Column-0 heading anchoring makes the table of contents
  structurally unmatchable, and the count is asserted at 37. If the split is wrong, the stage
  writes nothing and says why.
- **The book's own table of contents as an oracle.** The 37 TOC titles are compared against the 37
  body titles, so the split is cross-checked by the text itself.
- **One copy of the extraction prompt.** A test parses the template out of
  `specs/verne80_workflow.md` and asserts it matches the constant in the code, so "byte-identical
  across all 37 runs" is a checked claim rather than a comment.
- **Evidence-quote validation.** Each quote is matched through a ladder — exact, typography- and
  line-wrap-normalised, case-insensitive, ellipsis-spanning, near-miss, missing — and everything
  short of a clean pass lands in a review queue with the closest real text, a line number, and an
  inline diff.
- **A schema that does not pressure the model.** Money is null by default; an empty `amounts`
  array is the correct and expected answer for most chapters.

## Data

`data/raw/` and `data/chapters/` are committed. Gutenberg's URL is mutable, and the evidence
quotes are joined to this exact wording — committing the text makes the repo reproducible offline
and turns any change to the splitter into a reviewable diff. `data/extractions/` is committed too:
hand-verified project data, expensive to regenerate. `data/prompts/*.txt` and `data/review/` are
regenerable and ignored.

## Roadmap

**Extraction pipeline**

- [x] Fetch and slice Gutenberg #103 into 37 chapters
- [x] Render the 37 extraction prompts
- [x] Schema validation + evidence-quote validator
- [ ] Wikidata place resolution -> `data/review/places.csv` with a confirmed column
- [ ] Itinerary: order stops, attach dates, compute the running gain/loss

**Dashboard**

- [ ] Route + coordinates + hover summaries on a modern basemap
- [ ] Timeline scrubber and the ahead/behind ledger
- [ ] Historic (1872) vs current borders toggle
- [ ] Transport modes, mentioned-vs-visited places, detail panel
- [ ] Hungarian translation

**Maintenance**

- [ ] Tune `NEAR_MISS_RATIO` from the first full validation run

## Made by

made by [Crow Intelligence](https://crowintelligence.org/).

## License

MIT
