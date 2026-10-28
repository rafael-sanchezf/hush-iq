import Foundation

/// The Manhattan baseline [M12]: where one apartment sits among Manhattan apartments, for the same renter.
///
/// The 0 to 100 score is absolute (M1), so on its own it cannot say whether a 60 is good for Manhattan.
/// `Samples/manhattan_baseline.json` is built by the Python prototype (`noise_score/baseline.py`): about 300
/// Manhattan residential lots, stratified by community district and drawn with probability proportional to
/// residential units, each scored by the same model at a facade-neutral unit (no floor, front). A rank
/// re-applies the renter's floor (capped at each building's height), side and answers to every sample, so
/// "quieter than 58%" means: the same person, at the same height and side, in 58% of Manhattan apartments,
/// would hear more. No network needed.
public struct Baseline: Decodable, Sendable {
    public struct Sample: Decodable, Sendable {
        public var bbl: String
        public var cd: String
        public var address: String?
        public var weight: Int
        public var floors: Int?
        public var commercial: Bool
        /// Per ingredient (street, nightlife, building, sirens, construction), per window, facade-neutral dB.
        public var levels: [String: [Window: Double]]
        public var plainScore: Int

        enum CodingKeys: String, CodingKey { case bbl, cd, address, weight, floors, commercial, levels, plainScore = "plain_score" }
    }

    public struct Universe: Decodable, Sendable {
        public var lots: Int
        public var units: Int
    }

    public var asOf: String
    public var seed: Int
    public var configSha: String
    public var universe: Universe
    public var samples: [Sample]

    enum CodingKeys: String, CodingKey { case asOf = "as_of", seed, configSha = "config_sha", universe, samples }

    /// The bundled Manhattan sample, or nil if the file is missing or unreadable.
    public static let manhattan: Baseline? = {
        guard let url = Bundle.module.url(forResource: "manhattan_baseline", withExtension: "json", subdirectory: "Samples"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(Baseline.self, from: data)
    }()

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        asOf = try c.decode(String.self, forKey: .asOf)
        seed = try c.decode(Int.self, forKey: .seed)
        configSha = try c.decode(String.self, forKey: .configSha)
        universe = try c.decode(Universe.self, forKey: .universe)
        samples = try c.decode([Sample].self, forKey: .samples)
    }

    static let ingredientOrder = ["street", "nightlife", "building", "sirens", "construction"]

    /// dB added to each ingredient for this unit in a building with these facts. Mirrors the position terms
    /// in `Scorer` (and `baseline.position_db` in Python) exactly.
    static func positionAdjustments(floors: Int, commercial: Bool, unit: Unit) -> [String: Double] {
        let att = Scorer.floorAttenuation(unit) + (Config.positionDb[unit.position] ?? Config.positionDb[.unknown]!)
        var adj: [String: Double] = ["street": att, "nightlife": att, "sirens": att, "construction": att, "building": 0]
        if let f = unit.floor, f != 0 {
            if commercial && f <= 2 { adj["nightlife"]! += Config.groundFloorCommercialDb }
            if floors > 0 && f >= floors { adj["building"]! += Config.topFloorDb }
            if f == 1 { adj["building"]! += Config.firstFloorDb }
            if f == 2 && commercial { adj["building"]! += Config.aboveCommercialDb }
        }
        return adj
    }

    /// The overall level this renter would have in this sampled building.
    public static func level(for s: Sample, unit: Unit, profile: Profile?) -> Double {
        var u = unit
        if let f = unit.floor, let floors = s.floors, floors > 0 { u = Unit(floor: min(f, floors), position: unit.position) }
        let adj = positionAdjustments(floors: s.floors ?? 0, commercial: s.commercial, unit: u)
        let raws = ingredientOrder.map { name -> Scorer.Raw in
            var levels: [Window: Double] = [:]
            for w in Window.allCases { levels[w] = (s.levels[name]?[w] ?? 0) + adj[name]! }
            return Scorer.Raw(name: name, label: name, levels: levels, rawLevel: 0, evidence: [], positionDb: 0, temporary: false)
        }
        return Scorer.combine(raws, profile).overall
    }

    public struct Rank: Hashable, Sendable {
        /// 0 to 100: the share of Manhattan apartments louder than this one, for this renter.
        public var quieterThan: Double
        public var medianScore: Int
        public var p25Score: Int
        public var p75Score: Int
        /// Sample points (a building hit twice counts twice).
        public var n: Int
        public var apartments: Int
        public var asOf: String
        /// One score per sample point, weights expanded, for the distribution strip.
        public var sampleScores: [Int]
    }

