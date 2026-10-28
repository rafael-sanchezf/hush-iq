import XCTest
@testable import NoiseKit

final class CacheAndSourcesTests: XCTestCase {
    var dir: URL!
    var cache: NoiseCache!

    override func setUp() {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("noisekit-tests-\(UUID().uuidString)", isDirectory: true)
        cache = NoiseCache(directory: dir)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: dir)
    }

    func testCacheRoundTripAndTTL() throws {
        let key = NoiseCache.key(["pluto", "bbl=1018857501"])
        XCTAssertEqual(key.count, 64)
        XCTAssertEqual(key, NoiseCache.key(["pluto", "bbl=1018857501"]))
        XCTAssertNotEqual(key, NoiseCache.key(["pluto", "bbl=1018857502"]))

        XCTAssertNil(cache.get("pluto", key: key, as: [PlutoRow].self))
        let rows = [PlutoRow(address: "2900 BROADWAY", yearbuilt: "2000", numfloors: "14.0")]
        let t0 = Date(timeIntervalSince1970: 1_800_000_000)
        XCTAssertTrue(cache.put("pluto", key: key, request: "test", value: rows, fetchedAt: t0))

        let hit = try XCTUnwrap(cache.get("pluto", key: key, as: [PlutoRow].self))
        XCTAssertEqual(hit.value, rows)
        XCTAssertEqual(hit.fetchedAt.timeIntervalSince1970, t0.timeIntervalSince1970, accuracy: 1)

        // Within the TTL it is served; past it, nil; with no TTL, served whatever its age.
        XCTAssertNotNil(cache.get("pluto", key: key, as: [PlutoRow].self, maxAge: 3600, now: t0.addingTimeInterval(60)))
        XCTAssertNil(cache.get("pluto", key: key, as: [PlutoRow].self, maxAge: 3600, now: t0.addingTimeInterval(7200)))
        XCTAssertNotNil(cache.get("pluto", key: key, as: [PlutoRow].self, maxAge: nil, now: t0.addingTimeInterval(1e9)))

        // A whole pull survives too, with the Python key shape inside.
        let inputs = FixtureDataSource.sampleInputs
        cache.put("pull", key: "k", value: inputs, fetchedAt: t0)
        let back = try XCTUnwrap(cache.get("pull", key: "k", as: Inputs.self))
        XCTAssertEqual(back.value, inputs)
        XCTAssertGreaterThan(cache.sizeOnDisk, 10_000)

        cache.remove("pull", key: "k")
        XCTAssertNil(cache.get("pull", key: "k", as: Inputs.self))
        cache.clear()
        XCTAssertNil(cache.get("pluto", key: key, as: [PlutoRow].self))
    }

    func testRequestURLsMatchPython() throws {
        let url = try LiveDataSource.url(LiveDataSource.Dataset.complaints311, [
            ("$select", "unique_key,complaint_type"),
            ("$where", "within_circle(location,40.806158,-73.96469,150) AND complaint_type like 'Noise%' AND created_date > '2024-10-31'"),
            ("$limit", "20000"),
        ])
        let s = url.absoluteString
        XCTAssertTrue(s.hasPrefix("https://data.cityofnewyork.us/resource/erm2-nwe9.json?"))
        XCTAssertTrue(s.contains("$select=unique_key,complaint_type"))
        XCTAssertTrue(s.contains("within_circle(location,40.806158,-73.96469,150)"))
        XCTAssertTrue(s.contains("'Noise%25'"))     // the percent is the one thing that must be escaped
        XCTAssertTrue(s.contains("$limit=20000"))
        XCTAssertEqual(LiveDataSource.num(150), "150")
        XCTAssertEqual(LiveDataSource.num(62.5), "62.5")
        XCTAssertEqual(LiveDataSource.daysAgoISO(720, from: Date(timeIntervalSince1970: 1_792_000_000)), "2024-10-24")
        XCTAssertEqual(LiveDataSource.sources.count, 8)
        XCTAssertEqual(LiveDataSource.sources.last?.url, "https://data.cityofnewyork.us/resource/67g2-p84d.json")
    }

    func testErrorMapping() {
        XCTAssertEqual(LiveDataSource.mapError(URLError(.notConnectedToInternet)).errorDescription, NoiseError.offline.errorDescription)
        XCTAssertEqual(LiveDataSource.mapError(URLError(.cannotFindHost)).errorDescription, NoiseError.offline.errorDescription)
        XCTAssertEqual(LiveDataSource.mapError(URLError(.timedOut)).errorDescription, NoiseError.offline.errorDescription)
        if case .upstream = LiveDataSource.mapError(URLError(.badURL)) {} else { XCTFail("badURL should be upstream") }
        if case .upstream = LiveDataSource.mapError(NoiseError.upstream("HTTP 500")) {} else { XCTFail("passthrough") }
        XCTAssertTrue(LiveDataSource.isTransient(URLError(.timedOut)))
        XCTAssertTrue(LiveDataSource.isTransient(NoiseError.upstream("HTTP 503 ")))
        XCTAssertFalse(LiveDataSource.isTransient(NoiseError.upstream("HTTP 400 bad SoQL")))
        XCTAssertFalse(LiveDataSource.isTransient(URLError(.notConnectedToInternet)))
    }

    /// With a session that cannot reach anything, the live source falls back to the stale cache only when allowed.
    func testOfflineFallsBackToCacheOnlyWhenAllowed() async throws {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [OfflineProtocol.self]
        let session = URLSession(configuration: cfg)
        let ds = LiveDataSource(cache: cache, session: session)
        let address = FixtureDataSource.sampleAddress

        // Nothing cached: offline, whatever allowCache says.
        do { _ = try await ds.pullAll(address: address, allowCache: true); XCTFail("expected offline") }
        catch { XCTAssertEqual((error as? NoiseError)?.errorDescription, NoiseError.offline.errorDescription) }
        XCTAssertNil(ds.cached(address: address))

        // A whole pull in the cache: served stale when allowed, refused when not.
        let t0 = Date(timeIntervalSince1970: 1_790_000_000)
        cache.put("pull", key: LiveDataSource.pullKey(address), value: FixtureDataSource.sampleInputs, fetchedAt: t0)
        let stale = try await ds.pullAll(address: address, allowCache: true)
        XCTAssertTrue(stale.fromCache)
        XCTAssertEqual(stale.fetchedAt.timeIntervalSince1970, t0.timeIntervalSince1970, accuracy: 1)
        XCTAssertEqual(stale.inputs.complaints.count, FixtureDataSource.sampleInputs.complaints.count)
        do { _ = try await ds.pullAll(address: address, allowCache: false); XCTFail("expected offline") }
        catch { XCTAssertEqual((error as? NoiseError)?.errorDescription, NoiseError.offline.errorDescription) }
        XCTAssertNotNil(ds.cached(address: address))

        // Recent complaints: no cache -> offline; suggestions -> offline.
        do { _ = try await ds.recentComplaints(lat: 40.8, lng: -73.96, radiusM: 500, days: 30, allowCache: true); XCTFail("expected offline") }
        catch { XCTAssertEqual((error as? NoiseError)?.errorDescription, NoiseError.offline.errorDescription) }
        do { _ = try await ds.suggest("2900 Broadway"); XCTFail("expected offline") }
        catch { XCTAssertEqual((error as? NoiseError)?.errorDescription, NoiseError.offline.errorDescription) }
        let short = try await ds.suggest("29")
        XCTAssertTrue(short.isEmpty)
    }

    /// A canned Socrata/GeoSearch server: every request decodes and the pull assembles with the eighth source.
    func testCannedResponsesAssembleAPull() async throws {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.protocolClasses = [CannedProtocol.self]
        let ds = LiveDataSource(cache: cache, session: URLSession(configuration: cfg), now: { Date(timeIntervalSince1970: 1_792_000_000) })

        let suggestions = try await ds.suggest("2900 Broadway")
        XCTAssertEqual(suggestions.count, 1)
        XCTAssertEqual(suggestions[0].bbl, "1018857501")
        XCTAssertEqual(suggestions[0].borough, "Manhattan")

        let pulled = try await ds.pullAll(address: suggestions[0], allowCache: false)
        XCTAssertFalse(pulled.fromCache)
        XCTAssertEqual(pulled.inputs.asOf, "2026-10-14")
        XCTAssertEqual(pulled.inputs.since, "2024-10-24")
        XCTAssertEqual(pulled.inputs.pluto?.yearbuilt, "2000")
        XCTAssertEqual(pulled.inputs.complaints.count, 1)
        XCTAssertEqual(pulled.inputs.roads.count, 1)
        XCTAssertEqual(pulled.inputs.facilities.count, 1)
        XCTAssertEqual(pulled.inputs.facilities[0].kind, .hospital)
        XCTAssertEqual(pulled.inputs.sources.count, 8)
        XCTAssertNotNil(ds.cached(address: suggestions[0]))
        XCTAssertEqual(CannedProtocol.seen.value.filter { $0.contains("67g2-p84d") }.count, 1)
        XCTAssertTrue(CannedProtocol.seen.value.contains { $0.contains("rbx6-tga4") && $0.contains("block='1885'") && $0.contains("borough='MANHATTAN'") })

        // A second pull inside the TTL is served from the cache without touching the network.
        let before = CannedProtocol.seen.value.count
        _ = try await ds.pullAll(address: suggestions[0], allowCache: false)
        XCTAssertEqual(CannedProtocol.seen.value.count, before)

        let recent = try await ds.recentComplaints(lat: 40.806158, lng: -73.96469, radiusM: 500, days: 30, allowCache: false)
        XCTAssertEqual(recent.complaints.count, 1)
        XCTAssertEqual(recent.complaints[0].status, "Closed")
        XCTAssertTrue(CannedProtocol.seen.value.contains { $0.contains("starts_with(complaint_type,'Noise')") && $0.contains("$order=created_date DESC") })

        let s = Scorer.score(pulled.inputs, unit: Unit(floor: 4, position: .front), profile: nil)
        XCTAssertEqual(s.ingredients.count, 5)
    }
}

