# The extraction prompts — how to run them

Thirty-seven prompts, one per chapter, each with its chapter embedded verbatim. You paste
them into Gemini; the JSON that comes back goes into `data/extractions/`.

## Why by hand, and why Gemini rather than NotebookLM

Exhaustive extraction is not a retrieval task. NotebookLM is RAG over your sources: it
returns the chunks most relevant to a question, which is excellent for "where does Fogg's
money go?" and wrong for "list every place named in chapter 12" — you would get a
plausible subset with no signal about what it missed. Pasting the whole chapter puts 100%
of the text in context, which is what enumeration needs.

NotebookLM still earns its place as a companion: upload the whole book and ask
cross-chapter questions to *audit* these extractions afterwards.

## Regenerating the prompts

```bash
uv run python scripts/02_prompts.py
```

The `chapter_NN.txt` files are gitignored — they are chapter text plus a constant, and
reconstruct byte-identically from the committed chapters and the template. `manifest.json`
is committed, and records the template's fingerprint alongside each prompt's and each
chapter's, so a later run can tell whether an extraction was produced under these exact
instructions and against this exact text.

## The paste workflow

For each chapter, in order:

1. Open `data/prompts/chapter_NN.txt`, select all, paste into Gemini.
2. Use the most capable model available. Set temperature low if it is exposed.
3. Save the response to `data/extractions/chapter_NN.json` — zero-padded, matching the
   chapter filename. If the response came wrapped in a ```` ```json ```` fence, or with a
   line of preamble before it, leave it: the loader peels both off.
4. **Validate every few chapters, rather than batching all thirty-seven:**

   ```bash
   uv run python scripts/03_validate.py --chapters 1-5
   ```

   Finding a systematic problem after five pastes costs five pastes. Finding it after
   thirty-seven costs thirty-seven.

To see what is still outstanding:

```bash
uv run python scripts/03_validate.py --missing-only   # not yet pasted
uv run python scripts/03_validate.py --stale-only     # pasted under an older prompt
```

## The `narrative` block, and why it exists

The map has to know where Fogg's party actually is in each chapter, and `places_visited`
cannot say. Chapter 5 lists London, the Reform Club and Scotland Yard as its settings while
Fogg is already on a train to Paris. Chapter 6 is set at Suez, where Fix is waiting and the
party has not yet arrived. The chapter's setting and the party's position come apart in both
directions, so position has to be resolved from who was actually on stage.

Note what the block does *not* ask: it never asks where Fogg is. Chapter 5 does not say, and
asking would invite exactly the invention rule 1 forbids. It asks who is physically in this
chapter's scene — which one chapter can answer on its own — and lets an empty `on_stage`
array be the signal that the travellers were elsewhere.

**Chapter 5 is the acceptance test for the whole change.** Its `on_stage` should hold the club
members and Lord Albemarle; Fogg belongs in `named_but_not_present`. If the model puts Fogg on
stage there because the chapter is *about* him, tell me — the fix is a sharper warning in the
prompt, not code, and it is worth catching now rather than at chapter 37.

## What the validator checks, and what it does not

Every extracted item carries a verbatim quotation from its chapter. The validator greps
each one back against `data/chapters/chapter_NN.txt` — the same bytes the prompt embedded —
and sorts the results:

| verdict | meaning | blocks the run |
|---|---|---|
| `exact` | found character for character | no |
| `normalised` | found once line wrapping and curly punctuation are folded | no |
| `case_insensitive` | found, but the capitalisation was changed | no, warns |
| `ellipsis` | the fragments around a `...` all appear, in order | no, warns |
| `near_miss` | close to a real passage, but not it | no, warns |
| `missing` | nothing in the chapter resembles it | **yes** |

`--strict` blocks on anything short of a clean match. The warnings land in
`data/review/evidence_queue.md` with the closest real text, its line number and a diff, so
fixing one is a copy-paste.

What this cannot check is whether a *correctly quoted* passage was interpreted correctly —
whether the place really is where Fogg is, rather than somewhere he mentions. That is what
your eyes are for, and it is why there are only thirty-seven of these.

The one field to be suspicious of is **money**. Verne is not systematic about Fogg's
spending; most chapters state no amount at all, and an empty `amounts` array is the correct
and expected answer. Ask thirty-seven times "how much is left?" and a model will produce
thirty-seven plausible numbers. If a money series comes back looking complete, that is the
warning sign — the honest version has gaps, and the gaps are the truth.

## One divergence from `specs/verne80_workflow.md`

The workflow document says to substitute the zero-padded chapter number for `{{N}}`. The
template line is `"chapter": {{N}},`, and `"chapter": 07` is not valid JSON — a leading
zero is a parse error. So `{{N}}` renders as a plain integer (`"chapter": 7,`) and
zero-padding stays where it belongs: in filenames.
