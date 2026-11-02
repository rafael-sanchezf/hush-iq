# Source upgrade decisions

The judgment calls inside the five source upgrades, decided 2026-10-29. Each entry says what was chosen, the
evidence at the time, where the number lives, and what would make us revisit it. The engine rules themselves are
in `../ENGINE_V2.md`; each source's full method is in `<source>.md` beside this file.

| Id | Call | Chosen | Number and file |
|---|---|---|---|
| U1 | Apartments per floor raise neighbor noise | Off | `HALLWAY_PER_DOUBLING = 0.0` in `noise_score/upgrades/building.py` |
| U2 | Street counts reach the streets nobody counted | As built; k now sourced | `BORROW_MAX_M = 1000`, `CORRECTION_CAP = 6` in `street.py`; k 15 and 8 in `config_v2.py` |
| U3 | Outdoor dining raises nightlife | Replaced by a sourced terrace source | `TERRACE_*` in `config_v2.py`, used in `nightlife.py` |
| U4 | Sirens: station distance against routed trips | Half each | `MIX = 0.5` in `sirens.py` |
| U5 | Building type corrects neighbor noise | Half strength, capped | `CLASS_SHARE = 0.5`, `CLASS_CAP = 6.0` in `building.py` |
| U6 | Nightlife research numbers lower the sensor match | Old 311 add kept; new grades and terraces kept | `NIGHTLIFE_311_*` in `config_v2.py` |

## U1 Apartments per floor

- **The idea:** more doors on a hallway means more chatter and more neighbors through the walls.
- **The evidence:** on 32,390 Manhattan lots, later 311 neighbor complaints fell as apartments per floor rose,
  once today's level and building type were known (-0.17 per doubling, t -3.6). Elevator buildings with 14 to 20
  apartments a floor drew 0.045 complaints per apartment a year; 6 to 8 a floor drew 0.095. Adding the rule made
  the held-out fit slightly worse.
- **Why off:** the one dataset we have says the opposite, and we could not separate "quieter" from "complains
  less" (big buildings often have staff to call instead of 311).
- **Revisit when:** a measured source exists, such as indoor sound recordings by building, or listing photos show
  the hallway layout. Switching it back on is one number; a test keeps the rule working.

## U2 Street volume beyond the counted streets

- **The facts:** the city publishes traffic counts for 86 of Manhattan's 11,797 street segments. Uncounted
  streets borrow the nearest count on the same street within 1 km, else take the typical volume for their road
  type. Buses come from MTA timetables on 5,052 segments; trucks from the truck-route map.
- **The effect:** modest. 20 of 298 sample buildings move by a point or more; the ranking barely changes.
- **Why as built:** a wider borrow or a bigger correction would spread guesses, not measurements.
- **Revisit when:** more counts arrive (DOT adds locations yearly).
- **2026-10-29:** the noise research sourced the heavy-vehicle factor: 15 cars per truck or bus on city streets
  (NYC CEQR 13 for a medium truck, 18 for a bus at 25 mph), 8 on highways (a bus is 6.3 cars at 50 mph).

## U3 Outdoor dining

- **The facts:** 1,613 Manhattan sidewalk and roadway cafe licences (Dining Out NYC, fpeh-f7ci). Tables close at
  11 pm under the 2026 rules.
- **The evidence against:** on held-out 311, adding the outdoor rule lowered the match slightly; a district-level fit
  gives licensed cafes about zero effect on evening complaints.
- **Why kept:** people talking outdoors is louder at the window than the same people behind a closed front, and 311
  may undercount it because diners leave by 11. It is labelled judgment on the board.
- **Revisit when:** sound measurements near cafes exist.
- **2026-10-29:** replaced. The research gives a seated terrace at raised voices as 46 + 10 log10(seats / 2) at 10 m
  (56.8 for 24 seats, the default since licences do not give seats), busy 7 pm to 11 pm. Each cafe is now its own
  point source, added as energy for those hours, so restaurants with tables land near their old level while
  restaurants without fall to 47.

## U4 Sirens mix

- **The facts:** two estimates of the same sirens. Today's counts hospitals, firehouses and police stations within
  600 m. The routes count 708,000 routed fire and ambulance trips from the last year on each street.
- **Why half each:** nothing measures sirens at the address, so neither estimate has earned more weight. Against
  SONYC sensor recordings, the mix scores better than today by day and early morning, and worse at night.
- **Revisit when:** the FDNY records request comes back with real routes, or more sensor data exists.

## U5 Building type

- **The facts:** comparing each building class's complaints with what today's formula expected, elevator rentals
  run about twice the expected rate, co-ops about a quarter, condos about half.
- **Why half strength and a cap of 6:** part of the gap is likely who calls 311 (owners may complain to the board
  instead), not how loud the building is.
- **Revisit when:** a measured source separates loudness from reporting.

## U6 Nightlife research numbers against the sensors

- **The facts:** the research lowers restaurants to 47 and other venues to 59 at 10 m, and caps the 311 add at 6,
  at night only, because complaints count callers, not loudness.
- **The evidence against:** on the SONYC sensor blocks, nightlife's match to music and voice tags falls from +0.38 to
  +0.28 at night and from +0.37 to +0.01 by day. Taken one at a time, the 311 ceiling and the day bump going away
  cost the most, the restaurant grade some (`RECALIBRATION.md`, Checks). 33 blocks, mostly Greenwich Village;
  tags are presence, not loudness.
- **Options:** keep the research numbers; or keep the grades and terraces and restore the old 311 add (ceiling 12,
  every slot); or restore all of nightlife's old numbers. Each is a change to `config_v2.py` and a sample rebuild.
- **Decided:** 2026-10-29 (HIQ-72): restore the old 311 add (ceiling 12, every slot), keep the new grades
  and terraces. Sensor match after: +0.35 at night, +0.29 by day. The research's case (complaints count callers)
  is argued from theory at low confidence; the sensors are the only Manhattan measurement we have.
- **Revisit when:** sound levels, not tag presence, exist for nightlife blocks, or 311 callers can be de-duplicated.
