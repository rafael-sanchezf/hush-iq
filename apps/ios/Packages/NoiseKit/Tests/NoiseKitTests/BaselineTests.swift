import XCTest
@testable import NoiseKit

/// The Manhattan baseline [M12]: the Swift rank must match the Python rank for the four fixtures.
final class BaselineTests: XCTestCase {
    struct Expected: Decodable {
        struct B: Decodable {
            var quieter_than: Double
            var median_score: Int
            var p25_score: Int
            var p75_score: Int
            var n: Int
            var verdict: String
        }
        struct W: Decodable {
            var level_db: Double
            var quieter_than: Double
            var median_db: Double
            var verdict: String
        }
        var unit: ApartmentUnit
        var profile: Profile?
        var result: ScoreResult
        var baseline: B
        var windows: [String: W]
    }

    func testBundledBaselineLoads() throws {
        let b = try XCTUnwrap(Baseline.manhattan)
        XCTAssertGreaterThan(b.samples.count, 250)
        XCTAssertEqual(b.samples.reduce(0) { $0 + $1.weight }, 300)
        for s in b.samples { XCTAssertEqual(Set(s.levels.keys), Set(Baseline.ingredientOrder)) }
    }

    func testRankMatchesPython() throws {
        let b = try XCTUnwrap(Baseline.manhattan)
        for slug in ["bedford", "second-ave", "claremont", "broadway"] {
            let url = try XCTUnwrap(Bundle.module.url(forResource: "\(slug).expected", withExtension: "json", subdirectory: "Fixtures"))
            let e = try JSONDecoder().decode(Expected.self, from: Data(contentsOf: url))
            let r = b.rank(level: e.result.internalLevel, unit: e.unit, profile: e.profile)
            XCTAssertEqual(r.quieterThan, e.baseline.quieter_than, accuracy: 0.5, slug)
            XCTAssertEqual(r.medianScore, e.baseline.median_score, slug)
            XCTAssertEqual(r.p25Score, e.baseline.p25_score, slug)
            XCTAssertEqual(r.p75Score, e.baseline.p75_score, slug)
            XCTAssertEqual(r.n, e.baseline.n, slug)
            XCTAssertEqual(r.sampleScores.count, e.baseline.n, slug)
            XCTAssertEqual(r.verdict.label, e.baseline.verdict, slug)
            for w in Window.allCases {
                let x = try XCTUnwrap(e.windows[w.rawValue])
                let got = b.windowRank(e.result, window: w, unit: e.unit)
                XCTAssertEqual(got.levelDb, x.level_db, accuracy: 0.06, "\(slug) \(w)")
                XCTAssertEqual(got.quieterThan, x.quieter_than, accuracy: 0.5, "\(slug) \(w)")
                XCTAssertEqual(got.medianDb, x.median_db, accuracy: 0.06, "\(slug) \(w)")
                XCTAssertEqual(got.verdict.label, x.verdict, "\(slug) \(w)")
            }
        }
    }

    func testFloorIsCappedAtTheBuildingsHeight() throws {
        let b = try XCTUnwrap(Baseline.manhattan)
        let s = try XCTUnwrap(b.samples.first { ($0.floors ?? 0) >= 3 })
        let top = Baseline.level(for: s, unit: ApartmentUnit(floor: s.floors, position: .front), profile: nil)
        let above = Baseline.level(for: s, unit: ApartmentUnit(floor: 80, position: .front), profile: nil)
        XCTAssertEqual(top, above, accuracy: 1e-9)
    }

    func testVerdictBandsAndAnchors() {
        XCTAssertEqual(Verdict(quieterThan: 0).label, "Very loud")
        XCTAssertEqual(Verdict(quieterThan: 19.9).label, "Very loud")
        XCTAssertEqual(Verdict(quieterThan: 53).label, "Typical")
        XCTAssertEqual(Verdict(quieterThan: 100).label, "Very quiet")
        XCTAssertEqual(Loudness.anchor(60.4), "a normal conversation")
        XCTAssertEqual(Loudness.anchor(46.9), "a quiet office")
    }
}
