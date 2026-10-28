import Foundation

// The contract between the model, the data layer and the screens. The screens code against these
// types and the `NoiseDataSource` protocol only; the model fills `ScoreResult`; the data layer
// implements the protocol. Shapes mirror the Python prototype (noise_score/model.py) so the
// `*.expected.json` fixtures decode into `ScoreResult` directly.

// MARK: - The renter's answers

public enum Window: String, Codable, CaseIterable, Sendable {
    case night, early, day
    public var label: String {
        switch self {
        case .night: return "Night"
        case .early: return "Early"
        case .day: return "Day"
        }
    }
    /// The hours the window covers, as the deck states them.
    public var hours: String {
        switch self {
        case .night: return "10 pm to 5 am"
        case .early: return "5 to 8 am"
        case .day: return "8 am to 10 pm"
        }
    }
}

public enum Position: String, Codable, CaseIterable, Sendable {
    case front, rear, unknown
}

public enum Sleep: String, Codable, CaseIterable, Sendable {
    case light, normal, heavy
}

/// What bothers the renter. Each maps to one ingredient (config BOTHER_TO_INGREDIENT, M10 and M11).
public enum Bother: String, Codable, CaseIterable, Sendable {
    case neighbors, people, traffic, sirens, construction
    public var ingredient: String {
        switch self {
        case .neighbors: return "building"
        case .people: return "nightlife"
        case .traffic: return "street"
        case .sirens: return "sirens"
        case .construction: return "construction"
        }
    }
}

public struct Unit: Codable, Hashable, Sendable {
    /// 1 is the ground floor. nil means unknown.
    public var floor: Int?
    public var position: Position
    public init(floor: Int? = nil, position: Position = .unknown) { self.floor = floor; self.position = position }
}

public struct Profile: Codable, Hashable, Sendable {
    public var sleep: Sleep
    public var wfh: Bool
    public var bothers: [Bother]
    public init(sleep: Sleep = .normal, wfh: Bool = false, bothers: [Bother] = []) {
        self.sleep = sleep; self.wfh = wfh; self.bothers = bothers
    }
}

// MARK: - The score

/// One ingredient of the score: street, nightlife, building, sirens, construction.
public struct Ingredient: Codable, Hashable, Identifiable, Sendable {
    public var name: String
    public var label: String
    /// Pseudo-dB per window, after position and before the bother bump.
    public var levels: [Window: Double]
    /// The 0 to 100 score per window.
    public var scores: [Window: Int]
    public var rawLevel: Double
    /// Evidence lines a renter can check against their own apartment.
    public var evidence: [String]
    public var positionDb: Double
    public var temporary: Bool
    public var weightedUp: Bool

    public var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, label, levels, scores, rawLevel = "raw_level", evidence, positionDb = "position_db", temporary, weightedUp = "weighted_up"
    }

    public init(name: String, label: String, levels: [Window: Double], scores: [Window: Int], rawLevel: Double,
                evidence: [String], positionDb: Double, temporary: Bool, weightedUp: Bool) {
        self.name = name; self.label = label; self.levels = levels; self.scores = scores; self.rawLevel = rawLevel
        self.evidence = evidence; self.positionDb = positionDb; self.temporary = temporary; self.weightedUp = weightedUp
    }
}

public struct ScoreResult: Codable, Hashable, Sendable {
    /// 0 to 100, higher is quieter.
    public var score: Int
    /// A HowLoud-style number: roads, rail and businesses, no floor, no building, no hours.
    public var streetOnlyScore: Int
    public var byTime: [Window: Int]
    public var ingredients: [Ingredient]
    public var internalLevel: Double
    public var windowWeights: [Window: Double]
    public var caveats: [String]

    enum CodingKeys: String, CodingKey {
        case score, streetOnlyScore = "street_only_score", byTime = "by_time", ingredients
        case internalLevel = "internal_level", windowWeights = "window_weights", caveats
    }

    public init(score: Int, streetOnlyScore: Int, byTime: [Window: Int], ingredients: [Ingredient],
                internalLevel: Double, windowWeights: [Window: Double], caveats: [String]) {
        self.score = score; self.streetOnlyScore = streetOnlyScore; self.byTime = byTime; self.ingredients = ingredients
        self.internalLevel = internalLevel; self.windowWeights = windowWeights; self.caveats = caveats
    }
}

// MARK: - Data access

/// Where the screens get data. `LiveDataSource` talks to Socrata and GeoSearch and caches on disk;
/// `FixtureDataSource` replays the bundled fixtures for previews and for the no-network fallback.
public protocol NoiseDataSource: Sendable {
    /// Address suggestions for what the renter has typed so far. Empty for fewer than 3 characters.
    func suggest(_ text: String) async throws -> [GeoAddress]
    /// Every pull the score needs. Network first; the cache only when `allowCache` and the network fails.
    func pullAll(address: GeoAddress, allowCache: Bool) async throws -> Pulled
    /// The last cached pull for this address, if any. Never touches the network.
    func cached(address: GeoAddress) -> Pulled?
    /// Live 311 noise complaints for the map and list: recent, wide, with status and resolution.
    func recentComplaints(lat: Double, lng: Double, radiusM: Double, days: Int, allowCache: Bool) async throws -> PulledComplaints
}

/// A pull plus where it came from, so the screens can say "live" or "from Tuesday".
public struct Pulled: Codable, Hashable, Sendable {
    public var inputs: Inputs
    public var fetchedAt: Date
    public var fromCache: Bool
    public init(inputs: Inputs, fetchedAt: Date, fromCache: Bool) { self.inputs = inputs; self.fetchedAt = fetchedAt; self.fromCache = fromCache }
}

public struct PulledComplaints: Codable, Hashable, Sendable {
    public var complaints: [ComplaintRow]
    public var fetchedAt: Date
    public var fromCache: Bool
    public init(complaints: [ComplaintRow], fetchedAt: Date, fromCache: Bool) { self.complaints = complaints; self.fetchedAt = fetchedAt; self.fromCache = fromCache }
}

public enum NoiseError: Error, LocalizedError, Sendable {
    case offline
    case noMatch(String)
    case upstream(String)
    case decoding(String)

    public var errorDescription: String? {
        switch self {
        case .offline: return "No internet connection."
        case let .noMatch(q): return "No NYC address matches \"\(q)\"."
        case let .upstream(m): return "NYC Open Data did not answer: \(m)"
        case let .decoding(m): return "Unexpected data from NYC Open Data: \(m)"
        }
    }
}

// MARK: - Additive (KIT agent, 2026-10-21)

/// Lets `[Window: Double]` and `[Window: Int]` encode as JSON objects keyed "night"/"early"/"day", the shape
/// of the Python fixtures. Without this Swift encodes an enum-keyed dictionary as a flat array.
extension Window: CodingKeyRepresentable {}

/// `Unit` collides with Foundation's `Unit` (NSUnit) in any file that imports both Foundation and NoiseKit,
/// where the bare name is "ambiguous for type lookup". Write `NoiseKit.Unit` there, or use this alias.
public typealias ApartmentUnit = Unit
