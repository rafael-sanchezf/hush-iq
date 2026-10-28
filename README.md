# Hush IQ

A noise score for any NYC apartment, for the way you sleep. Built from the city's own records (311
complaints, building permits, liquor licenses, the street network, the subway, hospitals and firehouses), not
from reviews, and served to listing sites as an API so the answer sits next to the price.

Entry in the Meta Global AI Developer Hackathon, Oct 26 to Nov 4, 2026. `HACKATHON.md` says what existed
before the hackathon and what was built during it.

## Start here, product

Three questions (how you sleep, what gets to you, your place), then a verdict in words against Manhattan:
Very quiet, Quiet, Typical, Loud, Very loud, with the decibels at your window by night, early morning and
day, and the evidence behind each source. The hackathon adds a Meta-model layer that reads a listing, adjusts
the score for what the datasets cannot see, and writes the explanation with citations it cannot invent.

- Live API: https://hush-iq-api.vercel.app (`/v1/score?address=...&floor=5&position=rear&sleep=light&bothers=people,traffic`, `/docs`)
- The iOS app: `apps/ios/`
- The method and every decision: `packages/model/DECISIONS.md`

## Start here, engineering

```
apps/ios        SwiftUI app and the NoiseKit package (prior work)
apps/web        the website: live demo, API docs, the page for listing sites (hackathon)
packages/model  the noise model, FastAPI, eight NYC datasets, Manhattan baseline (prior work, frozen)
services/agent  the Meta-model layer: listing reader, adjustments, verdict writer, voice intake (hackathon)
HACKATHON.md    the line between prior and new work, commit by commit
```

Run the model locally:

```bash
cd packages/model
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m noise_score.cli "140 Claremont Ave, New York" --floor 5 --position rear --sleep light
```

## Data

All public, all from NYC Open Data and NYS Open Data, pulled live per address and cached. No scraping of
listing sites; a listing is read only when a renter pastes it.
