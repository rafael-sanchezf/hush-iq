# Hush IQ

A noise score for any NYC apartment, for the way you sleep. Built from the city's own records (311
complaints, building permits, liquor licenses, the street network, the subway, hospitals and firehouses), not
from reviews, and served to listing sites as an API so the answer sits next to the price.

Entry in the Meta Global AI Developer Hackathon, Oct 26 to Nov 4, 2026. `HACKATHON.md` says what existed
before the hackathon and what was built during it.

## Start here, product

Three taps (your sleep hours, whether daytime noise bothers you, what gets to you), then a verdict in words
against Manhattan: Very quiet, Quiet, Typical, Loud, Very loud, with each source ranked against Manhattan's
apartments and the evidence behind it. The hackathon adds a Meta-model layer that reads a listing for the floor
and the side, reads the block's building permits for what the counts cannot see, and writes the explanation
with citations it cannot invent.

- Live API: https://hush-iq-api.vercel.app (`/` lists every route; `/v2/score?address=...&floor=5&position=rear&sleep_from=23&sleep_until=7&bothers=people,traffic`; `/docs`)
- The iOS app: `apps/ios/`
- The method and every decision: `packages/model/DECISIONS.md`

## Start here, engineering

```
apps/ios          SwiftUI app and the NoiseKit package (prior work)
apps/web          the website: live demo, API docs, the page for listing sites (hackathon)
apps/extension    the Chrome extension: a score card on StreetEasy and Zillow listings (hackathon)
packages/model    the noise model, FastAPI, eight NYC datasets, Manhattan baseline (prior work, frozen); engine v2
services/agent    the listing reader: Muse Spark reads a listing's text and photos (hackathon)
services/verdict  the verdict writer: a paragraph whose every sentence cites its evidence (hackathon)
services/adjust   the permit reader: building permits read into a bounded adjustment (hackathon)
api/index.py      the one host: every route above on one Vercel origin (hackathon)
eval/             the 20-case eval, run on every change in CI (hackathon)
HACKATHON.md      the line between prior and new work, commit by commit
```

Run the model locally:

```bash
cd packages/model
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m noise_score.cli "140 Claremont Ave, New York" --floor 5 --position rear --sleep light
```

Run every route on one host, as Vercel does (keys in `.env`, never in git; without `MODEL_API_KEY` the reader
and the verdict writer answer with their rules and template and say so, and the permit reader adjusts nothing):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api.index:app --port 8000      # then open http://127.0.0.1:8000/ for the route index
```

Run the 20-case eval (no key, no cost) and the site, from the repo root:

```bash
(cd eval && python -m hush_eval run)            # mock mode; --ai off runs the services' own rules
(cd apps/web && npm ci && npm run dev)          # http://localhost:3100
```

## Data

All public, all from NYC Open Data and NYS Open Data, pulled live per address and cached. No scraping of
listing sites; a listing is read only when a renter pastes it on the site or clicks the extension on it.
