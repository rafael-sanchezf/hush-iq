import XCTest
@testable import NoiseKit

final class ModelUnitTests: XCTestCase {

    func testWindowOf() {
        XCTAssertEqual(Scorer.windowOf(22), .night)
        XCTAssertEqual(Scorer.windowOf(23), .night)
        XCTAssertEqual(Scorer.windowOf(0), .night)
        XCTAssertEqual(Scorer.windowOf(4), .night)
        XCTAssertEqual(Scorer.windowOf(5), .early)
        XCTAssertEqual(Scorer.windowOf(7), .early)
        XCTAssertEqual(Scorer.windowOf(8), .day)
        XCTAssertEqual(Scorer.windowOf(21), .day)
        var counts: [Window: Int] = [:]
        for h in 0..<24 { counts[Scorer.windowOf(h), default: 0] += 1 }
        XCTAssertEqual(counts, [.night: 7, .early: 3, .day: 14])
    }

    func testEnergySum() {
        XCTAssertNil(Scorer.energySum([]))
        XCTAssertEqual(Scorer.energySum([60])!, 60, accuracy: 1e-9)
        XCTAssertEqual(Scorer.energySum([60, 60])!, 63.0103, accuracy: 1e-3)   // two equal sources: +3 dB
        XCTAssertEqual(Scorer.energySum([70, 40])!, 70.0043, accuracy: 1e-3)   // one loud source dominates
    }

    func testLogBump() {
        XCTAssertEqual(Scorer.logBump(0, ref: 4), 0, accuracy: 1e-12)
        XCTAssertEqual(Scorer.logBump(4, ref: 4), 3, accuracy: 1e-12)          // perDoubling at n == ref
        XCTAssertEqual(Scorer.logBump(12, ref: 4), 6, accuracy: 1e-12)         // (1 + 12/4) = 4 = two doublings
        XCTAssertEqual(Scorer.logBump(1000, ref: 4, cap: 10), 10, accuracy: 1e-12)
        XCTAssertEqual(Scorer.logBump(3, ref: 3, perDoubling: 4), 4, accuracy: 1e-12)
    }

    func testToScoreRoundsHalfToEvenLikePython() {
        XCTAssertEqual(Scorer.toScore(40), 100)
        XCTAssertEqual(Scorer.toScore(80), 0)
        XCTAssertEqual(Scorer.toScore(100), 0)
        XCTAssertEqual(Scorer.toScore(20), 100)
        XCTAssertEqual(Scorer.toScore(40.6), 98)   // 98.5 -> 98 (Python round, half to even)
        XCTAssertEqual(Scorer.toScore(41.0), 98)   // 97.5 -> 98
    }

    func testHourParsesPythonStyle() {
        XCTAssertEqual(Scorer.hour(of: "2026-10-21T00:35:53.000"), 0)
        XCTAssertEqual(Scorer.hour(of: "2026-10-21T23:05:00"), 23)
        XCTAssertEqual(Scorer.hour(of: "2026-10-21 07:00:00"), 7)
        XCTAssertEqual(Scorer.hour(of: "2026-10-21"), 0)
        XCTAssertNil(Scorer.hour(of: nil))
        XCTAssertNil(Scorer.hour(of: ""))
        XCTAssertNil(Scorer.hour(of: "yesterday"))
        XCTAssertNil(Scorer.hour(of: "2026-10-21T25:00:00"))
    }

    func testPythonFormatting() {
        XCTAssertEqual(Scorer.pyTitle("353 EAST 78 STREET"), "353 East 78 Street")
        XCTAssertEqual(Scorer.pyTitle("o'neil's way"), "O'Neil'S Way")       // Python's title(), warts included
        XCTAssertEqual(Scorer.squish("  541   WEST  113 STREET "), "541 WEST 113 STREET")
        XCTAssertEqual(Scorer.fmt(0.0731, 2), "0.07")
        XCTAssertEqual(Scorer.fmt(0.85, 1), "0.8")   // C and Python agree on the binary value of 0.85
        XCTAssertEqual(Scorer.round1(63.55), 63.5)   // Python round(63.55, 1) on the exact binary value
        XCTAssertEqual(Scorer.round1(63.65), 63.6)
    }

    func testFloorAttenuation() {
        XCTAssertEqual(Scorer.floorAttenuation(Unit(floor: nil)), 0)
        XCTAssertEqual(Scorer.floorAttenuation(Unit(floor: 1)), 0)
        XCTAssertEqual(Scorer.floorAttenuation(Unit(floor: 4)), -3)
        XCTAssertEqual(Scorer.floorAttenuation(Unit(floor: 40)), -8)
    }

    func testWindowWeights() {
        XCTAssertEqual(Scorer.windowWeights(nil), [.night: 1.0, .early: 0.6, .day: 0.6])
        XCTAssertEqual(Scorer.windowWeights(Profile(sleep: .light, wfh: true)), [.night: 1.5, .early: 1.2, .day: 1.2])
        XCTAssertEqual(Scorer.windowWeights(Profile(sleep: .heavy)), [.night: 0.7, .early: 0.6, .day: 0.6])
    }

    // MARK: sirens [M11]

