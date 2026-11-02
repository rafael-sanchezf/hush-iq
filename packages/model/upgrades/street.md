# Street upgrade

Module `noise_score/upgrades/street.py`, artifact `noise_score/data/upgrades/street.json.gz` (0.24 MB, Manhattan).
Today's street estimate (road class, lanes, speed, distance, 311 vehicle complaints) stays. This upgrade corrects it
for what actually passes: vehicles per hour, trucks, and scheduled buses, by time slot. Levels are internal
("index"); renters see counts only.

## Inputs
- `lat`, `lng`, and `today`: the frozen model's street level per slot (night 22-5, early 5-8, day 8-22).
- Built artifact: 11,797 Manhattan centerline segments, each with vehicles per hour, buses per hour, truck route.

## Datasets
| Dataset | Id | Window | Use |
|---|---|---|---|
| [Automated Traffic Volume Counts](https://data.cityofnewyork.us/d/7ym2-wayt) | 7ym2-wayt | 2019, 2022 to 2026 (106,731 Manhattan rows) | weekday vehicles per hour per slot |
| [Vehicle Classification Counts](https://data.cityofnewyork.us/d/96ay-ea4r) | 96ay-ea4r | 2019, 2022 to 2025 (15,036 rows citywide, 73 Manhattan segments used) | truck share of non-bus vehicles |
| [NYC Truck Routes](https://data.cityofnewyork.us/d/jjja-shxy) | jjja-shxy | current (4,621 Manhattan rows) | local or through designation |
| [Street Centerline](https://data.cityofnewyork.us/d/inkn-q76z) | inkn-q76z | current | the segments, class as today's model reads it |
| [MTA bus timetables](https://new.mta.info/developers) (GTFS static, 6 feeds: m, bx, b, q, si, busco) | rrgtfsfeeds.s3.amazonaws.com | Tue 2026-11-10 school-day service (55,159 trips, 1,427 shapes) | weekday buses per hour |

## Formula in plain words
1. Every centerline segment gets vehicles per hour per slot. Counted (86 segments): the weekday median hour, latest
   usable year, both directions added. Not counted: the nearest count on the same street and traffic direction
   within 1 km, fading linearly to nothing at 1 km, blended with the median of counted segments of the same road class.
   No count nearby: that class median alone. Of the 298 sample buildings' main streets, 3 are counted, 39 borrow, 237 use the class.
2. Buses per hour: weekday trips by the hour their first stop departs, divided by the slot's hours, added up over every
   route shape that runs along at least half the segment, within 15 m and 30 degrees.
3. Truck share: the street's own classification count where it has one, else the pooled share of Manhattan streets with
   its truck route designation (none, local, through).
4. Effective vehicles = cars + k x (trucks + buses). k = 15 on city streets, 8 on highways (V10).
5. Implied volume = median effective vehicles of the counted segments in the same road class and slot (what today's class assumes).
6. Correction per street = 10 x log10(effective / implied), capped at plus or minus 6.
7. For streets within 60 m (today's radius), keep one segment per street name as today does, add the corrections in energy
   terms weighted by each street's level today, so the loudest street dominates. New level = today + that correction.
8. No street within 60 m: today's level unchanged. Elevated rail and the 311 bump stay as today computes them.

## Constants
| Name | Value | Source |
|---|---|---|
| SLOT_HOURS | 22-5, 5-8, 8-22 | sourced: today's model (config.WINDOWS) |
| K_HEAVY, K_HEAVY_HIGHWAY | 15, 8 | sourced, noise research of 2026-10-29: NYC CEQR 13 for a medium truck and 18 for a bus at 25 mph; FTA a bus is 17.8 cars at 25 mph, 6.3 at 50 (was 8, judgment) |
| CORRECTION_CAP | 6 | judgment |
| COUNT_YEARS, WEEKDAYS | skip 2020 and 2021; Mon to Fri | judgment |
| COUNT_MIN_DAY_VPH, COUNT_MIN_SLOT_RATIO, COUNT_MAX_EARLY_RATIO | 25, 0.05, 3 | judgment: drops counter faults and closures (8 direction-years) |
| COUNT_MATCH_NAMED_M, COUNT_MATCH_ANY_M | 40 m, 12 m | judgment |
| DOUBLE_ONE_DIRECTION | on | judgment: a two-way street counted one way carries the same the other way |
| BORROW_MAX_M | 1000 m | judgment |
| MIN_COUNTED_IN_CLASS, CLASS_PARENT | 3; ramp to bridge, bridge to arterial, one lane to two lane to arterial | judgment |
| BUS_MAX_SHARE | 0.5 | judgment |
| ROUTE_MATCH_M, ROUTE_MATCH_ANGLE_DEG, ROUTE_COVER_FRACTION | 15 m, 30 degrees, 0.5 | judgment |
| GTFS_REFERENCE_DATE | 2026-11-10 | judgment |
| Class medians, truck shares, bus rates | in the artifact | sourced: the datasets above |

## Limits, worst first
1. Few counts. 86 of 11,797 segments are counted (0.7%); side streets have 26 counts between them. Most
   streets rest on the class median, so the upgrade mostly moves streets with many buses, a truck route, or a count nearby.
2. Today's 60 m cliff is kept. 19 of 298 sample buildings sit more than 60 m from any street; they get today's 40 to 45
   and no correction, which ranks them quietest on street noise whatever runs 70 m away.
3. Counts are a few days at one time of year, 2019 for 21 of them (before congestion pricing and the 14th Street busway), so a street can be off by a factor of two.
4. Buses are timetable trips by first-stop hour, not observed passes; deadheads and delays are absent, express buses
   are included.
5. Elevated rail and the 311 bump are in today's level and are not corrected; near a viaduct the road correction overstates.
6. The class reference is the median of counted segments, and counters sit on avenues; counted side streets are few (7 one-lane).
7. 613 footpath and bike path segments (mostly bridge class) count as roads in today's model; they get zero vehicles, so the cap lowers them.
8. k is one number for trucks and buses; a heavy truck is closer to 47 cars at 25 mph, a medium truck to 13.
9. Truck share for unclassified streets is pooled by route designation from 73 streets, 24 of them non-route.
10. Segment matching of count points and bus shapes uses distance and bearing; a divided avenue's two carriageways are 20 m apart.
