import Foundation

// The score. A function-by-function port of noise_score/model.py: pure functions over the raw pulls,
// no network, so it is testable and replayable against the Python fixtures.
//
// Pipeline, per time window (night, early, day):
//   1. each ingredient -> a pseudo-dB exposure (street, nightlife, building, sirens, construction)
//   2. position adjusts the outdoor ingredients (floor, front/rear) and the building one (top floor, first floor)
//   3. the renter's profile adds dB to the ingredients they named and weights the windows
//   4. ingredients combine by energy sum within a window; windows average by weight
//   5. score = 100 - 2.5 * (L - 40), higher is quieter
//
// Evidence strings must match the Python text exactly: they are what the renter reads and what the
// fixture test diffs. Python formatting is reproduced where it matters: int() truncation, f"{x:.2f}",
// f"{x:.1f}x", str.title(), and "None" for a missing value inside an f-string.

public struct ScoreOptions: Sendable {
    /// Include the sirens ingredient (M11). Fixtures written before M11 are replayed with `false`.
    public var sirens = true
    public init(sirens: Bool = true) { self.sirens = sirens }
}

public enum Scorer {

    // MARK: - Helpers (public where the tests and the screens want them)

    /// L = 10*log10(sum 10^(Li/10)). nil for an empty list.
    public static func energySum(_ levels: [Double]) -> Double? {
        if levels.isEmpty { return nil }
        return 10 * log10(levels.reduce(0.0) { $0 + pow(10, $1 / 10) })
    }

    /// 100 - SCALE_SLOPE * (level - SCALE_QUIET_DB), clamped to 0..100, rounded half to even like Python's round().
    public static func toScore(_ level: Double) -> Int {
        let v = max(0.0, min(100.0, 100 - Config.scaleSlope * (level - Config.scaleQuietDb)))
        return Int(v.rounded(.toNearestOrEven))
    }

    public static func windowOf(_ hour: Int) -> Window {
        for w in Window.allCases {
            guard let (a, b) = Config.windows[w] else { continue }
            if a < b && a <= hour && hour < b { return w }
            if a > b && (hour >= a || hour < b) { return w }
        }
        return .day
    }

    /// 0 at n=0, `perDoubling` at n=ref, grows by perDoubling per doubling of (1 + n/ref).
    public static func logBump(_ nPerYear: Double, ref: Double, perDoubling: Double = 3.0, cap: Double? = nil) -> Double {
        let v = perDoubling * log2(1 + nPerYear / ref)
        if let cap { return min(cap, v) }
        return v
    }

    /// Python's `datetime.fromisoformat(created[:19]).hour`. The string is local time with no zone.
    public static func hour(of created: String?) -> Int? {
        guard let created else { return nil }
        let s = String(created.prefix(19))
        let u = Array(s.utf8)
        func digits(_ r: Range<Int>) -> Int? {
            guard r.upperBound <= u.count else { return nil }
            var v = 0
            for i in r {
                guard u[i] >= 48, u[i] <= 57 else { return nil }
                v = v * 10 + Int(u[i] - 48)
            }
            return v
        }
        guard let y = digits(0..<4), u.count >= 10, u[4] == 45, u[7] == 45, let m = digits(5..<7), let d = digits(8..<10),
              y > 0, (1...12).contains(m), (1...31).contains(d) else { return nil }
        if u.count == 10 { return 0 }
        guard u.count >= 13, u[10] == 84 || u[10] == 32, let h = digits(11..<13), (0...23).contains(h) else { return nil }
        return h
    }

    public static func floorAttenuation(_ unit: Unit) -> Double {
        guard let floor = unit.floor, floor > 1 else { return 0.0 }
        return max(Config.floorMaxAttenuationDb, Config.floorDbPerFloor * Double(floor - 1))
    }

    // MARK: - Python-shaped formatting

    /// Python's `float(x)`: nil when the string does not parse.
    static func f(_ s: String?) -> Double? {
        guard let s = s?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        return Double(s)
    }

    /// `_f(x, default) or default`: a missing, unparseable or zero value falls back.
    static func fOr(_ s: String?, _ fallback: Double) -> Double {
        let v = f(s) ?? fallback
        return v == 0 ? fallback : v
    }

