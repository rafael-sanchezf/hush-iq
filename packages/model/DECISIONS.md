# Decisions behind the Personal Noise Score

Written 2026-10-21 for the HCD team project (Pitch & Prototype due Tue 2026-10-27). Every number lives in
`noise_score/config.py` with the tag below next to it. "Default taken" means the code runs with that value
today; Rafa overrides any of them by changing the constant and re-running the three test addresses.

The user-facing claim the numbers have to support: HowLoud scores a point on the map once, for everyone.
We score one apartment, for one renter, by hour, with the ingredients shown.

## Math decisions

### M1. The scale (default taken: 0 to 100, higher is quieter, full range used)
Internally everything is a pseudo-decibel exposure, roughly facade dB(A). 40 is very quiet and maps to
100; 80 is very loud and maps to 0; score = 100 - 2.5 × (L - 40). Same direction as HowLoud so the two
are comparable on one slide.
Consequence: a 2nd-floor front unit over a Bedford Ave bar strip reads in the 20s at night, where HowLoud
would read around 55 to 65, because HowLoud's practical range is 50 to 100. **Decide:** keep the full range
(the spread is the story) or compress to HowLoud's 50 to 100 so a renter who has seen Soundscore is not
alarmed. If compressing: set SCALE_SLOPE to 1.25.

### M2. Three time windows (default taken: night 10 pm to 5 am, early 5 to 8 am, day 8 am to 10 pm)
MR's garbage truck at 4 am and LE's 1 am bar crowd are both "night" under this split. **Decide:** whether
"early" should start at 4 am so the truck gets its own window, or whether night should end at 7 am for
sleepers. Changing the boundaries changes which complaints land in which bar, nothing else.

### M3. Lookback and radii (default taken: 24 months; building = exact tax lot; vehicle and construction
complaints within 100 m; bars and party complaints within 150 m; roads within 60 m; elevated subway within 350 m)
24 months smooths small buildings; 12 months is fresher. 150 m is about one Manhattan avenue block.
**Decide:** 12 or 24 months, and whether the renter should see the radius on the "why" screen.

### M4. How ingredients combine (default taken: energy sum, not a weighted average)
L = 10·log10(Σ 10^(Li/10)). One loud source dominates, as it does in a bedroom: a quiet street does not
offset a bar below you. Same-street road segments are deduplicated before the sum. The alternative, a
weighted average of four sub-scores, is what a listing site would expect and is easier to explain on a
slide, but it lets three quiet ingredients hide one loud one. **Decide:** energy sum (physics) or weighted
average (explainability). If average: the four weights need choosing too.

### M5. Street loudness (default taken: modelled from NYC street centerline class, lanes, posted speed and
two-way flag; line source losing 3 dB per doubling of distance from 10 m; elevated subway station as a proxy
for the elevated line at 72 dB at 30 m, losing 4 dB per doubling; vehicle complaints within 100 m add up to
10 dB; night -5 dB, early -2 dB)
Arterial = 3+ travel lanes (66 dB); two lanes 60; one lane 56; highway 75; ramp 70; bridge 68; a DSNY
snow-priority "critical" street (bus and truck routes) adds 2. No traffic counts are used; NYC DOT's count dataset is sparse and HowLoud's federal
model is not public. **Decide:** whether to buy or license a traffic layer later, and whether the elevated
subway proxy (stations, not track) is acceptable for the demo. Truck routes and DSNY collection times
are not in; the 4 am garbage truck is a known gap.

### M6. Nightlife loudness (default taken: NYS liquor licenses within 150 m as point sources: club,
cabaret and "additional bar" 66 dB, hotels, caterers, breweries, theatres and "food and beverage" 62 dB,
restaurants 58 dB, all at 10 m, losing 6 dB per doubling, summed and capped at 75; grocery, liquor and wine
stores ignored; party, music and loud-talking complaints within 150 m add up to 12 dB by hour; early and day
-8 dB; a commercial ground floor adds 5 dB to floors 1 and 2)
The license list says what a place is allowed to be, not how late it runs. A restaurant with a 4 am
license and a club with a 2 am license get the same base. **Decide:** whether to pull closing hours (the
SLA license has none; Google Places does, at a cost per lookup) and whether Street/Sidewalk party
complaints belong to nightlife (as now) or split between street and nightlife.

