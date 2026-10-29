"""Every tunable number in engine v2, in one place. (Hackathon work, Oct 28.)

Each constant carries a tag like [V3] that points at the matching rule in ENGINE_V2.md.
v1's numbers stay in config.py, untouched; v2 reads the frozen ingredients and adds only these.
"""

# ---------------------------------------------------------------- time of day [V2]
# Each hour weighs by what the renter is doing then; each slot's weight is the sum of its hours.
ASLEEP_HOUR_WEIGHT = 3.0
AWAKE_HOUR_WEIGHT = 1.0
AWAKE_HOUR_WEIGHT_NOT_BOTHERED = 0.5   # "daytime noise does not bother me"
DEFAULT_SLEEP = (23, 7)                # asleep from 23:00 until 07:00

# ---------------------------------------------------------------- source weights [V3]
# Defaults from NYC health department noise surveys (Epi Data Briefs 45 and 105), mean of three readings,
# rounded. 311 complaint shares are not used: they over-count neighbors and under-count traffic.
SOURCE_WEIGHTS = {"street": 32.0, "sirens": 20.0, "building": 20.0, "nightlife": 15.0, "construction": 13.0}
TICKED_MULTIPLIER = 3.0
TICK_TO_SOURCE = {"traffic": "street", "people": "nightlife", "neighbors": "building", "sirens": "sirens",
                  "construction": "construction"}

# ---------------------------------------------------------------- caps [V6]
# Ranks are "quieter than X% of Manhattan", so the loudest 5% is quieter_than <= 5.
ANY_SOURCE_CAP_PCT = 5.0       # any source this loud caps the verdict at Loud
ANY_SOURCE_CAP_VERDICT = "Loud"
TICKED_SOURCE_CAP_PCT = 10.0   # a ticked source this loud caps the verdict at Typical
TICKED_SOURCE_CAP_VERDICT = "Typical"

# ---------------------------------------------------------------- source upgrades [V9]
# Each source keeps today's estimate and adds what actually passes (noise_score/upgrades/). Used only when the
# upgraded Manhattan sample was built with the same modules, so the renter and the sample are scored alike.
USE_UPGRADES = True

# ---------------------------------------------------------------- research recalibration [V10]
# From the noise research of 2026-10-29 (HIQ-71; packages/model/upgrades/RECALIBRATION.md has each number's
# source). Only numbers that differ between buildings move a rank, so only those change here. Offsets applied
# alike to every building (slot offsets, absolute siren levels) cannot move one and stay as config.py has them.

# Floor and side, used by v2.position_db for the renter and the sample alike.
STORY_HEIGHT_M = 3.4                # NEW-P-a: Manhattan median, 29,792 residential buildings (footprints x PLUTO)
STORY_HEIGHT_BY_FLOORS = ((6, 3.64), (20, 3.44), (None, 3.16))   # 2-6, 7-20 and 21+ floors, when the count is known
LINE_SOURCES = ("street", "sirens")  # P1: traffic, elevated rail and sirens arrive from passes tens of metres away
LINE_FLAT_M = 12.0                  # P1: no change through 12 m above the floor-1 window
LINE_DB_PER_M = -0.1                # P1: then this much per metre (measured canyons: 0 to -0.5 per floor)
LINE_MAX_DB = -6.0                  # P2
POINT_DB_PER_FLOOR = -1.0           # P1: nightlife and construction are nearby point sources, as today
POINT_MAX_DB = -8.0                 # P2
REAR_DB = {"street": -10.0, "nightlife": -8.0, "sirens": -8.0, "construction": -8.0}   # P3: -10 is road traffic only
UNKNOWN_SIDE_DB = -2.5              # P4: energy mean of front and rear
TOP_FLOOR_DB = -4.0                 # B16: one of four shared surfaces gone
FIRST_FLOOR_DB = 0.0                # B17: losing the unit below removes little impact noise
ABOVE_COMMERCIAL_DB = 0.0           # B18: the shop is already in nightlife's ground-floor term

# The five sources, recomputed on the same pulls (noise_score/recal.py).
ROAD_SPEED_DB_PER_5MPH = 2.0        # ST8: +2 per 5 mph over 25 ...
ROAD_SPEED_CLASSES = ("highway", "ramp")   # ... on free-flow roads only; Manhattan streets average under 7 mph
ROAD_TWO_WAY_DB = 0.0               # ST9: level follows total flow, not direction
STREET_311_MAX_DB = 3.0             # ST17: complaints count who calls, not how loud
STREET_NONE_DB = 50.0               # ST20: quiet-street background, Bronx and Hudson Square studies
VENUE_BASE_DB = {"bar": 66.0, "venue": 59.0, "restaurant": 47.0}   # N1 kept; N2 open door at 90 inside; N3 at 78
NIGHTLIFE_311_MAX_DB = 12.0         # N8 not taken (decision U6, HIQ-72): the research said 6, but the SONYC sensors
NIGHTLIFE_311_SLOTS = ("night", "early", "day")   # match nightlife through complaints, by day too; kept as config.py
MIDCENTURY_DB = ((1968, 2.0), (1977, 1.0), (2000, 0.0))   # B14: built before 1968, before 1977, before 2000
SIRENS_DB_PER_DOUBLING = 5.0        # SI4: 4.6 to 6.1 measured inside 60 m across 144 streets
CONSTRUCTION_311_DB_PER_DOUBLING = 2.0   # C4: after-hours complaints, a quarter duplicates, few summonses
HEAVY_VEHICLE_FACTOR = 15.0         # k: cars per truck or bus at city speeds (NYC: 13 medium truck, 18 bus)
HEAVY_VEHICLE_FACTOR_HIGHWAY = 8.0  # k: at 50 mph a bus is about 6 cars, so highways keep 8
TERRACE_SEATS = 24                  # Dining: seats when the licence does not say
TERRACE_DB_AT_10M = 46.0            # Dining: 46 + 10 log10(seats / 2) at 10 m, raised voices
TERRACE_HOURS = (19, 23)            # Dining: tables busy 7 pm to 11 pm, closed at 11 by law