    /// Python's `f"{x:.2f}"`.
    static func fmt(_ x: Double, _ places: Int) -> String { String(format: "%.\(places)f", x) }

    /// A value inside a Python f-string: None prints as "None".
    static func py(_ s: String?) -> String { s ?? "None" }

    /// Python's `str.title()`: the first letter of each run of cased characters upper, the rest lower.
    static func pyTitle(_ s: String) -> String {
        var out = ""
        var prevCased = false
        for ch in s {
            if ch.isLetter {
                out += prevCased ? ch.lowercased() : ch.uppercased()
                prevCased = true
            } else {
                out.append(ch)
                prevCased = false
            }
        }
        return out
    }

    /// Python's `" ".join(s.split())`.
    static func squish(_ s: String) -> String {
        s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
    }

    static func positionDb(_ unit: Unit) -> Double {
        Config.positionDb[unit.position] ?? Config.positionDb[.unknown]!
    }

    static func within(_ row: ComplaintRow, _ lat: Double, _ lng: Double, _ radiusM: Double) -> Bool {
        guard let la = f(row.latitude), let ln = f(row.longitude) else { return false }
        return Geo.haversineM(lat, lng, la, ln) <= radiusM
    }

    /// Counts in insertion order (Python dict), then a stable sort by count desc: ties keep first appearance.
    static func countsByFirstSeen(_ keys: [String]) -> [(key: String, n: Int)] {
        var order: [String] = []
        var counts: [String: Int] = [:]
        for k in keys {
            if counts[k] == nil { order.append(k) }
            counts[k, default: 0] += 1
        }
        return order.map { ($0, counts[$0]!) }
    }

    static func stableSorted<T>(_ xs: [T], by less: (T, T) -> Bool) -> [T] {
        xs.enumerated().sorted { a, b in
            if less(a.element, b.element) { return true }
            if less(b.element, a.element) { return false }
            return a.offset < b.offset
        }.map(\.element)
    }

    static func topDescriptors(_ rows: [ComplaintRow], k: Int = 2) -> String {
        let counts = stableSorted(countsByFirstSeen(rows.map { ($0.descriptor?.isEmpty == false) ? $0.descriptor! : "?" })) { $0.n > $1.n }.prefix(k)
        if counts.isEmpty { return "" }
        return " (" + counts.map { "\($0.key.lowercased()) \($0.n)" }.joined(separator: ", ") + ")"
    }

    static func windowCounts(_ rows: [ComplaintRow], years: Double) -> (perYear: [Window: Double], n: Double) {
        var counts: [Window: Double] = [.night: 0, .early: 0, .day: 0]
        for r in rows {
            if let h = hour(of: r.createdDate) { counts[windowOf(h), default: 0] += 1 }
        }
        var perYear: [Window: Double] = [:]
        for w in Window.allCases { perYear[w] = counts[w]! / years }
        return (perYear, counts.values.reduce(0, +))
    }

    static func hasCommercial(_ pl: PlutoRow?) -> Bool {
        guard let pl else { return false }
        let tot = f(pl.unitstotal) ?? 0, res = f(pl.unitsres) ?? 0
        return tot > res || ["4", "5"].contains(pl.landuse ?? "")
    }

    /// An ingredient before rounding and scoring.
    struct Raw {
        var name: String
        var label: String
        var levels: [Window: Double]
        var rawLevel: Double
        var evidence: [String]
        var positionDb: Double
        var temporary: Bool
    }

    // MARK: - 1. street

