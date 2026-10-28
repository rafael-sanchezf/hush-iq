import XCTest
@testable import NoiseKit

/// Hits NYC Open Data and GeoSearch for real. Skipped unless `NOISEKIT_LIVE=1` is in the environment:
/// `NOISEKIT_LIVE=1 swift test --filter LiveTests`. Prints the row counts for the report.
final class LiveTests: XCTestCase {
    func testLivePullFor2900Broadway() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["NOISEKIT_LIVE"] == "1", "set NOISEKIT_LIVE=1 to run against the network")
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("noisekit-live-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let ds = LiveDataSource(cache: NoiseCache(directory: dir))

        let suggestions = try await ds.suggest("2900 Broadway")
        print("LIVE suggest: \(suggestions.count) -> \(suggestions.map { $0.label ?? "?" })")
        let address = try XCTUnwrap(suggestions.first { ($0.label ?? "").localizedCaseInsensitiveContains("2900") } ?? suggestions.first)
        XCTAssertEqual(address.lat, 40.806, accuracy: 0.01)
        XCTAssertEqual(address.lng, -73.965, accuracy: 0.01)

        let pulled = try await ds.pullAll(address: address, allowCache: false)
        let i = pulled.inputs
        print("LIVE pull for \(address.label ?? "?") bbl \(address.bbl ?? "-") borough \(address.borough ?? "-"), as_of \(i.asOf), since \(i.since ?? "-")")
        print("LIVE rows: complaints \(i.complaints.count), liquor \(i.liquor.count), roads \(i.roads.count), stations \(i.stations.count), permits \(i.permits.count), facilities \(i.facilities.count), pluto \(i.pluto == nil ? "none" : "1 (\(i.pluto!.address ?? "?"), built \(i.pluto!.yearbuilt ?? "?"))")")
        print("LIVE facilities: \(i.facilities.map { "\($0.name) [\($0.kind)] \(Int(Geo.haversineM(address.lat, address.lng, $0.latitude, $0.longitude))) m" })")
        XCTAssertFalse(pulled.fromCache)
        XCTAssertGreaterThan(i.complaints.count, 50)
        XCTAssertGreaterThan(i.roads.count, 5)
        XCTAssertNotNil(i.pluto)
        XCTAssertEqual(i.sources.count, 8)

        let result = Scorer.score(i, unit: Unit(floor: 4, position: .front), profile: Profile(sleep: .light, bothers: [.traffic, .people]))
        print("LIVE score \(result.score), street-only \(result.streetOnlyScore), by_time \(Window.allCases.map { "\($0.rawValue) \(result.byTime[$0]!)" })")
        for ing in result.ingredients { print("LIVE   \(ing.name): \(ing.evidence)") }

        let recent = try await ds.recentComplaints(lat: address.lat, lng: address.lng, radiusM: 500, days: 30, allowCache: false)
        print("LIVE recent complaints (500 m, 30 days): \(recent.complaints.count); first: \(recent.complaints.first.map { "\($0.descriptor ?? "?") at \($0.incidentAddress ?? "?") \($0.createdDate ?? "?") \($0.status ?? "?")" } ?? "none")")
        XCTAssertGreaterThan(recent.complaints.count, 0)
        XCTAssertNotNil(recent.complaints.first?.status)

        // Second time round the pull is served from the cache without the network.
        let again = try await ds.pullAll(address: address, allowCache: false)
        XCTAssertEqual(again.inputs, i)
        XCTAssertNotNil(ds.cached(address: address))
    }
}
