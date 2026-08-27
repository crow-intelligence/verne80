# Changes summary — the globe

Two PRs. `globe/payload` builds the six JSON files and nothing that draws them, so its
review is a readable data diff. `globe/page` draws them: the globe, the typography, the
itinerary, the chrome.

## What this PR does

**`scripts/08_dashboard.py`** joins the four artefacts the pipeline already produces —
Fogg's itinerary, the resolved places, the per-chapter positions, the extracted summaries —
plus the Natural Earth coastline, into `web/data/{journey,places,chapters,land,strings,
provenance}.json`. It reads nothing from the network and decides nothing new.

**`src/verne80/globe.py`** holds the payloads, the great-circle arcs, the rotation helper
and `TRANSPORT_STYLE`. **`src/verne80/basemap.py`** holds coastline winding and rounding.
**`src/verne80/strings.py`** holds the string catalogue. **`src/verne80/sources.py`** gains
`GeoJSONSource` and `LAND`; **`scripts/00_fetch.py`** gains `--only book|land`.

**`web/data/` is committed**, with `tests/test_dashboard_data.py` re-running the export and
failing if the committed files have drifted from their inputs. Pages serves what is in the
repository and there is no build step at deploy time. The cost is that a place correction is
a two-file commit.

## Bugs found while building it

**The winding convention, which I got wrong twice before the page proved it.** d3-geo reads
polygons spherically, so a ring wound the wrong way fills its own complement: the ocean inks
and the continents become holes punched in it.

The trap is that **d3-geo wants clockwise exterior rings, the opposite of RFC 7946**. I first
assumed Natural Earth was already RFC-compliant and needed nothing; then decided it was
ESRI-wound and normalised it *to* RFC 7946 — which is what actually broke it, and the first
render of the page came back with a blank white globe. Asking d3 settles it in one line:

```
geoArea({type:"Polygon", coordinates:[oneDegreeSquareClockwise]})  //  0.000305 — the square
geoArea({type:"Polygon", coordinates:[sameSquareCounterClockwise]}) // 12.566066 — the world
```

Natural Earth follows the ESRI convention, so `ne_110m_land` was right for d3 all along and
`normalise_winding` now leaves all 127 of its rings alone. The function still earns its keep:
it makes "wound the way d3 reads it" a checked fact, and the historic-borders GeoJSON coming
next *is* RFC 7946 and will need every ring turned. `ring_area` is now signed so positive is
the area d3 will fill — the number that decides what you see, not the one a standard prefers.

Two tests pin this down so it cannot drift again: one asserts the clockwise square is the
small one, quoting the d3 command that proves it; the other asserts Natural Earth needs no
reversal at all, so a future release that switches convention fails loudly rather than
quietly painting the sea.

**Three bugs Hypothesis found, all fixed in the module rather than papered over in the test:**

- An edge spanning exactly 180° of longitude resolved to `-π` whichever way it was walked, so
  a ring and its reverse disagreed by `2π` instead of by a sign.
- `normalise_winding` was not idempotent for a ring of zero area: it reversed on the sign of
  its own rounding error, and flipped back and forth for ever. Rings below `1e-12` steradians
  are now left alone, since they have no winding to get wrong.
- `ring_area`'s contract promised a magnitude within `4π`. That is only true for a ring that
  does not cross itself; one that winds round the world twice accumulates more. The contract
  now says so instead of asserting something false.

**`journey_payload` documented dropping a rejected stop's coordinates and did not do it.**
Caught by the test written from its own contract.

**The plan's geography was wrong and the docstring now carries measurements instead.** Leg 0
does not "fly over Germany and Turkey": its arc runs over eastern France, the Alps and the
Adriatic, passing about 450 km from Paris, 700 km from Mont Cenis and 360 km from Brindisi.
Those are computed figures, not remembered ones.

## Decisions that change the numbers

Each is a parameter with its default stated in the docstring.

**`DRIFT_RATIO = 1.0` (`globe.py`) — new, and it withholds a pin.** A waypoint further from
the leg it is placed on than that leg is long is treated as contradicting the curation, and
is listed rather than drawn. The arcs are schematic, so a legitimate waypoint can be a long
way off one: Singapore is 2,422 km from the Calcutta–Hong Kong arc because the steamer went
round the Malay peninsula. Measured against leg length, every honest waypoint is at 0.84 or
below and Queenstown is at 3.3, so the threshold sits in a real gap. **This is the one
behavioural decision in the PR that a human should confirm.** Its effect today is exactly one
place: Queenstown drops out of the default layer, and 202 rather than 203 places are drawn.

**`ARC_SAMPLES = 64`.** Points per leg. Puts a waypoint within ~130 km of its position on the
longest leg, finer than the dot that marks it.

