# Construction upgrade

Code `noise_score/upgrades/construction.py`, artifact `noise_score/data/upgrades/construction.json.gz` (222 KB),
tests `tests/test_upgrade_construction.py`, rebuild `construction.build(DATA, cache_dir=...)` (5 seconds with the
pulls cached, a few minutes without). Today's level counts building permits and 311 complaints with a blanket
night offset. This upgrade adds street work and after-hours work, and merges them with today's level without ever
adding two decibel levels: both describe the same construction sound.

## Inputs

- `lat`, `lng`; `today`, the frozen model's construction level per slot at a facade-neutral unit; `facts` is not used.
- The artifact: 12,520 places on Manhattan streets with 20,336 street-work records (days with a permit, active on
  the build date, hours stated for night and early work), and 989 after-hours variance sites. Built 2026-10-28.

## Datasets (window 2025-10-30 to 2026-10-28, Manhattan, no key)

Each at `https://data.cityofnewyork.us/resource/<id>`.
- Street Construction Permits 2022 to present, `tqtj-sjs8`: 63,181 permit rows used (street openings, sidewalk work,
  DOT paving and milling, crane or shovel on the street). 97.6% placed on a street; 2.4% not (ramps, highways, rail).
- DOB After Hour Variance Permits, `g76y-dcqj`: 147,964 daily variance rows, window plus 60 days ahead; 740 had no
  coordinates. Latitude and longitude come with the data.
- NYC Street Centerline, `inkn-q76z`: 14,113 segments, used to place permits (below).
- Cranes, `hcv3-zacv`: read and not used. It adds a crane type (96% mobile) to permits already counted.

## Placing a permit

1. Names are normalised (East to E, Street to ST) and matched to the centreline. Cross streets meet at a shared
   segment end. "From X to Y" gives a block; "from X" alone gives that corner. A house number, when present (23% of
   permits), places a point on the block by interpolating its address range.
2. A block is not a point: at request time distance is averaged along it (one sample per 25 m).

## The formula in plain words

1. Distance weight: 1 within 20 m, a straight line down to 0 at 100 m.
2. Street intensity = sum over nearby work of kind weight x distance weight x (days with a permit / 365, plus 0.25
   if active on the build date). Kind weights: heavy 1.0, repair 0.6, light 0.2. Permits for one job at one place
   are merged (days are a union, not a sum).
3. Day level = today's day level + 3 dB x log2(1 + intensity) x (1 - 0.6 x how near today is to its ceiling), at most 9 dB.
   The ceiling share is (today's day level - 40) / 25.
4. Share of nights with work = 1 - product over sites of (1 - distance weight x kind weight x night hours with a
   permit / (7 x 365)), at most 0.8. Sites are variance sites (weighted by reason and by enclosed work) and DOT permits
   whose text states night hours ("work 11pm-7am nightly"). Early mornings use 5 to 7 am only, over 2 x 365.
5. Night level = energy average of a work night at the day level above and a quiet night at today's night level,
   weighted by the share. Early level the same. No level is ever lower than today's.
6. No work within 100 m: today's levels, unchanged, with one sentence saying so. Artifact missing: today's levels.

## Constants

Sourced: base 40, 3 dB per doubling, ceiling 25 (today's model, `config.py`); slots of 7 and 3 hours; window 365 days
and reach 100 m (the brief); variance statuses "AHV Permit Issued" and "Approved".
Judgment, all named at the top of the module: near distance 20 m; kind weights 1.0 / 0.6 / 0.2; active-now bonus 0.25
site-years; overlap discount 0.6 (street work also reaches today's level through 311 complaints); day cap 9 dB;
share cap 0.8 (a permit is permission, not use); reason weights (city or emergency 1.0, hardship or public safety 0.8,
minimal noise 0.3); enclosed work x 0.5; weeknights x 5/7; text ranges over 14 hours ignored; block span 700 m.

## Limits, worst first

1. Permits are permission, not measurement. Nothing here is a sound reading, and no study ties these counts to
   loudness; the lift and the shares are indexes, not decibels a renter should see.
2. A snapshot. Work that starts after 2026-10-28 is invisible until a rebuild. Active-now flags lapse at each permit's
   end date and are dropped after 90 days. Rebuild monthly.
3. Night work is found only where it is written down: a variance, or hours in DOT permit text (2,573 permits).
   A permit with no stated hours counts as day work, so night street work is undercounted.
4. Street work next to a building project is partly the same job as a DOB permit; the overlap discount is a guess.
5. Placement is by block, not address, for the 77% of permits with no house number; the exact spot on a long block
   is unknown.
6. Hours are read from free text with a pattern; unusual wording is missed, and "weeknights" is a flat 5/7.
7. Manhattan only (Governors Island included). No floor or facade effect here; the engine adds it afterwards.
8. Contract notes: `save()` writes only to `DATA`, so `build(out_dir)` writes its own file; `upgrade()` has no date,
   so it reads the system date for the active-now flags.

## Evaluation (the 298 distinct baseline buildings, three slots averaged)

Street work within 100 m: 284 (95%); a variance site: 74 (25%). Rank correlation of today's level with the combined
level: 0.987 (0.979 with sleep weights); night 0.952, day 0.982. Spread: 155 distinct values become 274.
