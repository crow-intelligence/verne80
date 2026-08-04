# Around the World in Eighty Days — an interactive map dashboard

*Le tour du monde en quatre-vingts jours* (Verne, 1872) as a NLP + GenAI demonstrator:
extract the route and the calendar from the text, resolve 1872 place names to modern ones,
and show the journey on a map that can be flipped between the world as it was and the world
as it is.

Origin: reading it aloud with a six-year-old. That's where the idea came from, but the
**audience is general** — anyone who knows the book, or wants to. Build in English; a Hungarian
version may follow.

---

## 0. The idea in one line

The novel already contains its own dataset. Fogg keeps an **itinerary with a column of gains
and losses**; the wager is a route *plus* a deadline. So the dashboard's job is not to impose
structure on the text but to make the text's own structure visible.

**Spine: a synchronised map + timeline.** Scrub through the 80 days; the map advances along
the route and a ledger shows whether Fogg is ahead or behind schedule. Where + when, together
— that's the book's actual tension.

**The toggle is the lesson.** In 1872 the route crosses a world of empires (British India,
Qing China, Meiji Japan, the young United States). The same route today crosses ~20 sovereign
states. Flipping *historic ↔ current* borders under a fixed route is the entire history lesson
in one interaction — the lines move while the route stays put, and no explanatory paragraph is
needed to make the point land.

---

## 1. Data sources (all checked, all open)

**Text** — Project Gutenberg #103 (English, HTML/plain text, public domain); French original
and translation also on Wikisource. Chapter-structured (37 chapters). Setting: the last
quarter of **1872**.

**Historic boundaries** (the load-bearing layer — verified to exist):
- **`aourednik/historical-basemaps`** — georeferenced world boundaries as **GeoJSON, one file
  per year-layer**, an auto-generated `index.json` listing available years, and documented
  Leaflet/D3 integration. This is the primary layer: right format, right period, drop-in.
- **CShapes 2.0** (ETH) — borders + capitals **1886–2019**, GeoJSON/Shapefile/CSV. **Note the
  start year: 1886 is 14 years after our 1872**, so CShapes is a cross-check for the modern
  end, not the source for the historic layer. (One GIS thread also flags its quality as
  uneven.) Cite Schvitz et al. 2022 if used.
- **Thenmap API** — GeoJSON/TopoJSON by date, but world borders only from **1945**; not usable
  for 1872. Listed here so nobody re-discovers this the hard way.

**Modern boundaries** — geoBoundaries (CC-BY) or Natural Earth.

**Gazetteer / name resolution** — Wikidata (has historical names, `followed by` / `replaced by`
relations, and coordinates), GeoNames for modern names, Pleiades only where relevant.

**Basemap** — a period-appropriate tile layer if one is licensable (David Rumsey's georeferenced
collection is the obvious candidate); otherwise a muted modern basemap styled to look old.

---

## 2. Pipeline

### 2.1 Segment
Split into the 37 chapters. Chapter is the unit of analysis — it's also how you read it aloud,
one chapter a night, so it matches the family use case.

### 2.2 Extract places and dates (NLP)
Per chapter: named entities (locations), and **dates/durations**. Verne is unusually explicit —
distances in miles, times in hours, arrival dates — so extraction gets real signal.

Two extraction targets, kept separate:
- **Route stops** — where Fogg actually *is* (London, Suez, Bombay, Calcutta, Hong Kong,
  Yokohama, San Francisco, New York, back to London).
- **Mentioned places** — everywhere merely *named*. Distinguishing these matters: the book
  name-drops far more geography than Fogg visits, and conflating them turns the route into mush.

Also extract **mode of transport** per leg (steamer, rail, elephant, sledge, wind-sled) — it's
half the charm and a natural map encoding.

### 2.3 Resolve names (the historically interesting part)
1872 → today, with the change itself as content:
Bombay→Mumbai, Calcutta→Kolkata, Madras→Chennai, Yokohama→Yokohama (unchanged), Suez→Suez,
Hong Kong→Hong Kong SAR, and so on. Store **both** names plus coordinates plus a
`name_changed: bool`. Wikidata is the resolution source.

