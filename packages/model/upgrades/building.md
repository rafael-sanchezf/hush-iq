# Neighbors upgrade (source "building")

Code: `noise_score/upgrades/building.py`. Data: `noise_score/data/upgrades/building.json.gz` (409 KB, Manhattan).
Today counts 311 residential noise complaints per apartment at the building. It does not know what kind of
building it is. This module keeps today's level and adds a capped correction, the same for every time slot.

## Inputs
Today: the level per slot, floors and the commercial flag (facts), apartments on the lot (PLUTO).
New: building class, apartments per floor, short-stay listings within 150 m, apartments within 150 m.
The tax lot is found by the bbl in the facts, else the best lot centre within 30 m (up to 150 m for big lots).

## Datasets
| Name | Id | URL | Window |
|---|---|---|---|
| NYC PLUTO | 64uk-42ks | data.cityofnewyork.us/resource/64uk-42ks | version 26v2, 32,390 Manhattan lots, 958,418 apartments |
| 311 Service Requests, Noise - Residential | erm2-nwe9 | data.cityofnewyork.us/resource/erm2-nwe9 | 2024-10-28 to 2026-10-28, 121,434 complaints on those lots |
| Inside Airbnb, New York City | listings 2026-09-14 | insideairbnb.com/get-the-data | one scrape; 8,922 Manhattan entire homes, 950 under 30 nights |

Inside Airbnb is licensed CC BY 4.0: credit "Inside Airbnb, insideairbnb.com, New York City, 2026-09-14".

## Formula in plain words
1. Type. For each building class, take the 311 noise complaints of the latest 12 months and divide by what
   today's formula expected from the 12 months before. Elevator co-ops drew 0.24 of the expected, condominiums
   0.48, the other elevator classes D1, D3, D5 and D9 1.7 to 2.2. Adjustment = 0.5 x 10 x log2(ratio / typical
   ratio), kept within plus or minus 6. "Typical" is the apartment-weighted average (0.69).
2. Hallway. Apartments per floor = apartments / (floors x buildings on the lot). Above the Manhattan typical
   (6.8), add 0.5 per doubling, at most 1.5. Nothing below typical.
3. Short stays. Entire-home listings within 150 m with a minimum stay under 30 nights and a review in the last
   year, per 1,000 apartments within 150 m. Add 0.5 per listing per 1,000, at most 1.0.
4. Level = today + (type + hallway + stays, kept within plus or minus 7), same in every slot, between 30 and 80.

## Constants
Sourced: typical apartments per floor 6.8 (PLUTO, apartment-weighted median); radius 150 m and the 30-night line
(Inside Airbnb blur, NYC short-term rental law); the class table (311 against PLUTO).
Judgment: type share 0.5 (half of a gap is who calls 311, not loudness); thin-class prior 25 complaints; type cap
6; hallway 0.5 per doubling, cap 1.5; stays 0.5 per listing per 1,000, cap 1.0; total cap 7; level range 30 to 80;
match distances 30 m, 150 m, lot radius x 1.5 (checked on 120 geocoded addresses: 114 right, 6 geocoder errors).

## What the data said
Held-out check: fit on a random half of the lots, predict the other half's latest 12 months from the 12 before.
Type alone cuts the Poisson deviance of today's level by 6.3% (8 splits, spread 0.5). Hallway alone: -0.16%.
Stays alone: -0.02%. Adding either to type changes nothing worth the weight.

## Rejected
- HPD Complaints and Problems (ygpa-z7cr): 60 categories in Manhattan, none about noise or neighbors.
- Floors as a correction: complaints per apartment fall with height (-0.25 per doubling, t -2.6); the engine
  already applies floor effects later. Total apartments: also negative. Built in 2000 or later: t -2.2, +0.1%.
- Neighborhood (community district): the best single predictor (12% against 4% for class, with no complaint history) but it is where you
  live, not the building; street and nightlife already carry place.
- Short stays at the building: not possible, Inside Airbnb moves each listing up to 150 m on purpose.
- NYC health surveys: report noise by household, not by building type, in the tables I found.

## Limits, worst first
1. Hallway has no support. On top of today and class, more apartments per floor goes with fewer later
   complaints (-0.17 per doubling, t -3.6): elevator buildings with 14 to 20 per floor draw 0.045 per apartment
   a year, 6 to 8 per floor draw 0.095. Kept at a small judgment weight because the owner asked for it. Set
   `HALLWAY_PER_DOUBLING = 0` to remove it.
2. Complaints are the only yardstick. Co-op and condo residents may call 311 less, so the type gap mixes
   quiet with silent. Half weight, cap 6, and 37% of apartments sit at the cap.
3. Short stays barely exist in the data (0.1% of apartments), blurred by up to 150 m, and 311 shows no signal
   (t -0.2). After Local Law 18 this is an area hint, nothing more.
4. Class ratios come from 12 + 12 months; today uses 24. A longer record needs less help, so the move is a bit
   large for buildings with many complaints.
5. Matching by centre: a wrong geocode gives a wrong or no lot (4 of 120 here). A miss leaves today unchanged.
6. Today's own floor at 40 ties half of Manhattan; the type step is what breaks those ties.
7. The artifact is a snapshot of 2026-10-28. Rebuild with `building.build(DATA)`.

## Result on the 300-building baseline (298 distinct)
All 298 matched. Rank correlation with today (slot-averaged) 0.77. Spread (sd) 7.2 to 9.6; distinct values 108
to 229. Biggest moves up: 115 Pitt Street, 95 Wall Street, 2410 8 Avenue (elevator rentals, +6 type). Biggest
moves down: elevator co-ops on La Guardia Place, East 4th, Morton and West 23rd Street (-6 type).