### M7. Building loudness (default taken: residential 311 complaints at this tax lot per residential unit
per year, shrunk toward the borough rate with 20 unit-years of prior weight; a building at exactly the
borough rate is 46 dB, 10 dB per doubling of the rate, clamped 40 to 72; pre-war walk-up +4, pre-war
elevator +1, 1940 to 1999 +1, any walk-up +1; top floor -3; first floor +2; second floor over a shop +2;
complaint hours used when the building has 8 or more, else the citywide pattern)
Borough baselines were pulled 2026-10-21: Bronx 0.28, Brooklyn 0.11, Queens 0.09, Manhattan 0.07, Staten
Island 0.07 complaints per unit-year. Shrinkage matters: a 4-unit building with one complaint is 0.125 per
unit-year raw, 2× Brooklyn, but reads 1.1× after shrinkage. **Decide:** the prior weight (20 unit-years
now; 50 trusts the borough more, 5 trusts the building more), whether to show the raw rate or the shrunk
one on the "why" screen (code shows both), and whether 311 counts should be normalised against the
neighborhood (community district) instead of the borough.

### M8. Construction (default taken: a fifth, temporary ingredient: 311 construction complaints within
100 m and unexpired DOB NOW permits on the same tax block for general construction, structural,
foundation, earthwork, demolition, excavation support, sidewalk sheds and protection; night -15, early -3)
The deck tested four ingredients. Construction is the biggest 311 signal at 158 Bedford, so hiding it
would misstate the block, but it is temporary. **Decide:** show it as its own bar tagged "temporary"
(as now), fold it into Street, or drop it from the headline score and show it only as a flag.

### M9. Position (default taken: outdoor ingredients lose 1 dB per floor above the first, capped at 8;
rear units -8 dB, unknown -2, front 0)
There is no public data on which side a unit faces; the listing text sometimes says. **Decide:** whether
"unknown" should be treated as front (worst case, honest for a listing site) or as the -2 compromise.

### M10. The personal layer (default taken: light sleeper weights night 1.5× and early 1.2×; heavy sleeper
night 0.7×; working from home weights day 1.2×; each named bother adds 4 dB to that ingredient; default
weights night 1.0, early 0.6, day 0.6)
The three questions are the deck's: how you sleep, home by day, what bothers you. **Decide:** the size of
the bother bump (4 dB is "a bit louder than it is"; 10 dB is "twice as loud") and whether an unnamed
ingredient should be weighted down rather than the named one up.

### M11. Sirens (default taken: hospitals, firehouses, ambulance stations and police stations from the NYC
Facilities Database within 600 m as point sources: hospital 64 dB, firehouse or ambulance station 62, police
station 56, all at 50 m, losing 4 dB per doubling, summed and capped at 70; nothing within 600 m is 35;
night -3, early -2; floor and front/rear attenuate it like any outdoor source; "sirens" is a fifth bother)
A siren is the one sound that ignores the time of day and the double glazing, and every tester named it
unprompted. 4 dB per doubling sits between a point source (6) and a line source (3) because the vehicle
leaves along the street rather than sitting at the bay. The open data has no dispatch counts (FDNY runs are
per company per year, EMS calls are not geocoded), so the level is modelled from where the vehicles start,
not how often they leave. The street-only comparison leaves sirens out, because HowLoud does, so the two
numbers stay comparable. The dataset's `within_circle` returns nothing, so the five facility types are
pulled citywide (about 400 rows, one cached pull for every address) and filtered to 600 m in Python.
**Decide:** whether police stations belong. A firehouse and an ER run sirens around the clock; a precinct
house is mostly quiet by day and its cars often leave without one. Default in at 56 dB, 8 under a hospital;
lower SIRENS_BASE_DB["police"] or delete the key to take them out.