    /// Rank an overall level (`ScoreResult.internalLevel`) among the sample for this renter.
    public func rank(level: Double, unit: Unit, profile: Profile?) -> Rank {
        var total = 0.0, louder = 0.0, ties = 0.0
        var scores: [(score: Int, weight: Int)] = []
        for s in samples {
            let l: Double = Baseline.level(for: s, unit: unit, profile: profile)
            let w = Double(s.weight)
            total += w
            if l > level + 1e-6 { louder += w } else if abs(l - level) <= 1e-6 { ties += w }
            scores.append((Scorer.toScore(l), s.weight))
        }
        scores.sort { a, b in a.score == b.score ? a.weight < b.weight : a.score < b.score }
        func quantile(_ q: Double) -> Int {
            var acc = 0.0
            for item in scores {
                acc += Double(item.weight)
                if acc >= q * total - 1e-9 { return item.score }
            }
            return scores.last?.score ?? 0
        }
        let q = (100 * (louder + ties / 2) / total * 10).rounded() / 10
        return Rank(quieterThan: q, medianScore: quantile(0.5), p25Score: quantile(0.25), p75Score: quantile(0.75),
                    n: Int(total), apartments: universe.units, asOf: asOf,
                    sampleScores: scores.flatMap { Array(repeating: $0.score, count: $0.weight) })
    }
}

// MARK: - The verdict and the time-of-day ranks

/// Five steps, one fifth of Manhattan each, from the share of apartments louder than this one.
public enum Verdict: Int, CaseIterable, Hashable, Sendable {
    case veryLoud, loud, typical, quiet, veryQuiet

    public init(quieterThan q: Double) {
        self = Verdict(rawValue: max(0, min(Int((q / 20).rounded(.down)), 4)))!
    }

    public var label: String {
        switch self {
        case .veryLoud: return "Very loud"
        case .loud: return "Loud"
        case .typical: return "Typical"
        case .quiet: return "Quiet"
        case .veryQuiet: return "Very quiet"
        }
    }
}

/// Everyday sounds for reading a decibel number, nearest ten.
public enum Loudness {
    public static let anchors: [(db: Int, sound: String)] = [
        (30, "a whisper"), (40, "a quiet library"), (50, "a quiet office"),
        (60, "a normal conversation"), (70, "a busy street"), (80, "heavy traffic up close"),
    ]

    public static func anchor(_ db: Double) -> String {
        let nearest = anchors.min { abs(Double($0.db) - db) < abs(Double($1.db) - db) }!
        return nearest.sound
    }
}

extension Baseline.Rank {
    public var verdict: Verdict { Verdict(quieterThan: quieterThan) }
}

extension Baseline {
    /// One time slot's estimated level at the window: the ingredients after floor and side, with no answer
    /// bumps, since those are preferences, not sound.
    public static func physicalLevel(_ result: ScoreResult, _ window: Window) -> Double {
        Scorer.energySum(result.ingredients.compactMap { $0.levels[window] }) ?? 0
    }

    public struct WindowRank: Hashable, Sendable {
        public var window: Window
        public var levelDb: Double
        public var quieterThan: Double
        public var medianDb: Double
        public var p25Db: Double
        public var p75Db: Double
        public var verdict: Verdict { Verdict(quieterThan: quieterThan) }
    }

    /// Rank one time slot's physical level among the sample at the same floor (capped) and side.
    public func windowRank(_ result: ScoreResult, window: Window, unit: Unit) -> WindowRank {
        let mine = Baseline.physicalLevel(result, window)
        var pairs: [(level: Double, weight: Int)] = []
        for s in samples {
            var u = unit
            if let f = unit.floor, let floors = s.floors, floors > 0 { u = Unit(floor: min(f, floors), position: unit.position) }
            let adj = Baseline.positionAdjustments(floors: s.floors ?? 0, commercial: s.commercial, unit: u)
            var parts: [Double] = []
            for n in Baseline.ingredientOrder { parts.append((s.levels[n]?[window] ?? 0) + adj[n]!) }
            pairs.append((Scorer.energySum(parts) ?? 0, s.weight))
        }
        pairs.sort { $0.level < $1.level }
        var total = 0.0, louder = 0.0, ties = 0.0
        for p in pairs {
            let w = Double(p.weight)
            total += w
            if p.level > mine + 1e-6 { louder += w } else if abs(p.level - mine) <= 1e-6 { ties += w }
        }
        func quantile(_ q: Double) -> Double {
            var acc = 0.0
            for p in pairs {
                acc += Double(p.weight)
                if acc >= q * total - 1e-9 { return p.level }
            }
            return pairs.last?.level ?? 0
        }
        let q = (100 * (louder + ties / 2) / total * 10).rounded() / 10
        return WindowRank(window: window, levelDb: mine, quieterThan: q,
                          medianDb: quantile(0.5), p25Db: quantile(0.25), p75Db: quantile(0.75))
    }
}