**Human-in-the-loop:** a small review table where every resolution is confirmed or corrected
before it reaches the map. There are on the order of tens of route stops — this is an
afternoon, not a project, and it removes the main source of embarrassing errors.

### 2.4 Summaries (GenAI)
A summary per chapter/location at **two lengths** (length, not reading age — the audience is
general):
- **`summary_hover` (one sentence, ≤25 words):** fits a tooltip. What happens here.
- **`summary_detail` (3-4 sentences):** for the side panel — what happens, plus the historical or
geographic context the chapter itself supplies.

Generation is LLM; **verification is human.** Summaries are where hallucination would be easiest
and least visible, so: generate from the chapter text, keep it grounded in that chapter, and
eyeball every one. Tens of items — entirely feasible.

### 2.5 Reconstruct the timeline
Fogg's schedule is the second axis. Extract, per leg: departure, arrival, planned vs actual,
and the running **gain/loss** — the book hands you this in its own itinerary table. This drives
the timeline scrubber and the ahead/behind indicator.

*(The date-line twist at the end — the day gained travelling east — is the book's punchline.
It should be a deliberate reveal in the UI, not a spoiler on the front page.)*

---

## 3. The dashboard

**Layout:** map centre; timeline scrubber along the bottom; a chapter/place panel at the side.

**Core interactions:**
1. **Scrub the 80 days** — the route animates; the current leg highlights; the gain/loss ledger
   updates.
2. **Historic ↔ current borders** — one toggle, same route. The headline feature.
3. **Click a stop** — its two-register summary, the 1872 and modern name, the chapter link.
4. **Transport mode** — encoded on each leg (line style or small icon).

**Two summary lengths, used in different places** — `summary_hover` on tooltip, `summary_detail`
in the side panel when a stop is selected. Not a user-facing toggle; just the right length in the
right slot.

**Deliberately NOT included:** dense charts, analytics panels, anything that needs a methodology
note to interpret. The map and the clock carry the story; keep the controls to a handful.

**Aesthetic:** this is a **dashboard**, not an Aporia essay — the Aporia rule ("these are not
dashboards; they are arguments read beginning to end") means this one is explicitly the other
kind. Interactive, exploratory, warm and storybook-ish rather than austere. Look at
`kmdb_dashboard` in `~/projects` for reusable interaction and data-loading patterns.

---

## 4. Scope tiers

- **MVP:** route stops + coordinates + modern names + hover summaries + a static route on a
  modern basemap. Already worth publishing.
- **+1:** the timeline scrubber and the gain/loss ledger.
- **+2:** the historic-boundaries toggle (the payoff).
- **+3:** mentioned-vs-visited places, transport modes, period basemap, detail panel.
- **+4:** Hungarian translation (keep strings centralised from the start so this stays a
  translation, not a rewrite).

---

## 5. Tooling

**Project setup as usual:** pyenv, uv, ruff, ty; docstrings + doctests + Hypothesis + pytest;
copy the scaffolding from the example projects in `~/projects` (keyflux, lexograph, kenon,
chronowords) rather than reinventing it.

**Extraction:** spaCy NER + an LLM pass for the harder date/leg reasoning; the data artefact is
a small committed JSON (stops, coordinates, names, dates, summaries) so the front end never needs
the model at runtime.

**Front end:** Leaflet (both boundary datasets ship GeoJSON, and `historical-basemaps` documents
Leaflet integration directly). Deploy static.

---

## 6. Why this is a good demonstrator

It shows the full modern stack on a text everyone knows: **NER → gazetteer resolution → LLM
summarisation → human verification → interactive geo-visualisation.** The 1872-vs-now toggle
makes a point no static map makes — that the borders moved and the route didn't. And it's small,
finishable, and built on a text a general audience already knows, which is rare for a data project.
It also has a built-in first reader at home who will say immediately if it's boring.

Downstream: a natural post for the technical blog (#8), and a genuinely charming portfolio piece.
