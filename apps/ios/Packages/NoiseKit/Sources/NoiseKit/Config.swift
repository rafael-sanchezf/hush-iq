import Foundation

/// Every tunable number in the model, in one place. A port of noise_score/config.py: same names in
/// camelCase, same values, and the same `[M*]` / `[T*]` tag pointing at the entry in DECISIONS.md.
/// Change a number here, never inside Model.swift.
public enum Config {

    // MARK: scale [M1]
    // Internal unit is a pseudo-decibel exposure, roughly facade dB(A). 40 = very quiet, 80 = very loud.
    // score = 100 - SCALE_SLOPE * (L - SCALE_QUIET_DB), clamped to 0..100. Higher = quieter (HowLoud's direction).
    public static let scaleQuietDb = 40.0           // [M1]
    public static let scaleSlope = 2.5              // [M1]

    // MARK: windows [M2]
    // Hour ranges [start, end), wrapping past midnight. Lengths: night 7h, early 3h, day 14h.
    public static let windows: [Window: (start: Int, end: Int)] = [.night: (22, 5), .early: (5, 8), .day: (8, 22)]  // [M2]
    public static let windowHours: [Window: Double] = [.night: 7, .early: 3, .day: 14]                            // [M2]
    /// Default (no profile) window weights: everyone sleeps, so night counts most.
    public static let defaultWindowWeights: [Window: Double] = [.night: 1.0, .early: 0.6, .day: 0.6]              // [M2]

    // MARK: lookback and radii [M3]
    public static let lookbackMonths = 24           // [M3]
    public static let radiusBlockM = 100.0          // [M3] 311 street / vehicle / construction complaints
    public static let radiusNightlifeM = 150.0      // [M3] liquor licenses and commercial / party complaints
    public static let radiusRoadsM = 60.0           // [M3] street centerline segments, true distance to the line
    public static let roadsQueryRadiusM = 300.0     // [M3] Socrata matches line vertices only, so the query is wider than the radius
    public static let radiusRailM = 350.0           // [M3] elevated subway station (proxy for the line)

    // MARK: combination [M4]
    // Ingredients combine by energy sum: L = 10*log10(sum 10^(Li/10)). One loud source dominates.
    // Same-street road segments are deduplicated by name (max) before the sum.

    // MARK: street [M5]
    /// Base loudness by NYC CSCL rw_type and class. Source distance reference 10 m, line source: -3 dB per doubling.
    public static let roadBaseDb: [String: Double] = [       // [M5]
        "highway": 75.0,   // rw_type 2
        "ramp": 70.0,      // rw_type 9
        "bridge": 68.0,    // rw_type 3
        "arterial": 66.0,  // rw_type 1 with >= 3 travel lanes
        "two_lane": 60.0,  // 2 travel lanes
        "one_lane": 56.0,  // 1 travel lane
    ]
    public static let roadSnowCriticalDb = 2.0      // [M5] DSNY snow priority C: bus or truck route, plowed first
    /// tunnel, boardwalk, path, steps, driveway, alley, non-physical, u-turn, ferry
    public static let roadIgnoreRwTypes: Set<String> = ["4", "5", "6", "7", "8", "10", "12", "13", "14"]  // [M5]
    public static let roadSpeedDbPer5MphOver25 = 1.0   // [M5]
    public static let roadTwoWayDb = 1.0            // [M5]
    public static let roadRefDistanceM = 10.0       // [M5]
    public static let roadDbPerDoubling = 3.0       // [M5]
    public static let railBaseDb = 72.0             // [M5] elevated structure at 30 m
    public static let railRefDistanceM = 30.0       // [M5]
    public static let railDbPerDoubling = 4.0       // [M5]
    public static let railLoudStructures: Set<String> = ["Elevated", "Viaduct", "Embankment", "AtGrade", "OpenCut"]  // [M5]
    public static let streetWindowOffset: [Window: Double] = [.night: -5.0, .early: -2.0, .day: 0.0]  // [M5] traffic volume by hour
    public static let street311RefPerYear = 4.0     // [M5] complaints/yr in a window at which the bump is 3 dB
    public static let street311MaxDb = 10.0         // [M5]
    public static let streetNoneDb = 45.0           // [M5] no road within radius

