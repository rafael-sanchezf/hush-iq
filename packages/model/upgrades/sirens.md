# Sirens upgrade

Code `noise_score/upgrades/sirens.py`, artifact `noise_score/data/upgrades/sirens.json.gz` (113 KB), tests
`tests/test_upgrade_sirens.py`, rebuild `sirens.build(DATA)` (about 15 seconds with the pulls cached).
Today's level comes from the distance to hospitals, firehouses and police stations. This upgrade adds where fire
engines and ambulances drive and averages the two, never adding them as energy: both estimate the same sound.

## Inputs

- `lat`, `lng`; `today`, the frozen model's sirens level per slot at a facade-neutral unit; `facts` is not used.
- The artifact: 5,117 street segments with trips per slot in three kinds (fire responses, ambulance responses,
  hospital transports), both directions summed, plus the facility list and the calibration.

## Datasets (window 2025-10-01 to 2026-09-30, Manhattan; no key)

Each at `https://data.cityofnewyork.us/resource/<id>`; streets from OpenStreetMap (osmnx drive network).
- Fire Incident Dispatch Data, `8m42-w767`: 172,434 incidents by alarm box and hour.
- EMS Incident Dispatch Data, `76xm-jjuj`: 384,275 incidents, 205,731 transports, by zip and hour.
- FDNY alarm box locations `v57i-gtxb`; Fire Companies `bst7-5464` (districts); FDNY Firehouse Listing `hc8x-tcnd`;
  NYC Facilities Database `67g2-p84d` (hospitals, ambulance stations, police stations).

## How routes are built

1. A fire incident sits at its alarm box. The first-due firehouse is the engine company whose district holds the
   box. 120,688 fire trips routed.
2. EMS has only a zip, so its calls are spread over where fire units' medical calls happen in that zip. Each gets an
   ambulance from the nearest hospital or ambulance station (382,519 trips) and, if the patient was taken, a
   transport from the call to the nearest hospital (204,893 trips).
3. Every trip takes the quickest path. Speeds (mph): motorway 45, trunk 35, primary 30, secondary 26, tertiary 22,
   other 16. One-ways are respected. Trips are counted per segment and slot (night 22 to 5, early 5 to 8, day 8 to 22).
4. The leg from a station's door to its nearest intersection (median 64 m for a firehouse) is a segment of its own,
   or the block in front of a station would carry no trips.

## The formula in plain words

1. Cut every segment into 25 m pieces; a piece carries its segment's trips.
2. A piece at distance d from the address counts `1 / (1 + (max(d, 10) / 30) ^ 1.33)`. Pieces within 300 m count.
3. Exposure per slot = weighted trips over fire, ambulance and transport, divided by the slot's hours in the year.
4. Route level = `51.145 + 10.37 x log10(exposure + 0.01)`, kept between 35 and 70.
5. Sirens level = half of today's level plus half of the route level, per slot.
6. No routed street within 500 m (outside Manhattan, part of Roosevelt Island): today's level, unchanged.

## Constants

- Window 365 days; slots of 7, 3 and 14 hours (`config.WINDOW_HOURS`).
- Reach 300 m, 30 m half-weight, exponent 1.33 (between a line, 1, and a point, 2), 10 m floor, road speeds: judgment.
- Offset 51.145 and scale 10.37: fitted so the median (51.69) and middle-half width (6.62) of route levels equal
  today's over the 298 baseline buildings and three slots.
- Floor 35, cap 70: today's `SIRENS_NONE_DB` and `SIRENS_SUM_CAP_DB`. The 0.01 in the log: judgment.
- Mix 0.5 / 0.5: judgment, no measured sirens say which estimate is better. "This block" 50 m and coverage 500 m:
  judgment.

## Check on the 298 Manhattan baseline buildings

- Spearman: today vs routes 0.51; today vs combined 0.87 (night 0.87, early 0.88, day 0.88).
- Middle-half width 6.6 today, 6.6 routes, 6.1 combined (standard deviation 6.5, 4.8, 4.9): averaging narrows it.
- Up, most: 66 East 34th and 20 East 35th Streets. Today gives them its no-facility floor (33), the nearest hospital
  being 900 m or more away; East 34th Street leads to the First Avenue hospitals (about 20 ambulance trips a day on
  the block), so the combined level rises 11 points.
- Down, most: 605 West 42nd Street (a firehouse 200 m away, but Rescue 1 has no engine company, so no trips start
  there); 310 East 70th and 233 East 69th Streets (a cancer hospital 340 to 420 m away that few ambulances use).

## Limits, worst first

1. Ambulances start at hospitals in the model but post on street corners in reality: trips pile onto hospital
   approaches, and the true spread across Midtown is flatter.
2. 30% of fire calls are unplaced (51,746 of 172,434): the alarm box list is from 2019, so newer boxes drop out.
   EMS is located by zip only; each call's street is inferred from fire units' medical calls.
3. Routes are modelled with assumed speeds, not observed. Nothing measures the sound, so the 0.5 mix and the
   distance weight cannot be tested against noise.
4. 7 of 48 firehouses have no engine company (ladder-only, Rescue, Squad, Marine) and send no trips here, though
   today's estimate counts them. The hospital list includes hospitals without an emergency department.
5. Roosevelt Island has no routes: the drive network is Manhattan only and the island is not joined to it.

## Evaluated, not shipped: NYPD Calls for Service (`n2zq-pubd`)

Police cars start from patrol, so they cannot be routed. Density of Critical and Serious calls (55,080 Manhattan
calls, Jul 2025 to Jun 2026, the latest 12 months published) is too sparse: the median address sees about 0.001
weighted calls an hour. Spearman 0.17 with today, 0.36 with routes; it tracks shops and crime. Left out.