    static func street(_ inputs: Inputs, _ unit: Unit) -> Raw {
        let lat = inputs.address.lat, lng = inputs.address.lng
        let years = Double(inputs.lookbackMonths) / 12
        var ev: [String] = []
        struct S { var level: Double; var cls: String; var d: Double; var lanes: Int; var speed: Double; var critical: Bool }
        var order: [String] = []
        var byStreet: [String: S] = [:]
        for r in inputs.roads {
            let rw = r.rwType ?? ""
            if Config.roadIgnoreRwTypes.contains(rw) { continue }
            let travel = Int(fOr(r.numberTravelLanes, 1))
            let cls: String
            if rw == "2" { cls = "highway" }
            else if rw == "9" { cls = "ramp" }
            else if rw == "3" { cls = "bridge" }
            else if travel >= 3 { cls = "arterial" }
            else if travel == 2 { cls = "two_lane" }
            else { cls = "one_lane" }
            var base = Config.roadBaseDb[cls]!
            let critical = r.snowPriority == "C" && rw == "1"
            if critical { base += Config.roadSnowCriticalDb }
            let speed = fOr(r.postedSpeed, 25)
            base += max(0.0, (speed - 25) / 5) * Config.roadSpeedDbPer5MphOver25
            if r.trafdir == "TW" { base += Config.roadTwoWayDb }
            guard var d = Geo.pointToMultilineM(lat, lng, r.theGeom), d <= Config.radiusRoadsM else { continue }
            d = max(d, Config.roadRefDistanceM)
            let level = base - Config.roadDbPerDoubling * log2(d / Config.roadRefDistanceM)
            let name = (r.fullStreetName ?? "unnamed").trimmingCharacters(in: .whitespacesAndNewlines)
            if let cur = byStreet[name], cur.level >= level { continue }
            if byStreet[name] == nil { order.append(name) }
            byStreet[name] = S(level: level, cls: cls, d: d, lanes: travel, speed: speed, critical: critical)
        }
        var levels: [Double] = []
        for name in stableSorted(order, by: { byStreet[$0]!.level > byStreet[$1]!.level }) {
            let s = byStreet[name]!
            levels.append(s.level)
            ev.append("\(name): \(s.cls.replacingOccurrences(of: "_", with: " ")), \(s.lanes) travel lane\(s.lanes != 1 ? "s" : ""), \(Int(s.speed)) mph"
                      + (s.critical ? ", bus or truck route" : "") + ", \(Int(s.d)) m away")
        }
        // elevated rail (station structure as a proxy for the line)
        for st in inputs.stations {
            guard let structure = st.structure, Config.railLoudStructures.contains(structure),
                  let sla = f(st.gtfsLatitude), let sln = f(st.gtfsLongitude) else { continue }
            var d = Geo.haversineM(lat, lng, sla, sln)
            d = max(d, Config.railRefDistanceM)
            let level = Config.railBaseDb - Config.railDbPerDoubling * log2(d / Config.railRefDistanceM)
            levels.append(level)
            ev.append("\(structure) subway (\(py(st.daytimeRoutes))) at \(py(st.stopName)), \(Int(d)) m away")
        }
        var base: Double
        if let b = energySum(levels) {
            base = b
        } else {
            base = Config.streetNoneDb
            ev.append("no road segment within radius")
        }
        // 311 pressure: street/sidewalk and vehicle complaints within the block radius
        let rows = inputs.complaints.filter { r in
            (r.complaintType == "Noise - Vehicle"
             || (r.complaintType == "Noise - Street/Sidewalk" && !Config.partyDescriptors.contains(r.descriptor ?? "")))
            && within(r, lat, lng, Config.radiusBlockM)
        }
        let (perYear, n) = windowCounts(rows, years: years)
        if n > 0 {
            ev.append("\(Int(n)) vehicle noise complaints to 311 within \(Int(Config.radiusBlockM)) m in \(inputs.lookbackMonths) months" + topDescriptors(rows))
        }
        let att = floorAttenuation(unit) + positionDb(unit)
        var out: [Window: Double] = [:]
        for w in Window.allCases {
            let bump = logBump(perYear[w]!, ref: Config.street311RefPerYear, cap: Config.street311MaxDb)
            out[w] = base + Config.streetWindowOffset[w]! + bump + att
        }
        return Raw(name: "street", label: "Street", levels: out, rawLevel: base, evidence: ev, positionDb: att, temporary: false)
    }

    // MARK: - 2. nightlife