    // MARK: nightlife [M6]
    public static let venueBaseDb: [String: Double] = [      // [M6]
        "bar": 66.0,          // Club, Cabaret, Additional Bar
        "venue": 62.0,        // Food & Beverage Business, Hotel, Catering, Brewer, Theatre, Vessel
        "restaurant": 58.0,   // Restaurant
    ]
    public static let venueClasses: [String: String] = [     // [M6]
        "Club": "bar", "Cabaret": "bar", "Additional Bar": "bar", "Additional Bar-Seasonal": "bar",
        "Summer Club": "bar", "Additional bar- ball park, race track, etc": "bar",
        "Food & Beverage Business": "venue", "Summer Food & beverage business": "venue",
        "Summer Food & Beverage Business": "venue", "Hotel": "venue", "Catering Establishment": "venue",
        "Summer Catering Establishment": "venue", "Restaurant Brewer": "venue", "Micro-Brewer": "venue",
        "Legitimate theatre": "venue", "Additional bar- legitimate theater": "venue",
        "Outdoor Athletic Fields and Stadiums": "venue", "Vessel": "venue", "Summer Vessel": "venue",
        "Restaurant": "restaurant", "Summer Restaurant": "restaurant",
    ]
    public static let venueRefDistanceM = 10.0      // [M6]
    public static let venueDbPerDoubling = 6.0      // [M6] point source
    public static let venueSumCapDb = 75.0          // [M6]
    public static let nightlifeWindowOffset: [Window: Double] = [.night: 0.0, .early: -8.0, .day: -8.0]  // [M6]
    public static let nightlife311RefPerYear = 3.0  // [M6]
    public static let nightlife311MaxDb = 12.0      // [M6]
    public static let nightlifeNoneDb = 40.0        // [M6]
    /// Counted under nightlife, never under street.
    public static let partyDescriptors: Set<String> = ["Loud Music/Party", "Loud Talking"]  // [M6]
    public static let groundFloorCommercialDb = 5.0 // [M6] floor <= 2 in a building with commercial units

    // MARK: building (neighbors) [M7]
    /// Residential noise complaints per residential unit per year, 12 months to 2026-10-01,
    /// 311 'Noise - Residential' counts over PLUTO unitsres by borough (pulled 2026-10-21).
    public static let boroughBaselinePerUnitYear: [String: Double] = [   // [M7]
        "Manhattan": 70174.0 / 958956.0,
        "Brooklyn": 120568.0 / 1115989.0,
        "Queens": 83975.0 / 890313.0,
        "Bronx": 167713.0 / 591146.0,
        "Staten Island": 11836.0 / 180241.0,
    ]
    public static let cityBaselinePerUnitYear = (70174.0 + 120568.0 + 83975.0 + 167713.0 + 11836.0) / (958956.0 + 1115989.0 + 890313.0 + 591146.0 + 180241.0)  // [M7]
    public static let buildingShrinkKUnitYears = 20.0     // [M7] Bayesian shrinkage toward the borough rate
    public static let buildingBaselineDb = 46.0           // [M7] a building at exactly the borough rate
    public static let buildingDbPerDoublingOfRate = 10.0  // [M7]
    public static let buildingMinDb = 40.0                // [M7]
    public static let buildingMaxDb = 72.0                // [M7]
    public static let buildingMinComplaintsForEmpiricalHours = 8   // [M7]
    /// Citywide residential complaint timing, 12 months: intensity per hour vs uniform, in dB.
    public static let buildingWindowPriorOffset: [Window: Double] = [.night: 1.7, .early: -3.1, .day: -0.6]  // [M7]
    public static let buildingWindowOffsetClamp = 6.0     // [M7]
    public static let prewarDb = 4.0            // [M7] yearbuilt < 1940 and walk-up (wood joists, plaster, no slab)
    public static let prewarElevatorDb = 1.0    // [M7] yearbuilt < 1940 and elevator building (masonry, steel, plaster)
    public static let midcenturyDb = 1.0        // [M7] 1940..1999
    public static let walkupDb = 1.0            // [M7] bldgclass starting with A, B, C (no elevator, stair traffic)
    public static let topFloorDb = -3.0         // [M7] nobody above you
    public static let firstFloorDb = 2.0        // [M7] lobby, buzzer, front door, stairs
    public static let aboveCommercialDb = 2.0   // [M7] floor 2 in a building with commercial units