**Coordinate rounding to 2 decimal places** in the coastline: about 1.1 km, below what 1:110m
resolves. 150 KB becomes 76 KB and the land fraction is unchanged at 28.9%.

**`DOUBTFUL_BELOW` is imported from `reviewmap.LOW_CONFIDENCE`, not restated**, so the QA map
and the public globe cannot come to disagree about what "doubtful" means.

## What needs a human

**1. Queenstown, and it is the highest-value ten minutes here.** Chapter 33's Queenstown is
Co. Cork — the transatlantic packet port, now Cobh — and the gazetteer resolved it to Otago.
I have not asserted a QID. The fix is a two-cell edit in `data/review/places.csv`
(`corrected_qid`, or `n` in `confirmed` to drop it), then `make dashboard`.
`test_queenstown_is_held_back_until_somebody_resolves_it` is written to fail when this lands,
and its docstring says so.

**2. Sydenham is wrong and the drift check does not catch it.** It resolved to
Buckinghamshire rather than the London suburb — 240 km, which is 0.07 of leg 0, so it passes.
The check catches wrong-continent, not wrong-suburb, and that limit is worth knowing.

**3. Nothing is confirmed.** 0 of 342 rows. Every pin is drawn with a broken ring, which is
honest and meant to be temporary. 110 of 202 drawn places resolved below 0.7 confidence, and
the `named` layer of 177 unreviewed places demonstrably contains Dublin-in-the-United-States
and Cochin-China-in-France. That layer ships **off by default**, as agreed.

**4. Confirm `DRIFT_RATIO`.** See above.

## Left alone deliberately

**Dates.** The 106 date mentions are still free text (`"7th December"`). No day-of-80 axis,
so no scrubber. `chapters[].day` is absent rather than guessed — that field is the seam.

**Historic borders.** Not fetched. `places[].tier` and the land-only basemap are the seams:
the toggle becomes one more canvas layer, not a rewrite.

**Bending arcs through waypoints.** Deferred. A bent leg 0 would assert a straight run from
Mont Cenis to Brindisi, which is more invention than the straight line rather than less.
`legs[].arc_is` means a surveyed polyline later is a data change with no code change.

**`unwrap_eastward` and `split_at_antimeridian` are not reused.** They are Web Mercator
artefacts and an orthographic projection has no map edge. Worth stating because the failure
would be silent: `geoOrthographic` accepts an unwrapped longitude of `237.6` and renders it
correctly, so the machinery would not break — it would just sit there being a Mercator
assumption in a projection that has none. Both stay in `reviewmap.py`, which still needs them.

**Hungarian ships empty**, not machine-translated: 62 keys reported as the translator's
worklist. An empty key falls back to English visibly; a guessed one reads as finished work.

## PR 2 — `globe/page`

**The page.** `web/index.html`, `style.css`, `globe.js`, `app.js`, `i18n.js`. Canvas for the
sphere, coastline and arcs; an SVG overlay for the nine stops, so each one gets a focus ring,
an accessible name and a 28px touch target without any hit-testing on the canvas. Drag to
turn, auto-rotate after twenty seconds idle with a real pause control, an itinerary as a
visible ordered list, and the provenance counts above the fold rather than in a footnote.

**Vendored, not fetched.** `d3-geo` 3.1.1 with `d3-array` and `internmap`, 57 KB, each
bundle's CDN imports rewritten to point at the file next door. `tests/test_web_page.py`
fails if one goes back to fetching itself.

**`versor` was fetched and then dropped.** It gives "the point you grabbed stays under the
cursor", which rolls the horizon — wrong for an atlas that reads north-up. The drag moves two
angles with the roll pinned at zero, the same decision as `globe.shortest_rotation`.

**Type, self-hosted.** Playfair Display and EB Garamond, Latin and Latin-Ext only, 312 KB
across 8 files — an English reader downloads about 113 KB of that. `scripts/fetch_fonts.py`
is reproducible and writes both OFL texts beside the fonts, which the licence requires.
EB Garamond is a variable font and the API serves the same bytes for 400 and 600, so the
faces are deduplicated by content hash and declared with a weight range; without that the
page shipped 158 KB twice.

**The camera does not centre on London.** Centring on a stop at 51 degrees north points the
globe at the Arctic and puts most of the journey over the horizon, so the view sits on
London's meridian at the route's own mean latitude, about 34.

## What is still only checked by eye

Canvas output, drag, font features and contrast are not a pytest's business. `web/globe.js`
opens with the list: Antarctica white not black, no clickable dots on the far side, no roll
while dragging, auto-rotate stopping on touch and never starting under reduced motion,
old-style figures in the prose and tabular ones in the day column.

Rendered and checked headless during this work: the globe draws, `?lang=hu` falls back to
English per key, the itinerary lists all nine stops with their modern names, and Queenstown
is absent from the last leg as intended.

