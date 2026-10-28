import XCTest
@testable import NoiseKit

final class DecodingTests: XCTestCase {

    func testGeoJSONDecodesPointAndLines() throws {
        let point = try JSONDecoder().decode(GeoJSON.self, from: Data(#"{"type":"Point","coordinates":[-73.96541,40.80577]}"#.utf8))
        XCTAssertEqual(point, .point(lng: -73.96541, lat: 40.80577))
        XCTAssertTrue(point.lines.isEmpty)

        let line = try JSONDecoder().decode(GeoJSON.self, from: Data(#"{"type":"LineString","coordinates":[[-73.96,40.80],[-73.95,40.81]]}"#.utf8))
        XCTAssertEqual(line.lines.count, 1)
        XCTAssertEqual(line.lines[0].count, 2)

        let multi = try JSONDecoder().decode(GeoJSON.self, from: Data(#"{"type":"MultiLineString","coordinates":[[[-73.964284092944,40.807301290734],[-73.964391370657,40.807345889505]],[[-73.96,40.80],[-73.95,40.81]]]}"#.utf8))
        XCTAssertEqual(multi.lines.count, 2)

        let polygon = try JSONDecoder().decode(GeoJSON.self, from: Data(#"{"type":"Polygon","coordinates":[[[0,0],[1,1],[0,1],[0,0]]]}"#.utf8))
        XCTAssertEqual(polygon, .other(type: "Polygon"))

        // Round trip keeps the shape.
        let back = try JSONDecoder().decode(GeoJSON.self, from: JSONEncoder().encode(multi))
        XCTAssertEqual(back, multi)
    }

    func testGeoDistances() {
        // 2900 Broadway to Columbia's Low Library, about 300 m.
        let d = Geo.haversineM(40.806158, -73.96469, 40.808075, -73.961968)
        XCTAssertEqual(d, 310, accuracy: 15)
        // A point 50 m east of a north-south segment.
        let lat = 40.8062, lng = -73.9647
        let dLng = 50.0 / (111_195.0 * cos(lat * .pi / 180))
        let seg = Geo.pointToSegmentM(lat, lng + dLng, [lng, lat - 0.001], [lng, lat + 0.001])
        XCTAssertEqual(seg, 50, accuracy: 0.1)
        // Beyond the end of the segment the distance is to the endpoint.
        let end = Geo.pointToSegmentM(lat + 0.002, lng, [lng, lat - 0.001], [lng, lat + 0.001])
        XCTAssertEqual(end, Geo.haversineM(lat + 0.002, lng, lat + 0.001, lng), accuracy: 0.05)
        // Multiline picks the nearest segment; nil for a point or nothing.
        let geom = GeoJSON.multiLineString([[[lng, lat - 0.001], [lng, lat + 0.001]], [[lng + 0.01, lat], [lng + 0.02, lat]]])
        XCTAssertEqual(Geo.pointToMultilineM(lat, lng + dLng, geom)!, 50, accuracy: 0.1)
        XCTAssertNil(Geo.pointToMultilineM(lat, lng, nil))
        XCTAssertNil(Geo.pointToMultilineM(lat, lng, .point(lng: lng, lat: lat)))
    }

    func testLenientStringDecoding() throws {
        // Socrata sends most numbers as strings, but not all; nulls and missing keys are nil.
        let json = #"""
        [{"unique_key": 70825703, "complaint_type": "Noise - Commercial", "descriptor": null,
          "created_date": "2026-10-21T00:35:53.000", "latitude": 40.8, "longitude": "-73.96", "bbl": 1018857501,
          "status": true},
         {"unique_key": "1", "latitude": "40.8"}]
        """#
        let rows = try JSONDecoder().decode([ComplaintRow].self, from: Data(json.utf8))
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows[0].uniqueKey, "70825703")
        XCTAssertNil(rows[0].descriptor)
        XCTAssertEqual(rows[0].latitude.double!, 40.8, accuracy: 1e-9)
        XCTAssertEqual(rows[0].longitude.double!, -73.96, accuracy: 1e-9)
        XCTAssertEqual(rows[0].bbl, "1018857501")
        XCTAssertEqual(rows[0].status, "true")
        XCTAssertNil(rows[1].complaintType)
        XCTAssertNil(rows[1].longitude)

        let pluto = try JSONDecoder().decode(PlutoRow.self, from: Data(#"{"numfloors": 14.0, "unitsres": "0", "yearbuilt": 2000}"#.utf8))
        XCTAssertEqual(pluto.numfloors, "14")   // a JSON 14.0 decodes as Int first; the model parses it as a float either way
        XCTAssertEqual(pluto.unitsres.int, 0)
        XCTAssertEqual(pluto.yearbuilt.int, 2000)
        XCTAssertEqual(Optional("14.0000000").int, 14)   // Optional<String>.int goes through Double for PLUTO decimals

        let road = try JSONDecoder().decode(RoadRow.self, from: Data(#"{"full_street_name":"BROADWAY","rw_type":1,"the_geom":{"type":"Nope"}}"#.utf8))
        XCTAssertEqual(road.rwType, "1")
        XCTAssertEqual(road.theGeom, .other(type: "Nope"))
        let badGeom = try JSONDecoder().decode(RoadRow.self, from: Data(#"{"full_street_name":"X","the_geom":"garbage"}"#.utf8))
        XCTAssertNil(badGeom.theGeom)
    }

    func testInputsDecodeWithMissingArraysAndNumbers() throws {
        let json = #"""
        {"address": {"lat": 40.8, "lng": -73.96, "label": "x"}, "as_of": "2026-10-21", "lookback_months": "24",
         "pluto": null, "complaints": [], "liquor": null}
        """#
        let inputs = try JSONDecoder().decode(Inputs.self, from: Data(json.utf8))
        XCTAssertEqual(inputs.lookbackMonths, 24)
        XCTAssertNil(inputs.pluto)
        XCTAssertTrue(inputs.roads.isEmpty)
        XCTAssertTrue(inputs.facilities.isEmpty)
        // And it scores without crashing.
        let r = Scorer.score(inputs, unit: Unit(), profile: nil)
        XCTAssertEqual(r.ingredients.count, 5)
        XCTAssertGreaterThan(r.score, 50)
    }

    func testFacilityKindsAndFilter() throws {
        let json = #"""
        [{"facname":"MOUNT SINAI MORNINGSIDE","factype":"HOSPITAL","address":"1111 AMSTERDAM AVENUE","latitude":"40.8054","longitude":"-73.9617"},
         {"facname":"ENGINE 47","factype":"FIREHOUSE","address":"502 WEST 113 STREET","latitude":40.8055,"longitude":-73.9636},
         {"facname":"26 PRECINCT","factype":"POLICE STATION","address":"520 WEST 126 STREET","latitude":"40.8140","longitude":"-73.9560"},
         {"facname":"EMS STATION 13","factype":"AMBULANCE STATION","latitude":"40.806","longitude":"-73.964"},
         {"facname":"NO COORDS","factype":"HOSPITAL","address":"x"},
         {"facname":"A SCHOOL","factype":"PUBLIC SCHOOL","latitude":"40.806","longitude":"-73.964"}]
        """#
        let rows = try JSONDecoder().decode([LiveDataSource.FacDBRow].self, from: Data(json.utf8))
        XCTAssertEqual(rows.count, 6)
        let near = LiveDataSource.nearbyFacilities(rows, lat: 40.806158, lng: -73.96469, radiusM: Config.radiusSirensM)
        XCTAssertEqual(near.map(\.name), ["MOUNT SINAI MORNINGSIDE", "ENGINE 47", "EMS STATION 13"])   // the precinct is ~1.1 km away
        XCTAssertEqual(near.map(\.kind), [.hospital, .fire, .fire])
        XCTAssertEqual(LiveDataSource.kind(of: "ACUTE CARE HOSPITAL"), .hospital)
        XCTAssertEqual(LiveDataSource.kind(of: "Police Station"), .police)
        XCTAssertNil(LiveDataSource.kind(of: "LIBRARY"))
    }

    func testFixtureDataSourceReplaysTheSample() async throws {
        let ds = FixtureDataSource()
        let suggestions = try await ds.suggest("anything")
        XCTAssertEqual(suggestions.count, 1)
        XCTAssertEqual(suggestions[0].bbl, "1018857501")
        let pulled = try await ds.pullAll(address: suggestions[0], allowCache: false)
        XCTAssertTrue(pulled.fromCache)
        XCTAssertEqual(pulled.inputs.asOf, "2026-10-21")
        XCTAssertGreaterThan(pulled.inputs.complaints.count, 100)
        let recent = try await ds.recentComplaints(lat: 0, lng: 0, radiusM: 500, days: 30, allowCache: false)
        XCTAssertEqual(recent.complaints.count, 132)
        XCTAssertNotNil(recent.complaints[0].status)
        XCTAssertNotNil(ds.cached(address: suggestions[0]))
        XCTAssertEqual(FixtureDataSource.sampleResult.ingredients.count, 5)
    }
}