    // MARK: construction (temporary) [M8]
    public static let constructionDescriptorKeys = ["construction", "jack", "nc1", "nc2", "nm1"]  // [M8]
    public static let constructionLoudWorkTypes: Set<String> = [   // [M8]
        "General Construction", "Structural", "Foundation", "Earth Work", "Full Demolition",
        "Support of Excavation", "Protection and Mechanical Methods", "Sidewalk Shed",
    ]
    public static let constructionPermitLookbackMonths = 18   // [M8]
    public static let constructionBaseDb = 40.0               // [M8]
    public static let construction311DbPerDoubling = 4.0      // [M8]
    public static let constructionPermitDbPerDoubling = 3.0   // [M8]
    public static let constructionMaxBumpDb = 25.0            // [M8]
    public static let constructionNoneDb = 35.0               // [M8]
    public static let constructionWindowOffset: [Window: Double] = [.night: -15.0, .early: -3.0, .day: 0.0]  // [M8]

    // MARK: position [M9]
    public static let floorDbPerFloor = -1.0          // [M9] outdoor sources, each floor above the first
    public static let floorMaxAttenuationDb = -8.0    // [M9]
    public static let positionDb: [Position: Double] = [.front: 0.0, .unknown: -2.0, .rear: -8.0]  // [M9]

    // MARK: profile [M10]
    public static let sleepWindowWeights: [Sleep: [Window: Double]] = [   // [M10]
        .light: [.night: 1.5, .early: 1.2],
        .normal: [:],
        .heavy: [.night: 0.7],
    ]
    public static let wfhDayWeight = 1.2    // [M10]
    public static let botherDb = 4.0        // [M10] added to each ingredient the renter names
    /// Bother to ingredient name. The Swift `Bother.ingredient` carries the same map; this is the Python-shaped view.
    public static let botherToIngredient: [Bother: String] = [   // [M10] + sirens [M11]
        .traffic: "street", .people: "nightlife", .neighbors: "building", .construction: "construction", .sirens: "sirens",
    ]

    // MARK: sirens [M11]
    /// Point sources: hospitals (ambulance bays, ER), firehouses and ambulance stations, police stations.
    public static let radiusSirensM = 600.0   // [M11] about four avenue blocks
    public static let sirensBaseDb: [FacilityRow.Kind: Double] = [.hospital: 64.0, .fire: 62.0, .police: 56.0]  // [M11] at the reference distance
    public static let sirensRefDistanceM = 50.0       // [M11]
    public static let sirensDbPerDoubling = 4.0       // [M11] between a point and a line source: sirens move along streets
    public static let sirensSumCapDb = 70.0           // [M11]
    public static let sirensNoneDb = 35.0             // [M11] no facility within the radius
    public static let sirensWindowOffset: [Window: Double] = [.night: -3.0, .early: -2.0, .day: 0.0]  // [M11]

    // MARK: technical [T*]
    public static let socrataAppToken: String? = nil   // [T3] none bundled; a token only raises the rate limit
    public static let cacheTtlDays = 7                 // [T4]
    public static let cacheTtlRecentMinutes = 15       // [T4] recent complaints for the map and list
    public static let cacheTtlFacilitiesDays = 30      // [T4] the citywide facilities pull
    public static let httpTimeoutS = 30.0              // [T2]
    public static let httpRetries = 2                  // [T2] retries on a transient failure
    public static let userAgent = "noise-score-ios/0.1 (Columbia ENGI E4502 and IEME E4201; ras2369@columbia.edu)"  // [T2]
}
