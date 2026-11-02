# Research recalibration (engine v2, rule V10)

Applied 2026-10-29 (HIQ-71) from the noise research of the same day, report "Noise levels and sound transmission"
(kept privately with the hackathon notes; IDs below are its recalibration table). Only numbers that differ between
buildings move a rank, so only those changed. Offsets applied alike to every building (slot offsets, absolute siren
levels, the WHO window losses) cannot move a rank and wait for an absolute flag. `config.py` and `model.py` stay
frozen; every new number is in `config_v2.py` under [V10].

## How it runs

- `noise_score/recal.py` repeats model.py's math at the facade-neutral unit on the same pulls, with the new numbers.
  With config.py's numbers it reproduces model.py exactly (tests) and the frozen sample to 0.0005 (sample build).
- `recal_sample.json` is the 298 sample buildings recomputed from the pulls the baseline was built from.
  Upgrades (V9) then start from these levels for the renter and the sample alike.
- `v2.position_db` replaces v1's floor and side rule for both.

## What changed

| ID | Number | Was | Now | Where |
|---|---|---|---|---|
| P1, P2 | Floor, traffic, elevated rail, sirens | -1 a floor, at most -8 | 0 through 12 m up, then -0.1 a metre, at most -6 | `v2.position_db` |
| P1, P2 | Floor, nightlife, construction | -1 a floor, at most -8 | same | `v2.position_db` |
| NEW-P-a | Metres per floor | none | 3.64 / 3.44 / 3.16 for 2-6 / 7-20 / 21+ floors, 3.4 unknown | `v2.story_height` |
| P3 | Rear | -8 | -10 traffic, -8 the rest | `v2.position_db` |
| P4 | Side unknown | -2 | -2.5 | `v2.position_db` |
| B16, B17, B18 | Neighbors: top floor, first floor, floor 2 over a shop | -3, +2, +2 | -4, 0, 0 | `v2.position_db` |
| k | Cars one truck or bus equals | 8 | 15 on city streets, 8 on highways | `upgrades/street.py` |
| ST8 | Speed over 25 mph | +1 per 5 mph, every road | +2 per 5 mph, highways and ramps only | `recal.street` |
| ST9 | Two-way street | +1 | 0 | `recal.street` |
| ST17 | Street 311 add, ceiling | 10 | 3 | `recal.street` |
| ST20 | No road within 60 m | 45 | 50 | `recal.street` |
| N2, N3 | Other venues, restaurants at 10 m | 62, 58 | 59, 47 (class-code grades keep their steps) | `recal.nightlife`, `nightlife.py` |
| N8 | Nightlife 311 add | ceiling 12, every slot | not taken: kept at 12, every slot (decision U6) | `config_v2.py` |
| Dining | Outdoor dining | +5 times a share, judgment | each cafe a terrace, 56.8 at 10 m (24 seats), 7 pm to 11 pm | `nightlife.py` |
| B14 | Built 1940 to 1999 | +1 | 1940-67 +2, 1968-76 +1, 1977-99 0 | `recal.building` |
| SI4 | Siren distance slope | 4 a doubling | 5 | `recal.sirens`; route calibration refit |
| C4 | Construction complaints | +4 a doubling | +2 | `recal.construction` |

## Not done yet (rank-moving, need data or geometry)

Street work cap by floor (15 on floors 1 to 3), street work at night (0.1 of day), after-hours variance ceiling -10,
siren routes on streets the window does not face (-8), trains per hour on elevated lines, distance to the elevated
structure, distinct 311 callers. Rank-neutral items (slot offsets, window losses, the WHO health tier) wait for the
absolute flag, which changes the /v2/score shape.

## Checks

- SONYC sensors, cells whose 90% interval clears zero, of 12: 6 now, 7 before this change, 3 for the frozen model.
  Street improves in every slot (night +0.29 to +0.34, early +0.42 to +0.46, day +0.31 to +0.40), construction
  early turns positive, sirens hold. Nightlife night +0.38 to +0.35, day +0.37 to +0.29.
- With the research's nightlife cap (6, night only) the count was 5: nightlife fell to +0.28 at night and +0.01 by
  day, because complaints carry most of what the sensors' music and voice tags agree with. Decision U6 kept the
  old cap.
- The sample at its typical apartment: 98 of 298 buildings change verdict. Buildings of 1 to 6 floors move up
  6.3 points on average (quieter), 7 to 20 floors move down 6.4 (they lose height credit traffic does not give),
  21+ floors barely move. Inwood and Hell's Kitchen blocks with heavy vehicle-complaint counts move most.

## Rebuild, in order

```
cd packages/model
NOISE_SCORE_CACHE=<cache> python -m noise_score.recal                     # recal_sample.json (PLUTO pull once)
python -c "from noise_score.upgrades import sirens; sirens.recalibrate()"  # routes on the new scale
python -m noise_score.upgrades.apply                                       # manhattan_upgraded.json
```