**One thing the render surfaced for the review pile:** Calcutta resolved to *Kolkata
district* rather than the city, at 0.96 confidence. It is on the route and it is drawn.
Worth a `corrected_qid` alongside Queenstown and Sydenham.

## PR 4 — `globe/page` (continued): the cover, the caveats, and the borders

**The title echoes the Penguin cover** — two lines and an enormous numeral, Playfair for
the words and Abril Fatface (OFL, ~20 KB) for the 80 alone. The layout is the cover's;
the lettering is not, because that artwork is Penguin's. The heading still reads "Around
the World in 80 Days" to a screen reader, because the whitespace between the four spans
is real markup.

**SEO.** A subtitle saying what the page is, a 56-character `<title>`, a 160-character
description, and JSON-LD that describes the page as a `WebSite` *about* a `Book` rather
than as the book. The head's title and description are written into the markup rather
than filled by JavaScript, so a crawler that executes nothing still reads them — and a
test asserts the two copies match the string table.

**The `og:image` had been a 404 since the first commit.** Every share of this page has
unfurled without a card. `scripts/09_og_card.py` draws one with Pillow behind an optional
`og` extra; a test checks the PNG header rather than importing the library that made it.

**Removed:** the provenance box, the broken-ring note and the vestigial "The route"
heading with its great-circle sentence. The counts now live in one sentence in About,
filled from `provenance.json` so they cannot drift. The dashed rings went with their
explanation — an unexplained notation is worse than none — but `status` stays in the
payload, so the ring returns the day `places.csv` is reviewed.

**About the project** is rewritten from `about.txt`: made by AI with minimal human
intervention, the idea from the author's son, Gemini for the entities and the summaries,
Claude Code for the rest.

## The borders

Two eras, as hairlines over the coastline: **1880** and today, with a three-way control
that persists in `localStorage` and takes a `?borders=` override so a link can carry the
comparison. Default 1880.

**There is no 1872 file.** The source offers 53 years and the nearest to the novel is
1880, eight years after. The page says so under the control and again in About.

**The winding, which this module's docstring got wrong.** `basemap.py` predicted that the
historic layer would be RFC 7946 and would need every ring turned. It is not and it does
not — all 539 exterior rings of `world_1880` are clockwise, the same as Natural Earth,
because the file was exported from a shapefile. The prediction is deleted and a test
records the fact instead. `normalise_winding` still earns its place: two of the file's 31
holes are wound as exteriors, which d3 would fill as land.

**`_is_drawable` was not doing what its own docstring said.** It promised "whether a ring
still bounds an area" and only counted points. Ten rings in the 1880 borders round onto a
straight line at one decimal place — closed, four points or more, enclosing exactly
nothing — and reached the payload as zero-area exteriors whose winding could not be
corrected because they had none. It now checks the area too. The coastline is unaffected;
`land.json` is byte-identical.

**`land_payload` is now `outline_payload`**, because it serves two layers. Its closing
principle survives and improves: the output carries no country name, and for borders
drawn as hairlines that is the design rather than a limitation.

### Decisions that change what you see

**Unnamed features are dropped — 63 of the 1880 file's 236.** The largest is an
Antarctica the source attributes to nobody, spanning every longitude from −90° to −63.2°;
as a hairline that is a straight rule right round the globe. An unlabelled boundary
asserts a border the source itself declined to attribute. Every one of them keeps its
coastline from the land layer. Natural Earth *names* Antarctica, so the modern layer keeps
it — and its polygon closes at the pole, which an orthographic projection collapses to a
point rather than a line.

**`BORDER_PLACES = 1`** — about 11 km against roughly 30 km to the pixel, so a third of a
pixel. Takes the 1880 layer from 152 KB gzipped to 80. The coastline stays at two places.

### What needs a human

**The GPL-3.0 judgement.** `historical-basemaps` carries a plain, unmodified GPL-3.0 and
no separate data licence. verne80 is MIT and the page is CC BY-NC-SA 4.0.
`web/data/borders_1880.json` ships under GPL-3.0 with a `NOTICE` naming André Ourednik.
Whether copyleft in fact reaches a rounded, re-wound, feature-filtered extract of geometry
is a question of law, not of fact. It is recorded, not resolved.

**The 1880 layer's accuracy.** Its own README: *"It is work in progress: verify the maps
by comparison to other sources before using in academic work."* Quoted verbatim in About.

**The arcs are described nowhere on the globe.** The caveat was deleted on request. About's
method paragraph now states as neutral method that the route is drawn as great circles
between the stops the book names; say the word and that goes too.

## Green

`make ci`: 765 tests pass, ruff format and lint clean, `ty check src` clean, 94% overall.