    static func inputs(facilities: [FacilityRow]) -> Inputs {
        Inputs(address: GeoAddress(label: "test", lat: 40.8062, lng: -73.9647, bbl: "1018857501", borough: "Manhattan"),
               asOf: "2026-10-21", lookbackMonths: 24, facilities: facilities)
    }

    /// One hospital 100 m north: 64 - 4 * log2(100 / 50) = 60 before offsets.
    func testSirensOneHospitalAt100m() {
        let lat = 40.8062, lng = -73.9647
        let hospitalLat = lat + 100.001 / (Geo.earthR * .pi / 180)   // 100 m of latitude on the haversine sphere, a hair over so int() reads 100
        let d = Geo.haversineM(lat, lng, hospitalLat, lng)
        XCTAssertEqual(d, 100, accuracy: 0.01)
        let fac = FacilityRow(name: "Test Hospital", kind: .hospital, address: "1 Test Pl", latitude: hospitalLat, longitude: lng)
        let raw = Scorer.sirens(Self.inputs(facilities: [fac]), Unit(floor: nil, position: .front))
        XCTAssertEqual(raw.rawLevel, 60, accuracy: 0.01)
        XCTAssertEqual(raw.levels[.night]!, 57, accuracy: 0.01)   // night offset -3, front, no floor
        XCTAssertEqual(raw.levels[.early]!, 58, accuracy: 0.01)
        XCTAssertEqual(raw.levels[.day]!, 60, accuracy: 0.01)
        XCTAssertEqual(raw.evidence, [
            "1 emergency facilities within 600 m: 1 hospital",
            "Test Hospital (hospital), 1 Test Pl, 100 m",
        ])
        XCTAssertEqual(raw.name, "sirens"); XCTAssertEqual(raw.label, "Sirens"); XCTAssertFalse(raw.temporary)
    }

    func testSirensNoneAndMixedKinds() {
        let none = Scorer.sirens(Self.inputs(facilities: []), Unit())
        XCTAssertEqual(none.rawLevel, 35)
        XCTAssertEqual(none.evidence, ["no hospital, firehouse or police station within 600 m"])
        XCTAssertEqual(none.levels[.day]!, 35 - 2, accuracy: 1e-9)   // unknown position -2

        let lat = 40.8062, lng = -73.9647
        let far = FacilityRow(name: "Far", kind: .police, latitude: lat + 0.02, longitude: lng)   // ~2.2 km, dropped
        let fire1 = FacilityRow(name: "Engine 1", kind: .fire, address: "A St", latitude: lat + 0.002, longitude: lng)
        let fire2 = FacilityRow(name: "Engine 2", kind: .fire, address: "B St", latitude: lat + 0.004, longitude: lng)
        let police = FacilityRow(name: "26 Pct", kind: .police, address: "C St", latitude: lat, longitude: lng + 0.001)
        let raw = Scorer.sirens(Self.inputs(facilities: [far, fire1, fire2, police]), Unit(floor: 3, position: .rear))
        XCTAssertEqual(raw.evidence.first, "3 emergency facilities within 600 m: 2 firehouses, 1 police station")
        XCTAssertEqual(raw.evidence.count, 4)
        XCTAssertTrue(raw.evidence[1].hasPrefix("26 Pct (police station), C St, "))   // nearest first
        XCTAssertEqual(raw.positionDb, -2 - 8)
        XCTAssertLessThanOrEqual(raw.rawLevel, 70)
    }

    func testScoreIncludesSirensUnlessDisabled() {
        let inputs = Self.inputs(facilities: [])
        let with = Scorer.score(inputs, unit: Unit(), profile: Profile(bothers: [.sirens]))
        XCTAssertEqual(with.ingredients.map(\.name), ["street", "nightlife", "building", "sirens", "construction"])
        XCTAssertTrue(with.ingredients[3].weightedUp)
        let without = Scorer.score(inputs, unit: Unit(), profile: nil, options: ScoreOptions(sirens: false))
        XCTAssertEqual(without.ingredients.map(\.name), ["street", "nightlife", "building", "construction"])
        XCTAssertEqual(with.ingredients.first?.evidence.first, "no road segment within radius")
        XCTAssertEqual(with.caveats.count, 4)
    }

    func testSirensBotherMovesTheScore() throws {
        let (inputs, expected) = try FixtureComparisonTests.load("broadway")
        let hospital = FacilityRow(name: "Mount Sinai Morningside", kind: .hospital, address: "1111 Amsterdam Ave",
                                   latitude: 40.8054, longitude: -73.9617)
        var withHospital = inputs
        withHospital.facilities = [hospital]
        var calm = expected.profile ?? Profile()
        calm.bothers.removeAll { $0 == .sirens }
        let base = Scorer.score(withHospital, unit: expected.unit, profile: calm)
        var p = calm
        p.bothers.append(.sirens)
        let bothered = Scorer.score(withHospital, unit: expected.unit, profile: p)
        XCTAssertLessThanOrEqual(bothered.score, base.score)
        XCTAssertTrue(bothered.ingredients.first { $0.name == "sirens" }!.weightedUp)
        XCTAssertFalse(base.ingredients.first { $0.name == "sirens" }!.weightedUp)
    }
}
