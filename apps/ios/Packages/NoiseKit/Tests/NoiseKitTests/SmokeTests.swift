import XCTest
@testable import NoiseKit

final class SmokeTests: XCTestCase {
    func testFixturesPresent() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "bedford.inputs", withExtension: "json", subdirectory: "Fixtures"))
        XCTAssertGreaterThan(try Data(contentsOf: url).count, 1000)
    }
}
