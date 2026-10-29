# Engine v2

Hackathon work, Oct 28. Code: `noise_score/v2.py`, numbers in `noise_score/config_v2.py`, tests in
`tests/test_v2.py`, endpoint `/v2/score`. It reads the frozen ingredients (M1 to M13 in `DECISIONS.md`) and the
frozen Manhattan sample, and changes neither. v1 stays live at `/v1/score`.

## Why a second engine

1. **Sources are compared with themselves, never added.** v1 adds the five sources in decibels. That assumes a
   neighbors "66" means the same as a street "66". For the street it roughly does, since it comes from road
   physics; for neighbors, sirens and construction the numbers are complaint and permit counts converted by our
   own rules, and no study ties those sources to loudness. v2 uses decibel-shaped estimates only inside each
   source (road size against distance, an indoor bar against an outdoor one) and turns each into a rank.
2. **Floor and side must move the verdict the right way.** v1 ranks a unit against every sample building moved
   to the same floor and side. At a high floor at the rear, outdoor noise drops for everyone and neighbor noise
   dominates, so a quieter unit can rank worse. v2 ranks against a fixed Manhattan.

## The rules

- **V1 Sources.** The five ingredients per time slot (street, nightlife, building, sirens, construction), the
  frozen model's math with the research numbers (V10), after floor and side.
- **V2 Hours.** An hour the renter is asleep weighs 3, an awake hour 1, or 0.5 if daytime noise does not bother
  them. A slot's weight is the sum of its hours. Asleep 11 pm to 7 am gives night 48%, early 18%, day 35%.
  Each source's slot levels are averaged with these weights.
- **V3 Weights.** Street 32, sirens 20, neighbors 20, nightlife 15, construction 13, from New York City health
  department noise surveys ([Epi Data Brief 45](https://www.nyc.gov/assets/doh/downloads/pdf/epi/databrief45.pdf),
  [Epi Data Brief 105](https://www.nyc.gov/assets/doh/downloads/pdf/epi/databrief105.pdf)), the mean of three
  readings, rounded. 311 complaint shares are not used: Brief 105 shows they over-count neighbors and
  under-count traffic. A source the renter ticks counts three times; weights are then rescaled.
- **V4 Ranks.** Each source is ranked against the Manhattan sample (300 buildings drawn by residential units,
  M12), every sample building at a typical apartment: the middle residential floor, side unknown. The rank is
  "quieter than X% of Manhattan apartments".
- **V5 Verdict.** The weighted average of the five ranks, re-ranked against the same average for every sample
  building, in fifths: Very loud, Loud, Typical, Quiet, Very quiet.
- **V6 Caps.** Any source in Manhattan's loudest 5% caps the verdict at Loud. A ticked source in the loudest 10%
  caps it at Typical. Each cap is returned with the source that set it.
- **V7 A silent listing.** No floor: the middle residential floor (floor 2 up when the ground floor is
  commercial). No side: unknown. Either missing adds a range: the lowest residential floor on the street side and
  the top floor at the rear. Floor and side follow the research rules (V10, `v2.position_db`).
- **V8 No decibels leave the engine.** Every number in the response is a rank, a weight, a floor or a count.
- **V9 Source upgrades.** Each source keeps today's estimate and adds what actually passes, and when
  (`noise_score/upgrades/`, one module per source, each documented in `upgrades/<source>.md`). Today and the
  upgrade are two estimates of the same sound, so a module combines them as a correction or an average inside
  its own source, never as a sum that counts the same noise twice. The Manhattan sample is upgraded the same way
  (`python -m noise_score.upgrades.apply`); the engine uses upgraded levels only when that sample was built with
  the modules on disk, so a renter and the sample are always scored alike. `v2.explain()` returns every input
  and rule as steps for the math board.
- **V10 Research recalibration.** The numbers that move a rank, from the noise research of 2026-10-29: traffic,
  elevated rail and sirens lose nothing through 12 m above the floor-1 window and then 0.1 a metre (at most 6);
  bars and building sites keep 1 a floor (at most 8); the rear is 10 quieter for traffic, 8 for the rest; trucks
  and buses count as 15 cars on city streets; the street 311 add stops at 3 (nightlife's stays at 12, decision U6);
  restaurants 47 and other venues 59 at 10 m, with outdoor tables as their own sound source; sirens fade 5 a doubling;
  construction complaints add 2 a doubling. `noise_score/recal.py` recomputes each source on the same pulls, and
  the Manhattan sample from the pulls it was built from. Every change, its source and its check:
  `upgrades/RECALIBRATION.md`.
- **V11 Block bars.** Each ingredient also carries `block_quieter_than`, display only: the same source ranked
  against the same Manhattan sample at the building's typical apartment (middle residential floor, side unknown,
  as V4 ranks the sample) with all 24 hours weighted equally. It is the same for every renter and every apartment
  in the building, so a per-source bar shows the block, while `quieter_than` beside it is the source at this
  apartment's floor and side over the renter's hours. The score, verdict, caps and the weighted average never read
  it. (Rafa, 2026-10-29: "the bars by definition are not impacted by an apartment's floor".)

The `nightlife` source reads "Local businesses" wherever a renter sees it (restaurants, theatres and busy spots,
not only bars); the API key stays `nightlife`.
