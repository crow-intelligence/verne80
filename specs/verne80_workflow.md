# 80 Days Dashboard — Workflow & Prompt Pack

Companion to `verne80_spec.md`. This is the *how*: pipeline order, the Gemini vs NotebookLM
call, copy-paste prompt templates, and exactly where to drop the files you generate.

---

## 1. Tooling (same as always)

**pyenv** (match the pinned version), **uv** (deps + lock), **ruff** (format + lint),
**ty** (type check); docstrings + doctests + Hypothesis + pytest. Don't reinvent the
scaffolding — copy `pyproject.toml`, `.python-version`, ruff/ty config, test layout and CI
from the example projects in `~/projects` (keyflux, lexograph, kenon, chronowords).

---

## 2. Step 1 — Claude Code: acquire and slice the text

**Task A — acquire.** Fetch Project Gutenberg #103 (English, public domain). Keep the raw
download untouched in `data/raw/` as the provenance record; never edit it in place.

**Task B — slice into chapters.** Strip the Gutenberg header/footer boilerplate, the table of
contents, and any transcriber notes. Emit **one plain-text file per chapter**.

Requirements:
- 37 chapters. **Assert the count** — if it isn't 37, stop and report rather than guessing.
- Filenames: `chapter_01.txt` … `chapter_37.txt` (zero-padded — this is what makes everything
  downstream sort and join correctly).
- Each file starts with the chapter number and title, then the body.
- Also emit `data/chapters/index.json`: chapter number, title, word count, first line — a
  cheap sanity check that the split is clean.
- Verify no chapter is suspiciously short/long (a classic sign the regex caught a TOC line).

---

## 3. Step 2 — the extraction question: Gemini or NotebookLM?

**Recommendation: Gemini UI for both extraction and summaries. NotebookLM as a companion,
not the extractor.**

The deciding argument is a structural one, and it's worth stating plainly because it's easy
to get backwards:

> **Exhaustive extraction is not a retrieval task.**

NotebookLM is RAG over your sources — it retrieves the *chunks most relevant to your question*
and answers with citations. That is excellent for "where does Fogg's money go?" and terrible
for "list every place named in Chapter 12", because retrieval returns what seems relevant, not
everything. You'd get a plausible subset with no signal about what it missed. Pasting the full
chapter into Gemini puts **100% of the text in context**, which is what enumeration needs.

Add to that: NotebookLM's output is conversational/report prose, schema compliance can't be
pinned down as tightly, and getting clean per-chapter JSON out of it is awkward.

**Where NotebookLM genuinely wins — use it for these:**
- Upload the whole book and ask cross-chapter questions to *audit* your extractions
  ("list every mention of money in order" — then diff against your CSV).
- Background for the adult-register text: empire, steamships, the 1872 rail network.
- Its **audio overview** is a legitimately fun bonus for a six-year-old.

**Efficiency win:** do extraction *and* summary in **one prompt per chapter**. 37 pastes, not
74. Template in §4 does both in a single JSON response.

**Model setting:** use Gemini's most capable model, temperature low if exposed. Paste the
chapter text in full.

---

## 4. THE PROMPT TEMPLATE (one per chapter, does extraction + summary)

Replace `{{N}}` with the zero-padded chapter number and `{{CHAPTER_TEXT}}` with the file
contents. Everything else stays byte-identical across all 37 runs — consistency is what makes
the outputs mergeable.

````
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
````

**Why the evidence quotes matter.** They turn verification from "reread the chapter" into a
string search: a script greps each quote against `chapter_NN.txt` and flags any that doesn't
match verbatim. Hallucinations don't survive that check. Have Claude Code write this validator
in step 4 — it's the single highest-value piece of QA in the project.

**If you'd rather split the tasks**, run the same template twice with the unused fields
deleted. But one pass is fewer pastes and guarantees the summary and the extraction agree.

---

## 5. Step 3 — WHERE TO PUT THE FILES

```
verne80/
├── data/
│   ├── raw/                     # Claude Code: untouched Gutenberg download
│   ├── chapters/                # Claude Code: chapter_01.txt … chapter_37.txt + index.json
│   ├── extractions/             # ← YOU DROP GEMINI OUTPUT HERE
│   │   ├── chapter_01.json
│   │   └── …  chapter_37.json
│   ├── review/                  # human-corrected gazetteer resolutions (step 5)
│   └── processed/               # merged + geocoded artefacts the dashboard reads
├── notebooks/
├── src/verne80/
└── web/                         # the dashboard itself
```

