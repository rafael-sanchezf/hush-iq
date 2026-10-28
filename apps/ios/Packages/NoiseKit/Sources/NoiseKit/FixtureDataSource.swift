import Foundation

/// Replays the bundled sample for 2900 Broadway (`Samples/broadway.inputs.json`, `broadway.recent.json`):
/// SwiftUI previews, and the no-network, no-cache fallback. `suggest` returns the one bundled address for
/// any text. Everything it returns says `fromCache = true` with the sample's `as_of` date as `fetchedAt`.
public struct FixtureDataSource: NoiseDataSource {
    public init() {}

    static func resource(_ name: String) -> Data {
        guard let url = Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Samples"),
              let data = try? Data(contentsOf: url) else {
            fatalError("NoiseKit: bundled resource \(name).json is missing")
        }
        return data
    }

    /// The pull for 2900 Broadway, as the Python model made it.
    public static let sampleInputs: Inputs = {
        do { return try JSONDecoder().decode(Inputs.self, from: resource("broadway.inputs")) }
        catch { fatalError("NoiseKit: broadway.inputs.json does not decode: \(error)") }
    }()

    /// 30 days of 311 noise complaints within 500 m of 2900 Broadway.
    public static let sampleComplaints: [ComplaintRow] = {
        do { return try JSONDecoder().decode([ComplaintRow].self, from: resource("broadway.recent")) }
        catch { fatalError("NoiseKit: broadway.recent.json does not decode: \(error)") }
    }()

    public static var sampleAddress: GeoAddress { sampleInputs.address }

    /// Noon, local time, on the sample's `as_of` day.
    public static let sampleFetchedAt: Date = {
        let parts = sampleInputs.asOf.split(separator: "-").compactMap { Int($0) }
        var c = DateComponents()
        c.year = parts.count > 0 ? parts[0] : 2026; c.month = parts.count > 1 ? parts[1] : 10; c.day = parts.count > 2 ? parts[2] : 21
        c.hour = 12
        return Calendar.current.date(from: c) ?? Date()
    }()

    /// A ready-made answer set for previews: floor 4 at the front, a light sleeper bothered by traffic and people.
    public static let sampleUnit = Unit(floor: 4, position: .front)
    public static let sampleProfile = Profile(sleep: .light, wfh: false, bothers: [.traffic, .people, .sirens])
    public static var sampleResult: ScoreResult { Scorer.score(sampleInputs, unit: sampleUnit, profile: sampleProfile) }

    public static var samplePulled: Pulled { Pulled(inputs: sampleInputs, fetchedAt: sampleFetchedAt, fromCache: true) }
    public static var samplePulledComplaints: PulledComplaints {
        PulledComplaints(complaints: sampleComplaints, fetchedAt: sampleFetchedAt, fromCache: true)
    }

    public func suggest(_ text: String) async throws -> [GeoAddress] { [Self.sampleAddress] }

    public func pullAll(address: GeoAddress, allowCache: Bool) async throws -> Pulled { Self.samplePulled }

    public func cached(address: GeoAddress) -> Pulled? { Self.samplePulled }

    public func recentComplaints(lat: Double, lng: Double, radiusM: Double, days: Int, allowCache: Bool) async throws -> PulledComplaints {
        Self.samplePulledComplaints
    }
}
