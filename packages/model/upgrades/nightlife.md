# Nightlife upgrade (Oct 28)

Code `noise_score/upgrades/nightlife.py`, artifact `noise_score/data/upgrades/nightlife.json.gz` (0.30 MB, Manhattan),
tests `tests/test_upgrade_nightlife.py`. Rebuild with `python -m noise_score.upgrades.nightlife` (network, stdlib only).

## What it adds

Today knows that a licence exists within 150 m and how many complaints were filed. It does not know whether tables
are outdoors, on how many different nights people complained, or which licences are bars. Three corrections, each a
share of the gap between two estimates of the same sound, so nothing is counted twice.

## Inputs

- Today, live: licensed venues within 150 m; party, music and loud-talking complaints within 150 m, per slot, 24 months.
- New: the class code of each venue; distinct nights with a complaint, per slot; licensed outdoor cafes within 150 m.

## Datasets (pulled 2026-10-28)

| Dataset | ID | Rows | Window |
|---|---|---|---|
| NYS Liquor Authority, Current Active Licenses, [link](https://data.ny.gov/resource/9s3h-dpkz) | 9s3h-dpkz | 9,939 in New York County, 7,649 venue licences kept | active on 2026-10-28 |
| NYC DOT, Dining Out NYC Locations, [link](https://data.cityofnewyork.us/resource/fpeh-f7ci) | fpeh-f7ci | 1,613 Manhattan (1,040 sidewalk, 573 roadway) | issued 2024-10-24 to 2026-10-23 |
| 311 Service Requests, [link](https://data.cityofnewyork.us/resource/erm2-nwe9) | erm2-nwe9 | 145,412 complaints, 107,696 cell-nights, grouped on the server | 2024-10-01 to 2026-09-30 |

311 filter: Manhattan, Noise - Commercial, Street/Sidewalk and Park, descriptor Loud Music/Party or Loud Talking (as today).

## Formula in plain words

1. Class: grade each venue by its class code, sum with today's distance law (10 m reference, 6 dB per doubling, cap 75).
   Correction = half of (sum by class code minus sum by licence description).
2. Nights: count nights with at least one complaint within 150 m, per slot (10 pm to 5 am is one night; a 1 am call
   belongs to the evening before). Bump = 3 x log2(1 + nights per year / 3), no 12 dB ceiling; it tops out at 20.9
   (a complaint every night). Correction = half of (this bump minus today's bump counted in complaints, 12 at most).
   The research proposed 6, night only; decision U6 kept 12 in every slot.
3. Terraces (V10, replaced the outdoor share rule): each licensed cafe within 150 m is a point source of 24 seats,
   46 + 10 log10(24 / 2) = 56.8 at 10 m, 6 per doubling of distance, summed as energy. Busy 7 pm to 11 pm: night 1
   hour of 7, early none, day 3 of 14. Added as energy for that share of each slot.
4. Level per slot = today + class + nights (held to 6 either way), then terraces. Levels are internal ("index").

## Constants

- Sourced from today's model (config.py, read not copied): 150 m radius, 24 months, 10 m reference, 6 dB per doubling,
  cap 75, 40 with no venue, bump 3 dB per doubling from 3 a year, ceiling 12 (kept by decision U6).
- Sourced, noise research of 2026-10-29 (config_v2.py, V10): description grades bar 66, other venues 59, restaurant 47;
  terrace 56.8 at 10 m, busy 7 pm to 11 pm (tables close at 11, Dining Out NYC). The nights bump ceiling 20.9 is
  arithmetic (365 nights).
- Judgment: class grades as steps from their description's grade (liquor Food & Beverage at bar grade, other Food &
  Beverage venue -4, restaurant with liquor +2, restaurant beer and wine -2, hotel and catering venue -6, additional
  bar bar -4), ordered by the fit below; both mixes 0.5; correction cap 6 (a sixth of the 40 to 80 range).

## What was tested

- Held out: features from Oct 2024 to Sep 2025, target distinct complaint nights Oct 2025 to Sep 2026, 32,390 residential
  Manhattan lots. Spearman, today to combined: night 0.42 to 0.48, early 0.19 to 0.20, day 0.33 to 0.37. Nights alone
  0.48, 0.19, 0.39; class alone 0.43, 0.20, 0.33; outdoor alone 0.415, 0.194, 0.31 (it lowers the match). This shows the
  counts are stable, not that they measure loudness.
- Fit by community district, complaint nights on licence counts within 100 m (night coefficients): liquor Food & Beverage
  0.28, restaurant with liquor 0.21, club 0.15, restaurant beer and wine 0.15, additional bar 0.10, other Food & Beverage
  0.08, hotel -0.14, catering -0.15. Licensed cafes, same fit on complaint counts: 0.03 evening, -0.03 10 pm to midnight, -0.13 after.
- Today's 311 bump sits at its 12 dB ceiling for about 45% of Manhattan lots at night and 41% by day; counted in nights, 34% and 29%.
  30.6% of these complaints come from 1% of locations; 1.42 complaints per cell-night.

## Rejected

- Open Restaurant Applications (pitm-atqc): 14,428 rows of the temporary 2020 to 2023 program, many sheds gone.
- Sidewalk Cafe Licenses (qcdj-rwhu): 324 rows, inactive, ended 2023. DCWP Issued Licenses (w7w3-xahh): no cabaret category.
- Liquor hours, live music, dancing, method of operation: the NYS file has none of them, only the class code.
- OpenStreetMap opening hours: Overpass was at capacity on two tries; volunteer tags, patchy.
- 311 hour profile as new slot offsets: day is 3 to 5 dB under night (7 for bar-located calls), early 9 to 14, against
  today's flat 8. A uniform shift that moves no rank, so left alone.

## Limits, worst first

1. Terraces assume 24 seats and evening use; 311 did not back the old outdoor rule (above). The new grades lower the
   SONYC match a little (night +0.38 to +0.35, day +0.37 to +0.29; DECISIONS.md U6).
2. Class grades rest on a complaint fit, a proxy for complaints, not loudness; a hotel with a rooftop bar grades as quiet.
   Class meanings are read off licensee names, the dataset has no legend.
3. 311 follows who calls as well as what is loud. Counting nights removes repeat callers on one night, not areas that call more.
4. Dining Out lists licences issued since Oct 2024; older sidewalk cafes may be missing, so outdoor dining is undercounted.
   Roadway cafes were seasonal (April to November) until the 2026 change and count as year-round here.
5. A snapshot (licences 2026-10-28, 311 to 2026-09-30), Manhattan only: a shore point sees no Brooklyn, Queens or New Jersey venues.
6. Licences at one address still count separately, as today (47% share a coordinate; up to 10 dB at large hotels).
   Not changed here, because it alters the frozen venue sum.