    static func nightlife(_ inputs: Inputs, _ unit: Unit, _ pl: PlutoRow?) -> Raw {
        let lat = inputs.address.lat, lng = inputs.address.lng
        let years = Double(inputs.lookbackMonths) / 12
        var ev: [String] = []
        struct V { var level: Double; var cls: String; var name: String?; var address: String?; var d: Double }
        var venues: [V] = []
        for r in inputs.liquor {
            guard let desc = r.description, let cls = Config.venueClasses[desc] else { continue }
            guard case let .point(vlng, vlat)? = r.georeference else { continue }
            let d = max(Geo.haversineM(lat, lng, vlat, vlng), Config.venueRefDistanceM)
            let level = Config.venueBaseDb[cls]! - Config.venueDbPerDoubling * log2(d / Config.venueRefDistanceM)
            venues.append(V(level: level, cls: cls, name: r.legalname, address: r.actualaddressofpremises, d: d))
        }
        venues = stableSorted(venues) { $0.level > $1.level }
        var base: Double
        if let b = energySum(venues.map(\.level)) {
            base = min(b, Config.venueSumCapDb)
            let kinds = countsByFirstSeen(venues.map(\.cls)).sorted { $0.key < $1.key }
            ev.append("\(venues.count) licensed venues within \(Int(Config.radiusNightlifeM)) m: "
                      + kinds.map { "\($0.n) \($0.key)\($0.n != 1 ? "s" : "")" }.joined(separator: ", "))
            for v in venues.prefix(3) {
                ev.append("nearest loud: \(py(v.name)) (\(v.cls)), \(py(v.address)), \(Int(v.d)) m")
            }
        } else {
            base = Config.nightlifeNoneDb
            ev.append("no licensed bar or restaurant within \(Int(Config.radiusNightlifeM)) m")
        }
        let rows = inputs.complaints.filter { r in
            ["Noise - Commercial", "Noise - Street/Sidewalk", "Noise - Park"].contains(r.complaintType ?? "")
            && Config.partyDescriptors.contains(r.descriptor ?? "")
            && within(r, lat, lng, Config.radiusNightlifeM)
        }
        let (perYear, n) = windowCounts(rows, years: years)
        if n > 0 {
            ev.append("\(Int(n)) party, music or loud-talking complaints within \(Int(Config.radiusNightlifeM)) m in \(inputs.lookbackMonths) months; "
                      + "\(Int(perYear[.night]! * years)) of them 10 pm to 5 am")
        }
        var att = floorAttenuation(unit) + positionDb(unit)
        if hasCommercial(pl), let floor = unit.floor, floor != 0, floor <= 2 {
            att += Config.groundFloorCommercialDb
            ev.append("commercial space on the ground floor of this building")
        }
        var out: [Window: Double] = [:]
        for w in Window.allCases {
            let bump = logBump(perYear[w]!, ref: Config.nightlife311RefPerYear, cap: Config.nightlife311MaxDb)
            out[w] = base + Config.nightlifeWindowOffset[w]! + bump + att
        }
        return Raw(name: "nightlife", label: "Nightlife", levels: out, rawLevel: base, evidence: ev, positionDb: att, temporary: false)
    }

    // MARK: - 3. building (neighbors)

