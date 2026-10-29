# SONYC validation

Does Hush IQ rank real Manhattan sensor blocks the way volunteers' sound tags do? Run 2026-10-29, city data as of 2026-10-29. Harness: `validation/sonyc.py`. Numbers: `sonyc_results.json`.

## Data
- SONYC-UST-V2 (version 2.3, Zenodo 3966543, CC BY 4.0, arXiv 2009.05188): 10-second street-level clips, tagged by three volunteers each, 1,380 verified by the SONYC team. Only `annotations.csv`, the taxonomy YAML and the README were downloaded (md5-checked); no audio.
- Manhattan (borough code 1): 17,662 clips, 58,527 annotation rows, 43 sensors on 28 tax blocks, 38 distinct block-level locations, recorded 2016 to 2019. 1,177 clips carry a verified label.
- Cluster, by distance from Washington Square Park: 19 locations (11,192 clips) under 0.5 km; 9 locations (4,891 clips) 0.5 to 1 km; 2 locations (390 clips) 1 to 2 km; 8 locations (1,189 clips) beyond 2 km. 91% of clips sit within 1 km, the Greenwich Village cluster the paper describes; the rest is 8 locations: Lower Manhattan 1, Midtown 5, the Upper East Side 2.
- 35 of 38 locations have 20 or more clips in some slot; the floor is applied per slot, so n is 26 to 34 locations per cell (night 33, early 26, day 34).

## Mapping
| Hush IQ source | SONYC tag | Note |
|---|---|---|
| street | engine (coarse class 1) | all engine sizes |
| construction | machinery-impact (2) or powered-saw (4) | non-machinery-impact left out |
| nightlife | music (6) or human-voice (7) | talking and crowds count, so it is also street life |
| sirens | siren (fine tag 5-3 under alert-signal) | horns, alarms and beepers excluded |
| building | none | neighbors have no outdoor sound tag, so there is no proxy to test against; skipped |

## Method
- Label: the verified label when the clip has one, else the volunteers' majority (2 of 3; every Manhattan clip has exactly 3). Sensitivity with 'any volunteer' is in the JSON (`rho_any_volunteer`).
- Tag share: tagged clips over all clips at a location, per slot (night 22 to 5, early 5 to 8, day 8 to 22, by the clip's hour). Locations with fewer than the floor in a slot drop out of that slot.
- Hush IQ level: `sources.pull_at` at the sensor coordinate, with the PLUTO lot on the sensor's own tax block nearest to it (median gap 0.5 m), scored by the frozen model at a facade-neutral unit (`baseline.neutral_levels`).
- Research numbers: the same pulls scored with the recalibrated constants of 2026-10-29 (`noise_score.recal`, engine v2 rule V10). Upgraded: `noise_score.upgrades.<source>.upgrade(lat, lng, level, facts)` on top of the research numbers, for each source that has a module and a built artifact. Used now: street, construction, nightlife, sirens.
- Statistic: Spearman rank correlation across locations, 90% percentile interval from 2000 resamples of locations (resampling whole tax blocks is in the JSON as `ci90_block`).

## Results (Spearman rho across sensor locations, positive means Hush IQ's louder blocks have more of the sound)
| Source | Slot | n | Mean share | Today rho [90% CI] | Research numbers rho | Upgraded rho [90% CI] |
|---|---|---|---|---|---|---|
| street | night | 33 | 33% | +0.20 [-0.06, +0.43] | +0.23 | +0.34 [+0.09, +0.56], change +0.14 |
| street | early | 26 | 33% | +0.26 [-0.05, +0.54] | +0.24 | +0.46 [+0.18, +0.65], change +0.20 |
| street | day | 34 | 30% | +0.26 [-0.02, +0.47] | +0.32 | +0.40 [+0.11, +0.60], change +0.14 |
| construction | night | 33 | 2% | +0.04 [-0.28, +0.35] | +0.14 | +0.16 [-0.16, +0.44], change +0.12 |
| construction | early | 26 | 13% | -0.13 [-0.47, +0.24] | +0.12 | +0.16 [-0.21, +0.50], change +0.29 |
| construction | day | 34 | 10% | -0.22 [-0.53, +0.12] | -0.21 | -0.26 [-0.54, +0.04], change -0.05 |
| nightlife | night | 33 | 26% | +0.38 [+0.07, +0.62] | +0.32 | +0.35 [+0.03, +0.60], change -0.03 |
| nightlife | early | 26 | 5% | -0.11 [-0.46, +0.27] | -0.02 | +0.01 [-0.38, +0.39], change +0.12 |
| nightlife | day | 34 | 31% | +0.20 [-0.10, +0.48] | +0.11 | +0.29 [-0.02, +0.55], change +0.09 |
| sirens | night | 33 | 4% | +0.16 [-0.17, +0.44] | +0.16 | -0.02 [-0.33, +0.30], change -0.17 |
| sirens | early | 26 | 2% | +0.43 [+0.07, +0.72] | +0.40 | +0.48 [+0.18, +0.71], change +0.05 |
| sirens | day | 34 | 4% | +0.49 [+0.20, +0.73] | +0.50 | +0.55 [+0.28, +0.77], change +0.06 |

Read: of 12 cells, 3 have an interval entirely above zero, 0 entirely below, 9 straddle zero. Strongest sirens day (+0.49 [+0.20, +0.73]), weakest construction day (-0.22 [-0.53, +0.12]).
With 12 cells and 90% intervals, chance alone puts about 0.6 above zero. The cells are not independent: they reuse the same locations, and the frozen sirens ranking is the same in every slot.

## Limits, worst first
1. Tiny, clustered sample: 38 locations, 28 blocks, mostly one neighborhood. No Harlem, Upper West Side, Chelsea or Hudson-side blocks. Intervals are wide; neighbors share streets, and resampling whole tax blocks (`ci90_block`) gives about the same width.
2. Clips were not drawn at random: SONYC picked audio near known examples of the target classes, and capped human voice at one clip per hour per sensor. A share measures how much of the picked audio has the tag, not how often the sound happens on that block.
3. Tag presence is not loudness. One horn and one jackhammer count once each; near and far count the same.
4. Years do not match: audio is 2016 to 2019, Hush IQ's 311, permit and license pulls cover the last 24 months. Roads and facilities barely change; bars, permits and complaints do.
5. Position: SONYC calls its coordinates block-level, but they land on a tax lot centroid (median 0.5 m); the facade, height and street a sensor faces are unknown. Hush IQ is scored at a facade-neutral unit with 60 to 150 m radii, so a sensor around the corner can see a different street.
6. Mapping is coarse: engine includes buses and idling, music and voice include daytime street life, a siren tag is any emergency vehicle passing, not only those from nearby facilities.
7. Label noise: majority of three volunteers, verified for only 1,177 of 17,662 clips, so the two rules mix. Switching to 'any volunteer' moves rho by up to 0.32 (construction night: +0.04 to +0.36).
8. Neighbors (building) cannot be tested at all with outdoor audio.
9. Upgrades: tested for street, construction, nightlife, sirens; not yet for none.

## Re-run
`cd packages/model && NOISE_SCORE_CACHE=<cache dir> python -m validation.sonyc` (add `--reuse-today` to skip the city-data pulls and only re-apply upgrades).
