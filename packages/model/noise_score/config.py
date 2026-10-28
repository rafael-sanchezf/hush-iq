"""Every tunable number in the model, in one place.

Each constant carries a tag like [M3] that points at the matching entry in DECISIONS.md.
Change the number here, never inside model.py.
"""

# ---------------------------------------------------------------- scale [M1]
# Internal unit is a pseudo-decibel exposure, roughly facade dB(A). 40 = very quiet, 80 = very loud.
# score = 100 - SCALE_SLOPE * (L - SCALE_QUIET_DB), clamped to 0..100. Higher = quieter (HowLoud's direction).
SCALE_QUIET_DB = 40.0
SCALE_SLOPE = 2.5

# ---------------------------------------------------------------- windows [M2]
# hour ranges [start, end), wrapping past midnight. Lengths: night 7h, early 3h, day 14h.
WINDOWS = {"night": (22, 5), "early": (5, 8), "day": (8, 22)}
WINDOW_HOURS = {"night": 7, "early": 3, "day": 14}

# Default (no profile) window weights: everyone sleeps, so night counts most.
DEFAULT_WINDOW_WEIGHTS = {"night": 1.0, "early": 0.6, "day": 0.6}

# ---------------------------------------------------------------- lookback and radii [M3]
LOOKBACK_MONTHS = 24
RADIUS_BLOCK_M = 100        # 311 street / vehicle / construction complaints
RADIUS_NIGHTLIFE_M = 150    # liquor licenses and commercial / party complaints
RADIUS_ROADS_M = 60         # street centerline segments, true distance to the line
ROADS_QUERY_RADIUS_M = 300  # Socrata matches line vertices only, so the query is wider than the radius
RADIUS_RAIL_M = 350         # elevated subway station (proxy for the line)

# ---------------------------------------------------------------- combination [M4]
# Ingredients combine by energy sum: L = 10*log10(sum 10^(Li/10)). One loud source dominates.
# Same-street road segments are deduplicated by name (max) before the sum.

# ---------------------------------------------------------------- street [M5]
# Base loudness by NYC CSCL rw_type and class. Source distance reference 10 m, line source: -3 dB per doubling.
ROAD_BASE_DB = {
    "highway": 75.0,   # rw_type 2
    "ramp": 70.0,      # rw_type 9
    "bridge": 68.0,    # rw_type 3
    "arterial": 66.0,  # rw_type 1 with >= 3 travel lanes
    "two_lane": 60.0,  # 2 travel lanes
    "one_lane": 56.0,  # 1 travel lane
}
ROAD_SNOW_CRITICAL_DB = 2.0   # DSNY snow priority C: bus or truck route, plowed first
ROAD_IGNORE_RW_TYPES = {"4", "5", "6", "7", "8", "10", "12", "13", "14"}  # tunnel, boardwalk, path, steps, driveway, alley, non-physical, u-turn, ferry
ROAD_SPEED_DB_PER_5MPH_OVER_25 = 1.0
ROAD_TWO_WAY_DB = 1.0
ROAD_REF_DISTANCE_M = 10.0
ROAD_DB_PER_DOUBLING = 3.0
RAIL_BASE_DB = 72.0            # elevated structure at 30 m
RAIL_REF_DISTANCE_M = 30.0
RAIL_DB_PER_DOUBLING = 4.0
RAIL_LOUD_STRUCTURES = {"Elevated", "Viaduct", "Embankment", "AtGrade", "OpenCut"}
STREET_WINDOW_OFFSET = {"night": -5.0, "early": -2.0, "day": 0.0}  # traffic volume by hour
STREET_311_REF_PER_YEAR = 4.0   # complaints/yr in a window at which the bump is 3 dB
STREET_311_MAX_DB = 10.0
STREET_NONE_DB = 45.0           # no road within radius

# ---------------------------------------------------------------- nightlife [M6]
VENUE_BASE_DB = {
    "bar": 66.0,          # Club, Cabaret, Additional Bar
    "venue": 62.0,        # Food & Beverage Business, Hotel, Catering, Brewer, Theatre, Vessel
    "restaurant": 58.0,   # Restaurant
}
VENUE_CLASSES = {
    "Club": "bar", "Cabaret": "bar", "Additional Bar": "bar", "Additional Bar-Seasonal": "bar",
    "Summer Club": "bar", "Additional bar- ball park, race track, etc": "bar",
    "Food & Beverage Business": "venue", "Summer Food & beverage business": "venue",
    "Summer Food & Beverage Business": "venue", "Hotel": "venue", "Catering Establishment": "venue",
    "Summer Catering Establishment": "venue", "Restaurant Brewer": "venue", "Micro-Brewer": "venue",
    "Legitimate theatre": "venue", "Additional bar- legitimate theater": "venue",
    "Outdoor Athletic Fields and Stadiums": "venue", "Vessel": "venue", "Summer Vessel": "venue",
    "Restaurant": "restaurant", "Summer Restaurant": "restaurant",
}
VENUE_REF_DISTANCE_M = 10.0
VENUE_DB_PER_DOUBLING = 6.0     # point source
VENUE_SUM_CAP_DB = 75.0
NIGHTLIFE_WINDOW_OFFSET = {"night": 0.0, "early": -8.0, "day": -8.0}
NIGHTLIFE_311_REF_PER_YEAR = 3.0
NIGHTLIFE_311_MAX_DB = 12.0
NIGHTLIFE_NONE_DB = 40.0
PARTY_DESCRIPTORS = {"Loud Music/Party", "Loud Talking"}   # counted under nightlife, never under street
GROUND_FLOOR_COMMERCIAL_DB = 5.0   # floor <= 2 in a building with commercial units