    static func building(_ inputs: Inputs, _ unit: Unit, _ pl: PlutoRow?) -> Raw {
        let a = inputs.address
        let years = Double(inputs.lookbackMonths) / 12
        var ev: [String] = []
        let rows = inputs.complaints.filter { r in
            r.complaintType == "Noise - Residential" && (a.bbl ?? "").isEmpty == false && r.bbl == a.bbl
        }
        let n = Double(rows.count)
        var units = f(pl?.unitsres) ?? 0
        if units <= 0 {
            units = 1.0
            ev.append("residential unit count unknown; treated as one unit")
        }
        let baseline = a.borough.flatMap { Config.boroughBaselinePerUnitYear[$0] } ?? Config.cityBaselinePerUnitYear
        let rawRate = n / (units * years)
        let rate = (n + Config.buildingShrinkKUnitYears * baseline) / (units * years + Config.buildingShrinkKUnitYears)
        var level = Config.buildingBaselineDb + Config.buildingDbPerDoublingOfRate * log2(rate / baseline)
        level = max(Config.buildingMinDb, min(Config.buildingMaxDb, level))
        ev.append("\(Int(n)) residential noise complaints to 311 at this building in \(inputs.lookbackMonths) months, "
                  + "\(Int(units)) units: \(fmt(rawRate, 2)) per unit-year vs \(fmt(baseline, 2)) for \(py(a.borough)) "
                  + "(\(fmt(rate / baseline, 1))x after shrinkage)" + topDescriptors(rows))
        // construction era and type
        let yb = Int(f(pl?.yearbuilt) ?? 0)
        let bc = pl?.bldgclass ?? ""
        let floors = Int(f(pl?.numfloors) ?? 0)
        var era = 0.0
        let walkup = ["A", "B", "C"].contains(String(bc.prefix(1)))
        if yb > 0 && yb < 1940 && walkup {
            era = Config.prewarDb
            ev.append("built \(yb): pre-war walk-up, wood joists and plaster carry footsteps")
        } else if yb > 0 && yb < 1940 {
            era = Config.prewarElevatorDb
            ev.append("built \(yb): pre-war elevator building, masonry and plaster")
        } else if yb >= 1940 && yb < 2000 {
            era = Config.midcenturyDb
            ev.append("built \(yb)")
        } else if yb >= 2000 {
            ev.append("built \(yb): post-2000, likely concrete slab")
        }
        if walkup {
            era += Config.walkupDb
            ev.append("class \(bc): walk-up, stairs pass every door")
        } else if bc.hasPrefix("D") {
            ev.append("class \(bc): elevator building")
        }
        // per-window timing: empirical if enough complaints, else the citywide prior
        var offsets = Config.buildingWindowPriorOffset
        if Int(n) >= Config.buildingMinComplaintsForEmpiricalHours {
            let (perYear, _) = windowCounts(rows, years: years)
            var total = perYear.values.reduce(0, +)
            if total == 0 { total = 1 }
            for w in Window.allCases {
                let sharePerHour = (perYear[w]! / total) / Config.windowHours[w]!
                let o = 10 * log10(max(sharePerHour, 1e-6) / (1.0 / 24))
                offsets[w] = max(-Config.buildingWindowOffsetClamp, min(Config.buildingWindowOffsetClamp, o))
            }
            ev.append("complaint hours at this building: " + Window.allCases.map {
                "\($0.rawValue) \(Int((perYear[$0]! * years).rounded(.toNearestOrEven)))"
            }.joined(separator: ", "))
        }
        // position inside the building
        var pos = 0.0
        if let floor = unit.floor, floor != 0 {
            if floors != 0 && floor >= floors {
                pos += Config.topFloorDb
                ev.append("floor \(floor) of \(floors): top floor, nobody above")
            }
            if floor == 1 {
                pos += Config.firstFloorDb
                ev.append("first floor: lobby, buzzer and front door")
            }
            if floor == 2 && hasCommercial(pl) {
                pos += Config.aboveCommercialDb
                ev.append("second floor above a commercial space")
            }
        }
        var out: [Window: Double] = [:]
        for w in Window.allCases { out[w] = level + era + offsets[w]! + pos }
        return Raw(name: "building", label: "Building", levels: out, rawLevel: level + era, evidence: ev, positionDb: pos, temporary: false)
    }

    // MARK: - 4. sirens [M11]

