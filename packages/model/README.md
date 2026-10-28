# Personal Noise Score

A unit-level, hour-aware noise score for NYC apartments, built from public data with no key. The
prototype behind the Columbia HCD team project (Harry West, Fall 2026): one apartment, one renter, by
hour, with the ingredients shown. HowLoud's Soundscore scores a point on the map once for everyone; this
scores floor 2 differently from floor 6, night differently from day, and a light sleeper differently
from a heavy one.

## Run it

```bash
cd ~/code/noise-score
uv venv .venv && uv pip install -e ".[dev]"
.venv/bin/noise-score "158 Bedford Ave, Brooklyn" --floor 2 --position front --sleep light --bothers neighbors,people
```

The demo page and the API:

```bash
.venv/bin/uvicorn noise_score.api:app --reload
```

Then open http://127.0.0.1:8000/ for the form, or call the API directly:

```
GET /v1/score?address=158 Bedford Ave, Brooklyn&floor=2&position=front&sleep=light&wfh=false&bothers=neighbors,people
GET /v1/raw?address=158 Bedford Ave, Brooklyn        the untouched pulls behind the score
```

A cold address takes 3 to 8 seconds (seven public pulls); pulls are cached on disk for 7 days under
`.cache/`. Pass `--fresh` (CLI) or `fresh=true` (API) to bypass. An optional Socrata app token in
`NOISE_SCORE_SOCRATA_TOKEN` raises the rate limit.

## What it returns

- `score`: 0 to 100, higher is quieter, weighted by the renter's hours and sensitivities.
- `by_time`: the same score for night (10 pm to 5 am), early (5 to 8 am) and day (8 am to 10 pm).
- `street_only_score`: what a HowLoud-style model would say, one number, no floor, no building, no hours.
- `ingredients`: street, nightlife, building, sirens, construction (temporary), each with a score per
  window and the evidence lines a renter can check against their own apartment.
- `unit`, `building_facts`, `profile`, `sources`, `caveats`.

## How the number is made

1. Each ingredient becomes a pseudo-decibel exposure per time window: street from road class, lanes,
   speed and distance plus elevated subway proximity and vehicle complaints; nightlife from liquor
   licenses as point sources plus party complaints by hour; building from residential 311 complaints
   per unit per year shrunk toward the borough rate, plus construction era and type; sirens from
   hospitals, firehouses, ambulance and police stations within 600 m as point sources; construction from
   311 construction complaints and unexpired loud-work permits on the block.
2. Position adjusts them: floors above the first attenuate outdoor sources, rear units more, the top
   floor loses the upstairs neighbor, the first floor gains the lobby.
3. The renter's three answers add decibels to the ingredients they named (traffic, people, neighbors,
   sirens, construction) and weight the windows.
4. Ingredients combine by energy sum within a window, so one loud source dominates, as in a bedroom.
5. score = 100 - 2.5 × (level - 40).

Every constant is in `noise_score/config.py`, tagged to the matching entry in `DECISIONS.md`.

## Data

| Source | Dataset | Used for |
|---|---|---|
| NYC GeoSearch | geosearch.planninglabs.nyc | address to lat/lng, BBL, BIN |
| NYC 311 | erm2-nwe9 | every `Noise*` complaint within 150 m, 24 months, with hour and BBL |
| NYC PLUTO | 64uk-42ks | year built, floors, units, building class, commercial units |
| NYC Street Centerline | inkn-q76z | road type, travel lanes, posted speed, snow priority, geometry |
| DOB NOW approved permits | rbx6-tga4 | loud-work permits on the same tax block, with expiry |
| NYS Liquor Authority | 9s3h-dpkz | active licenses within 150 m, by type |
| MTA subway stations | 39hk-dx4f | elevated structures within 350 m |
| NYC Facilities Database | 67g2-p84d | hospitals, firehouses, ambulance and police stations within 600 m |

Socrata's `within_circle` on a line geometry matches its vertices, not the line, so roads are queried
at 300 m and measured in Python. On the Facilities Database it returns nothing at all, so the five
facility types are pulled citywide (about 400 rows, one cache entry for every address) and filtered to
600 m in Python.

## Layout

```
noise_score/
  config.py     every tunable number, tagged [M1]..[T7]
  sources.py    the eight pulls, cached
  model.py      pure scoring, no network
  api.py        FastAPI: /, /v1/score, /v1/raw
  cli.py        noise-score "<address>" [--floor n] [--position front|rear] [--sleep light|normal|heavy] [--wfh] [--bothers traffic,people,neighbors,sirens,construction] [--json]
  geo.py        haversine, point-to-line distance
  cache.py      7-day disk cache
web/index.html  the demo form and card
tests/          pure model tests: python -m pytest
DECISIONS.md    the math and technical decisions, defaults taken, what Rafa decides
```

## Caveats, said on the page too

311 counts measure who complains, not decibels. Street loudness is modelled, not measured. Elevated
subway proximity uses stations as a proxy for track. Construction is temporary. The liquor license says
what a place may be, not how late it runs. Sirens are modelled from where the vehicles start, not from
how often they leave.