**Rules for `data/extractions/`:**
- One file per chapter, named **exactly** `chapter_NN.json` (zero-padded) to match
  `data/chapters/`.
- Paste Gemini's response raw. If it wrapped the JSON in ```json fences, strip them — or just
  let the loader tolerate them (tell Claude Code to handle both).
- If the summaries come from a separate run, put them in `data/summaries/chapter_NN.json`
  with the same convention.
- **Commit these.** They're small, hand-verified, and expensive to regenerate — they are
  project data, not build output.

---

## 6. Step 4 onward — back to Claude Code

1. **Load + validate.** Parse all 37 JSONs against the schema. Run the evidence-quote
   validator from §4. Report anything that fails — that's your review queue.
2. **Resolve places.** Unique `name_in_text` → Wikidata/GeoNames → modern name + coordinates.
   Emit `data/review/places.csv` with a confirmed column; **you eyeball it** before it reaches
   the map (tens of rows).
3. **Build the itinerary.** Order stops by chapter, attach dates and schedule status, compute
   the running gain/loss for the timeline scrubber.
4. **Build the dashboard** in `web/`.

---

## 7. Aesthetic alignment (from the live Crow dashboards)

Match `magyar-dalszovegek` and `chokepoints` — the house pattern is consistent and worth
following exactly:

- **Section rhythm:** each section = `h2` heading → **one short plain-language paragraph
  explaining what you're looking at** → the interactive viz. That explanatory sentence is a
  signature of the house style; it's also exactly what a parent reads aloud.
- **Palette:** the lyrics dashboard sets `theme-color: #7a1f1f` — deep maroon. Use the Crow
  palette; don't invent one.
- **Interaction:** dropdown/selector-driven, with legends that toggle series. Simple controls,
  no dense chart-junk.
- **Site chrome:** Crow Intelligence header nav (Portfolio / Services / About / Blog /
  Contact), prev/next footer links, `hello@crowintelligence.org`, CC BY-NC-SA 4.0.
- **Meta:** proper OG tags + an `assets/og.png` card, meta-description, skip-to-content link.
- **Closing "About the project" section** — data sources, method, tools used, licence. Both
  live dashboards do this and it's the credibility anchor. Here: Gutenberg #103, Gemini
  extraction, human verification, Wikidata resolution, `historical-basemaps` for 1872 borders.
- **Language:** build in **English**. A Hungarian version may follow, so make it a translation
  job, not a rewrite: keep every user-facing string in one place (a single strings/i18n file or
  language-keyed fields like `summary_hover.en`), never hardcoded in markup. Retrofitting this
  after 37 extraction files and a full UI exist is the expensive version. The lyrics dashboard
  is Hungarian-first, so a bilingual Crow site is already the norm.

---

## 8. My honest take on the project

**The workflow split is right.** Deterministic work (slicing, joining, geocoding, rendering) to
code; reading-comprehension work (who/where/when) to an LLM with a human check. That's the same
division we landed on for Homer, and it's the correct one.

**The biggest risk is the money field**, and it's worth naming: Verne is not systematic about
Fogg's spending. Ask 37 times "how much is left?" and a model will happily produce 37 numbers,
most of them invented, all of them plausible. Hence the explicit warning in the prompt and the
null-by-default schema. Treat any complete-looking money series with suspicion — the honest
version of that chart probably has gaps, and the gaps are the truth.

**The evidence-quote trick is the thing I'd keep** even if you drop everything else. It converts
verification from a reading task into a grep, which is what makes 37 chapters × ~6 fields
tractable for one person.

**Scope-wise:** MVP is route + coordinates + hover summaries on a modern map. That's already
worth publishing. The timeline scrubber and the 1872-border toggle are what make it *good* —
but they're increments, not prerequisites.

**One thing to get right early:** keep user-facing strings in one place from day one. English
now, Hungarian plausibly later — that's a translation job if the text is centralised and a
rewrite if it's scattered through the markup.
