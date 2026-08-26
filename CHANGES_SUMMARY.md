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

## Green

`make ci`: 687 tests pass, ruff format and lint clean, `ty check src` clean, 93% overall.