### M12. The Manhattan baseline (default taken: 300 sample points, stratified by community district,
probability proportional to residential units, seed 20261022; rank under the renter's own floor, side and
answers; floor capped at each sampled building's height)
The 0 to 100 score is absolute (M1): it says how loud, not how loud compared with what. Rafa's question of
2026-10-22, "why is mine 60 and not 80", has no answer on that scale alone. The baseline scores a sample of
real Manhattan apartments with the same model and ranks the renter among them: "quieter than 58% of
Manhattan apartments". Weighting by units means a 400-unit tower counts 400 times a brownstone apartment,
because the question is about apartments a renter could live in, not lots. The rank re-scores every sample
for the renter, as if they lived at the same height and side in each sampled building, so a light sleeper
who hates sirens is ranked against Manhattan for a light sleeper who hates sirens. What it does not do:
measure decibels. It grounds the number relative to the city through the same model; whether the model's
decibels match a sound meter is a separate test (the team's phone readings at the testers' apartments).
**Decide:** whether the headline on the app should be the percentile (default: shown beside the score,
not instead of it), and whether to extend the sample to all five boroughs (about four times the pulls).
Rebuild with `python -m noise_score.baseline build`; the file records the config hash it was built with,
so a constant change in `config.py` means a rebuild.

### M13. What the renter sees (default taken: a five-step verdict against Manhattan, decibels by time of day, no 0 to 100 score)
Rafa's call of 2026-10-22 after the app put "39 out of 100" beside "quieter than 53%": a 0 to 100 number
that is neither decibels nor a percentile reads like a failing grade and hides what is inside it. The
renter now sees three kinds of number, each one thing only. The verdict (Very loud, Loud, Typical, Quiet,
Very quiet, one fifth of Manhattan each) comes from the M12 rank under their answers. The decibels per
time slot are the physical estimate at the window, the same for anyone in the unit, with no answer bumps.
The percentile is shown as written ("quieter than 53%"). The internal scale (M1) still exists in the model
and the API for comparisons, but no screen shows it. The street-only comparison is dropped from the app.
`baseline.verdict` and `baseline.window_rank` in Python, `Verdict` and `Baseline.windowRank` in Swift.

## Technical decisions

### T1. Stack (default taken: Python 3.12+, FastAPI, httpx, uv; one GET endpoint plus a static demo page)
Same language as cbs-monday and the Stats course. The API is `GET /v1/score?address=&floor=&position=
&sleep=&wfh=&bothers=` and returns the full JSON the page renders; `/v1/raw` returns the untouched pulls
for checking by hand. **Decide:** whether the demo for the video is the page at localhost:8000 (as built)
or screenshots pasted into the deck.

### T2. Data sources (default taken: eight public datasets, no key: NYC GeoSearch, 311, PLUTO, Street
Centerline, DOB NOW permits, NYS liquor licenses, MTA stations, NYC Facilities Database)
OpenStreetMap's Overpass API was the first choice for roads and bars; it was at capacity all afternoon on
2026-10-21 and is not in. **Decide:** nothing today; if the city endpoints prove slow, the fallback is a
nightly bulk pull of the 311 noise rows into SQLite.

### T3. Socrata app token (default taken: none; you supply one as NOISE_SCORE_SOCRATA_TOKEN)
Without a token the city rate-limits anonymous queries; with one (free, two minutes at
data.cityofnewyork.us, Profile, Developer Settings) the limit is per app. Needed before scoring 20 live
listings in one sitting. **Decide:** whether to register it under ras2369 now.

### T4. Caching (default taken: every upstream pull cached on disk for 7 days under `.cache/`)
A cold address takes 3 to 8 seconds (six serial pulls); a cached one is instant. **Decide:** nothing for
the demo; for a listing site the cache moves to a database keyed by BBL.

### T5. Unit inputs are typed, not parsed (default taken: floor and front/rear are form fields)
A listing site would pass them from its own fields. **Decide:** nothing today.

### T6. Where it runs (default taken: local only)
`uvicorn noise_score.api:app` on the Mac. Hosting it (Fly, Render, or a Vercel function like cbs-monday)
is about an hour and only matters if a teammate needs to click it without Rafa's laptop. **Decide:**
local for the video, or hosted so the team can try their own apartments.

### T7. Repo (default taken: `~/code/noise-score`, private, not yet pushed)
**Decide:** push to GitHub under rafael-sanchezf, and whether teammates get access.

## The next test from the decision slide, as the code answers it
"Score the testers' own apartments" is one command each:

    noise-score "<MI's address>" --floor <n> --position front --sleep light --bothers neighbors
    noise-score "<MR's address>" --floor 6 --position front --bothers traffic
    noise-score "<LE's address>" --floor <n> --bothers neighbors

Working means each says the number is right for their floor and their hours; the one it gets wrong says
which constant above to fix first.