// MARK: - Stub URL protocols

final class OfflineProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)) }
    override func stopLoading() {}
}

final class Locked<T>: @unchecked Sendable {
    private var v: T
    private let lock = NSLock()
    init(_ v: T) { self.v = v }
    var value: T { lock.lock(); defer { lock.unlock() }; return v }
    func mutate(_ f: (inout T) -> Void) { lock.lock(); f(&v); lock.unlock() }
}

final class CannedProtocol: URLProtocol {
    static let seen = Locked<[String]>([])

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        let url = request.url!
        let s = url.absoluteString.removingPercentEncoding ?? url.absoluteString
        Self.seen.mutate { $0.append(s) }
        let body: String
        if s.contains("geosearch.planninglabs.nyc") {
            body = #"{"features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-73.96469,40.806158]},"properties":{"label":"2900 B'WAY, New York, NY, USA","borough":"Manhattan","addendum":{"pad":{"bbl":"1018857501","bin":"1057018"}}}}]}"#
        } else if s.contains("64uk-42ks") {
            body = #"[{"address":"2900 BROADWAY","borough":"MN","yearbuilt":"2000","numfloors":"14.0000000","bldgclass":"RC","unitsres":"0","unitstotal":"374","landuse":"5"}]"#
        } else if s.contains("erm2-nwe9") && s.contains("$order") {
            body = #"[{"unique_key":"70825703","created_date":"2026-10-13T00:35:53.000","closed_date":"2026-10-13T01:21:24.000","complaint_type":"Noise - Commercial","descriptor":"Banging/Pounding","incident_address":"990 AMSTERDAM AVENUE","status":"Closed","resolution_description":"Police responded.","latitude":"40.80","longitude":"-73.96","location_type":"Store/Commercial","bbl":"1018640001"}]"#
        } else if s.contains("erm2-nwe9") {
            body = #"[{"unique_key":"67051330","complaint_type":"Noise","descriptor":"Noise: Construction Equipment (NC1)","created_date":"2025-12-04T13:08:00.000","latitude":"40.8063667","longitude":"-73.9659729","bbl":"1018950052","incident_address":"605 WEST 113 STREET"}]"#
        } else if s.contains("inkn-q76z") {
            body = #"[{"full_street_name":"BROADWAY","rw_type":"1","trafdir":"TW","number_travel_lanes":"3","posted_speed":"25","snow_priority":"C","the_geom":{"type":"MultiLineString","coordinates":[[[-73.96500,40.80580],[-73.96440,40.80660]]]}}]"#
        } else if s.contains("rbx6-tga4") {
            body = #"[]"#
        } else if s.contains("9s3h-dpkz") {
            body = #"[{"legalname":"HEX NYC LLC","description":"Food & Beverage Business","actualaddressofpremises":"2911 BROADWAY","georeference":{"type":"Point","coordinates":[-73.96505,40.80655]}}]"#
        } else if s.contains("39hk-dx4f") {
            body = #"[{"stop_name":"116 St-Columbia University","daytime_routes":"1","structure":"Subway","gtfs_latitude":"40.807722","gtfs_longitude":"-73.96411"}]"#
        } else if s.contains("67g2-p84d") {
            body = #"[{"facname":"MOUNT SINAI MORNINGSIDE","factype":"HOSPITAL","address":"1111 AMSTERDAM AVENUE","latitude":"40.8054","longitude":"-73.9617"},{"facname":"FAR AWAY HOSPITAL","factype":"HOSPITAL","latitude":"40.70","longitude":"-73.90"}]"#
        } else {
            body = #"{"message":"unknown canned endpoint"}"#
            let resp = HTTPURLResponse(url: url, statusCode: 400, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(body.utf8))
            client?.urlProtocolDidFinishLoading(self)
            return
        }
        let resp = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: resp, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}