    static func sirens(_ inputs: Inputs, _ unit: Unit) -> Raw {
        let lat = inputs.address.lat, lng = inputs.address.lng
        var ev: [String] = []
        struct Fac { var level: Double; var row: FacilityRow; var d: Double }
        var near: [Fac] = []
        for r in inputs.facilities {
            let d = Geo.haversineM(lat, lng, r.latitude, r.longitude)
            if d > Config.radiusSirensM { continue }
            let level = Config.sirensBaseDb[r.kind]! - Config.sirensDbPerDoubling * log2(max(d, Config.sirensRefDistanceM) / Config.sirensRefDistanceM)
            near.append(Fac(level: level, row: r, d: d))
        }
        var base: Double
        if let b = energySum(near.map(\.level)) {
            base = min(b, Config.sirensSumCapDb)
            let kinds: [(FacilityRow.Kind, String, String)] = [(.hospital, "hospital", "hospitals"), (.fire, "firehouse", "firehouses"), (.police, "police station", "police stations")]
            let parts: [String] = kinds.compactMap { entry in
                let (kind, one, many) = entry
                let k = near.filter { $0.row.kind == kind }.count
                return k == 0 ? nil : "\(k) \(k == 1 ? one : many)"
            }
            ev.append("\(near.count) emergency facilities within \(Int(Config.radiusSirensM)) m: " + parts.joined(separator: ", "))
            for fc in stableSorted(near, by: { $0.d < $1.d }).prefix(3) {
                ev.append("\(fc.row.name) (\(kindLabel(fc.row.kind))), " + ((fc.row.address?.isEmpty == false) ? "\(fc.row.address!), " : "") + "\(Int(fc.d)) m")
            }
        } else {
            base = Config.sirensNoneDb
            ev.append("no hospital, firehouse or police station within \(Int(Config.radiusSirensM)) m")
        }
        let att = floorAttenuation(unit) + positionDb(unit)
        var out: [Window: Double] = [:]
        for w in Window.allCases { out[w] = base + Config.sirensWindowOffset[w]! + att }
        return Raw(name: "sirens", label: "Sirens", levels: out, rawLevel: base, evidence: ev, positionDb: att, temporary: false)
    }

    static func kindLabel(_ k: FacilityRow.Kind) -> String {
        switch k {
        case .hospital: return "hospital"
        case .fire: return "firehouse"
        case .police: return "police station"
        }
    }

    // MARK: - 5. construction (temporary)

    static func construction(_ inputs: Inputs, _ unit: Unit) -> Raw {
        let lat = inputs.address.lat, lng = inputs.address.lng
        let years = Double(inputs.lookbackMonths) / 12
        var ev: [String] = []
        let rows = inputs.complaints.filter { r in
            guard r.complaintType == "Noise" else { return false }
            let d = (r.descriptor ?? "").lowercased()
            return Config.constructionDescriptorKeys.contains { d.contains($0) } && within(r, lat, lng, Config.radiusBlockM)
        }
        let n311 = rows.count
        // Python: today = date.fromisoformat(inputs["as_of"]); never Date(), so fixtures replay.
        var today = String(inputs.asOf.prefix(10))
        if today.count != 10 { today = Self.isoDate(Date()) }
        var active: [PermitRow] = []
        for p in inputs.permits {
            guard let wt = p.workType, Config.constructionLoudWorkTypes.contains(wt) else { continue }
            let exp = String((p.expiredDate ?? "").prefix(10))
            if !exp.isEmpty, exp.count == 10, today.count == 10, exp < today { continue }
            active.append(p)
        }
        if n311 > 0 {
            ev.append("\(n311) construction noise complaints within \(Int(Config.radiusBlockM)) m in \(inputs.lookbackMonths) months" + topDescriptors(rows))
        }
        if !active.isEmpty {
            let kinds = stableSorted(countsByFirstSeen(active.map { $0.workType ?? "None" })) { $0.n > $1.n }
            ev.append("\(active.count) unexpired loud-work permits on this tax block: "
                      + kinds.map { "\($0.key) \($0.n)" }.joined(separator: ", "))
            for p in active.prefix(2) {
                ev.append(pyTitle(squish("\(p.houseNo ?? "") \(p.streetName ?? "")")) + ": \(py(p.workType)) to \((p.expiredDate ?? "").prefix(10))")
            }
        }
        var base: Double
        if n311 == 0 && active.isEmpty {
            base = Config.constructionNoneDb
            ev.append("no construction complaints or loud-work permits nearby")
        } else {
            let bump = Config.construction311DbPerDoubling * log2(1 + Double(n311) / years)
                + Config.constructionPermitDbPerDoubling * log2(1 + Double(active.count))
            base = Config.constructionBaseDb + min(Config.constructionMaxBumpDb, bump)
        }
        let att = floorAttenuation(unit) + positionDb(unit)
        var out: [Window: Double] = [:]
        for w in Window.allCases { out[w] = base + Config.constructionWindowOffset[w]! + att }
        return Raw(name: "construction", label: "Construction", levels: out, rawLevel: base, evidence: ev, positionDb: att, temporary: true)
    }