# ---------------------------------------------------------------- building (neighbors) [M7]
# Residential noise complaints per residential unit per year, 12 months to 2026-10-01,
# 311 'Noise - Residential' counts over PLUTO unitsres by borough (pulled 2026-10-21).
BOROUGH_BASELINE_PER_UNIT_YEAR = {
    "Manhattan": 70174 / 958956,
    "Brooklyn": 120568 / 1115989,
    "Queens": 83975 / 890313,
    "Bronx": 167713 / 591146,
    "Staten Island": 11836 / 180241,
}
CITY_BASELINE_PER_UNIT_YEAR = (70174 + 120568 + 83975 + 167713 + 11836) / (958956 + 1115989 + 890313 + 591146 + 180241)
BUILDING_SHRINK_K_UNIT_YEARS = 20.0   # Bayesian shrinkage toward the borough rate
BUILDING_BASELINE_DB = 46.0           # a building at exactly the borough rate
BUILDING_DB_PER_DOUBLING_OF_RATE = 10.0
BUILDING_MIN_DB = 40.0
BUILDING_MAX_DB = 72.0
BUILDING_MIN_COMPLAINTS_FOR_EMPIRICAL_HOURS = 8
# Citywide residential complaint timing, 12 months: intensity per hour vs uniform, in dB.
BUILDING_WINDOW_PRIOR_OFFSET = {"night": 1.7, "early": -3.1, "day": -0.6}
BUILDING_WINDOW_OFFSET_CLAMP = 6.0
PREWAR_DB = 4.0          # yearbuilt < 1940 and walk-up (wood joists, plaster, no slab)
PREWAR_ELEVATOR_DB = 1.0 # yearbuilt < 1940 and elevator building (masonry, steel, plaster)
MIDCENTURY_DB = 1.0      # 1940..1999
WALKUP_DB = 1.0          # bldgclass starting with A, B, C (no elevator, stair traffic)
TOP_FLOOR_DB = -3.0      # nobody above you
FIRST_FLOOR_DB = 2.0     # lobby, buzzer, front door, stairs
ABOVE_COMMERCIAL_DB = 2.0  # floor 2 in a building with commercial units

# ---------------------------------------------------------------- construction (temporary) [M8]
CONSTRUCTION_DESCRIPTOR_KEYS = ("construction", "jack", "nc1", "nc2", "nm1")
CONSTRUCTION_LOUD_WORK_TYPES = {
    "General Construction", "Structural", "Foundation", "Earth Work", "Full Demolition",
    "Support of Excavation", "Protection and Mechanical Methods", "Sidewalk Shed",
}
CONSTRUCTION_PERMIT_LOOKBACK_MONTHS = 18
CONSTRUCTION_BASE_DB = 40.0
CONSTRUCTION_311_DB_PER_DOUBLING = 4.0
CONSTRUCTION_PERMIT_DB_PER_DOUBLING = 3.0
CONSTRUCTION_MAX_BUMP_DB = 25.0
CONSTRUCTION_NONE_DB = 35.0
CONSTRUCTION_WINDOW_OFFSET = {"night": -15.0, "early": -3.0, "day": 0.0}

# ---------------------------------------------------------------- sirens [M11]
# Hospitals, firehouses, ambulance stations and police stations from the NYC Facilities Database (FacDB),
# as point sources whose vehicles leave along the street: 4 dB per doubling sits between a point (6) and a line (3).
RADIUS_SIRENS_M = 600         # about four avenue blocks
SIRENS_KINDS = {              # FacDB factype -> kind
    "HOSPITAL": "hospital", "ACUTE CARE HOSPITAL": "hospital",
    "FIREHOUSE": "fire", "AMBULANCE STATION": "fire",
    "POLICE STATION": "police",
}
SIRENS_BASE_DB = {"hospital": 64.0, "fire": 62.0, "police": 56.0}   # at the reference distance
SIRENS_KIND_LABEL = {"hospital": "hospital", "fire": "firehouse", "police": "police station"}
SIRENS_REF_DISTANCE_M = 50.0
SIRENS_DB_PER_DOUBLING = 4.0
SIRENS_SUM_CAP_DB = 70.0
SIRENS_NONE_DB = 35.0         # no facility within the radius
SIRENS_WINDOW_OFFSET = {"night": -3.0, "early": -2.0, "day": 0.0}

# ---------------------------------------------------------------- position [M9]
FLOOR_DB_PER_FLOOR = -1.0     # outdoor sources, each floor above the first
FLOOR_MAX_ATTENUATION_DB = -8.0
POSITION_DB = {"front": 0.0, "unknown": -2.0, "rear": -8.0}

# ---------------------------------------------------------------- profile [M10]
SLEEP_WINDOW_WEIGHTS = {
    "light": {"night": 1.5, "early": 1.2},
    "normal": {},
    "heavy": {"night": 0.7},
}
WFH_DAY_WEIGHT = 1.2
BOTHER_DB = 4.0   # added to each ingredient the renter names
BOTHER_TO_INGREDIENT = {"traffic": "street", "people": "nightlife", "neighbors": "building", "sirens": "sirens", "construction": "construction"}  # sirens: [M11]

# ---------------------------------------------------------------- technical [T*]
SOCRATA_APP_TOKEN = None          # [T3] set NOISE_SCORE_SOCRATA_TOKEN in the environment instead
CACHE_TTL_DAYS = 7                # [T4]
HTTP_TIMEOUT_S = 30.0
USER_AGENT = "noise-score-prototype/0.1 (Columbia HCD team project; ras2369@columbia.edu)"
