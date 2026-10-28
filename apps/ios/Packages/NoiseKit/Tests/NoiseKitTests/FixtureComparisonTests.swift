import XCTest
@testable import NoiseKit

/// Replays the four Python fixtures through the Swift model and diffs the result against the Python output.
/// The fixtures were regenerated with the sirens ingredient (M11), so they run with the default options.
final class FixtureComparisonTests: XCTestCase {
    static let slugs = ["bedford", "second-ave", "claremont", "broadway"]

    struct Expected: Decodable {
        var unit: NoiseKit.Unit
        var profile: Profile?
        var result: ScoreResult
    }

    static func load(_ slug: String) throws -> (Inputs, Expected) {
        let inputsURL = try XCTUnwrap(Bundle.module.url(forResource: "\(slug).inputs", withExtension: "json", subdirectory: "Fixtures"))
        let expectedURL = try XCTUnwrap(Bundle.module.url(forResource: "\(slug).expected", withExtension: "json", subdirectory: "Fixtures"))
        let inputs = try JSONDecoder().decode(Inputs.self, from: Data(contentsOf: inputsURL))
        let expected = try JSONDecoder().decode(Expected.self, from: Data(contentsOf: expectedURL))
        return (inputs, expected)
    }

    func testFixturesDecode() throws {
        for slug in Self.slugs {
            let (inputs, expected) = try Self.load(slug)
            XCTAssertFalse(inputs.complaints.isEmpty, slug)
            XCTAssertFalse(inputs.roads.isEmpty, slug)
            XCTAssertEqual(expected.result.ingredients.count, 5, slug)
            XCTAssertEqual(expected.result.byTime.count, 3, slug)
        }
    }

    func testFixturesMatchPython() throws {
        var summary: [String] = []
        for slug in Self.slugs {
            let (inputs, expected) = try Self.load(slug)
            let got = Scorer.score(inputs, unit: expected.unit, profile: expected.profile, options: ScoreOptions(sirens: true))
            let want = expected.result

            XCTAssertEqual(got.score, want.score, "\(slug) score", within: 1)
            XCTAssertEqual(got.streetOnlyScore, want.streetOnlyScore, "\(slug) streetOnlyScore", within: 1)
            for w in Window.allCases {
                XCTAssertEqual(got.byTime[w]!, want.byTime[w]!, "\(slug) byTime[\(w)]", within: 1)
                XCTAssertEqual(got.windowWeights[w]!, want.windowWeights[w]!, accuracy: 1e-9, "\(slug) windowWeights[\(w)]")
            }
            XCTAssertEqual(got.internalLevel, want.internalLevel, accuracy: 0.15, "\(slug) internalLevel")
            XCTAssertEqual(got.ingredients.map(\.name), want.ingredients.map(\.name), slug)

            for (g, e) in zip(got.ingredients, want.ingredients) {
                let tag = "\(slug)/\(g.name)"
                XCTAssertEqual(g.label, e.label, tag)
                XCTAssertEqual(g.temporary, e.temporary, tag)
                XCTAssertEqual(g.weightedUp, e.weightedUp, tag)
                XCTAssertEqual(g.rawLevel, e.rawLevel, accuracy: 0.15, "\(tag) rawLevel")
                XCTAssertEqual(g.positionDb, e.positionDb, accuracy: 0.15, "\(tag) positionDb")
                for w in Window.allCases {
                    XCTAssertEqual(g.levels[w]!, e.levels[w]!, accuracy: 0.15, "\(tag) levels[\(w)]")
                    XCTAssertEqual(g.scores[w]!, e.scores[w]!, "\(tag) scores[\(w)]", within: 1)
                }
                XCTAssertEqual(g.evidence.count, e.evidence.count, "\(tag) evidence count\n  got: \(g.evidence)\n want: \(e.evidence)")
                XCTAssertEqual(g.evidence.first, e.evidence.first, "\(tag) first evidence line")
                // Every line is expected to match; the spec only requires the first, so the rest is a soft check.
                for (i, (gl, el)) in zip(g.evidence, e.evidence).enumerated() where gl != el {
                    print("EVIDENCE DIFF \(tag)[\(i)]\n  swift:  \(gl)\n  python: \(el)")
                }
            }
            summary.append("\(slug): score \(got.score) vs \(want.score) (d \(got.score - want.score)), street-only \(got.streetOnlyScore) vs \(want.streetOnlyScore), "
                           + "by_time " + Window.allCases.map { "\($0.rawValue) \(got.byTime[$0]!)/\(want.byTime[$0]!)" }.joined(separator: " "))
        }
        print("FIXTURE SUMMARY\n" + summary.joined(separator: "\n"))
    }

    /// The whole result survives a JSON round trip (the app persists `ScoreResult`) with the Python key shape.
    func testScoreResultRoundTrip() throws {
        let (inputs, expected) = try Self.load("broadway")
        let got = Scorer.score(inputs, unit: expected.unit, profile: expected.profile)
        let data = try JSONEncoder().encode(got)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let byTime = try XCTUnwrap(json["by_time"] as? [String: Any])
        XCTAssertEqual(Set(byTime.keys), ["night", "early", "day"])
        let back = try JSONDecoder().decode(ScoreResult.self, from: data)
        XCTAssertEqual(back, got)
        XCTAssertEqual(got.ingredients.map(\.name), ["street", "nightlife", "building", "sirens", "construction"])
    }
}

func XCTAssertEqual(_ a: Int, _ b: Int, _ message: String, within tol: Int, file: StaticString = #filePath, line: UInt = #line) {
    XCTAssertLessThanOrEqual(abs(a - b), tol, "\(message): got \(a), want \(b)", file: file, line: line)
}