    // MARK: - 6. combine

    public static func windowWeights(_ profile: Profile?) -> [Window: Double] {
        var w = Config.defaultWindowWeights
        if let profile {
            for (k, v) in Config.sleepWindowWeights[profile.sleep] ?? [:] { w[k] = v }
            if profile.wfh { w[.day] = Config.wfhDayWeight }
        }
        return w
    }

    static func combine(_ ingredients: [Raw], _ profile: Profile?) -> (overall: Double, perWindow: [Window: Double], weights: [Window: Double], bothers: Set<String>) {
        let bothers = Set((profile?.bothers ?? []).compactMap { Config.botherToIngredient[$0] })
        var perWindow: [Window: Double] = [:]
        for w in Window.allCases {
            perWindow[w] = energySum(ingredients.map { $0.levels[w]! + (bothers.contains($0.name) ? Config.botherDb : 0.0) })!
        }
        let weights = windowWeights(profile)
        let overall = Window.allCases.reduce(0.0) { $0 + perWindow[$1]! * weights[$1]! } / weights.values.reduce(0, +)
        return (overall, perWindow, weights, bothers)
    }

    /// A HowLoud-style number: roads, rail and nearby businesses, one value, no floor, no building, no hours.
    public static func streetOnly(_ inputs: Inputs) -> Int {
        let ground = Unit(floor: nil, position: .front)
        let s = street(inputs, ground)
        let n = nightlife(inputs, ground, nil)
        let level = energySum([s.rawLevel, n.rawLevel - 4.0])!   // businesses by day, HowLoud's "local"
        return toScore(level)
    }

    /// "YYYY-MM-DD" in the device's calendar, Python's `date.today().isoformat()`.
    public static func isoDate(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    /// Python's `round(x, 1)`: correctly rounded on the exact binary value, which printf also does
    /// (`(x * 10).rounded() / 10` is not: 63.55 * 10 lands on 635.5 and goes up, Python says 63.5).
    static func round1(_ x: Double) -> Double { Double(String(format: "%.1f", x)) ?? x }

    // MARK: - 7. score

    public static func score(_ inputs: Inputs, unit: Unit, profile: Profile?, options: ScoreOptions = ScoreOptions()) -> ScoreResult {
        let pl = inputs.pluto
        var ings = [street(inputs, unit), nightlife(inputs, unit, pl), building(inputs, unit, pl)]
        if options.sirens { ings.append(sirens(inputs, unit)) }
        ings.append(construction(inputs, unit))
        let (overall, perWindow, weights, bothers) = combine(ings, profile)
        let ingredients = ings.map { raw -> Ingredient in
            var scores: [Window: Int] = [:]
            var levels: [Window: Double] = [:]
            for w in Window.allCases {
                scores[w] = toScore(raw.levels[w]!)
                levels[w] = round1(raw.levels[w]!)
            }
            return Ingredient(name: raw.name, label: raw.label, levels: levels, scores: scores, rawLevel: round1(raw.rawLevel),
                              evidence: raw.evidence, positionDb: round1(raw.positionDb), temporary: raw.temporary,
                              weightedUp: bothers.contains(raw.name))
        }
        var byTime: [Window: Int] = [:]
        for w in Window.allCases { byTime[w] = toScore(perWindow[w]!) }
        return ScoreResult(
            score: toScore(overall),
            streetOnlyScore: streetOnly(inputs),
            byTime: byTime,
            ingredients: ingredients,
            internalLevel: round1(overall),
            windowWeights: weights,
            caveats: [
                "311 counts measure who complains, not decibels; the count is shown so you can judge it.",
                "Street loudness is modelled from road class, lanes and speed, not measured.",
                "Elevated subway proximity uses the nearest station's structure as a proxy for the track.",
                "Construction is temporary; permits expire and the bar may close.",
            ]
        )
    }
}
