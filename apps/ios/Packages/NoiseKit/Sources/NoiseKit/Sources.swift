import Foundation

/// Every upstream pull, a port of noise_score/sources.py. All public datasets, no key needed. [T2][T3]
///
/// The endpoints and the `$select` / `$where` strings are the Python ones so the two models see the same
/// rows. Each request is cached by `NoiseCache` (7 days for the score pulls, 15 minutes for the recent
/// complaints, 30 days for the citywide facilities list); when the network fails and `allowCache` is true
/// the stale copy is returned with `fromCache = true`.
public struct LiveDataSource: NoiseDataSource {
    public static let nyc = "https://data.cityofnewyork.us/resource"
    public static let nys = "https://data.ny.gov/resource"
    public static let geosearch = "https://geosearch.planninglabs.nyc/v2/search"
    public static let geosearchAutocomplete = "https://geosearch.planninglabs.nyc/v2/autocomplete"

    public enum Dataset {
        public static let complaints311 = "\(nyc)/erm2-nwe9.json"   // 311 Service Requests 2010-present
        public static let pluto = "\(nyc)/64uk-42ks.json"           // Primary Land Use Tax Lot Output
        public static let roads = "\(nyc)/inkn-q76z.json"           // NYC Street Centerline (CSCL)
        public static let permits = "\(nyc)/rbx6-tga4.json"         // DOB NOW: Build, Approved Permits
        public static let liquor = "\(nys)/9s3h-dpkz.json"          // NYS Liquor Authority, Current Active Licenses
        public static let stations = "\(nys)/39hk-dx4f.json"        // MTA Subway Stations (structure: Elevated, Subway, ...)
        public static let facilities = "\(nyc)/67g2-p84d.json"      // NYC Facilities Database (hospitals, firehouses, police) [M11]
    }

    public static let sources: [SourceRef] = [
        SourceRef(name: "NYC GeoSearch (address, BBL, BIN)", url: geosearch),
        SourceRef(name: "NYC 311 Service Requests", url: Dataset.complaints311),
        SourceRef(name: "NYC PLUTO (year built, floors, units, class)", url: Dataset.pluto),
        SourceRef(name: "NYC Street Centerline (road class, lanes, speed)", url: Dataset.roads),
        SourceRef(name: "DOB NOW approved permits (same tax block)", url: Dataset.permits),
        SourceRef(name: "NYS Liquor Authority active licenses", url: Dataset.liquor),
        SourceRef(name: "MTA subway stations (elevated structures)", url: Dataset.stations),
        SourceRef(name: "NYC Facilities Database (hospitals, firehouses, police)", url: Dataset.facilities),
    ]

    public let cache: NoiseCache
    let session: URLSession
    let now: @Sendable () -> Date

    public init(cache: NoiseCache = .default, session: URLSession? = nil, now: @escaping @Sendable () -> Date = { Date() }) {
        self.cache = cache
        self.now = now
        if let session {
            self.session = session
        } else {
            let c = URLSessionConfiguration.default
            c.timeoutIntervalForRequest = Config.httpTimeoutS
            c.timeoutIntervalForResource = Config.httpTimeoutS * Double(Config.httpRetries + 1)
            c.waitsForConnectivity = false
            var headers = ["User-Agent": Config.userAgent, "Accept": "application/json"]
            if let token = Config.socrataAppToken { headers["X-App-Token"] = token }
            c.httpAdditionalHeaders = headers
            self.session = URLSession(configuration: c)
        }
    }

    // MARK: - HTTP

    /// One decoded response plus where it came from.
    struct Fetched<T: Codable>: Sendable where T: Sendable {
        var value: T
        var fetchedAt: Date
        /// True only when the network failed and a stale cache entry stood in.
        var fromCache: Bool
    }

    static func url(_ base: String, _ params: [(String, String)]) throws -> URL {
        guard var comps = URLComponents(string: base) else { throw NoiseError.upstream("bad URL \(base)") }
        comps.queryItems = params.map { URLQueryItem(name: $0.0, value: $0.1) }
        guard let url = comps.url else { throw NoiseError.upstream("bad URL \(base)") }
        return url
    }

    /// `NoiseError.offline` for the URLError codes that mean no network; anything else is `upstream`.
    static func mapError(_ error: Error) -> NoiseError {
        if let e = error as? NoiseError { return e }
        if let e = error as? URLError {
            switch e.code {
            case .notConnectedToInternet, .networkConnectionLost, .cannotFindHost, .cannotConnectToHost, .timedOut,
                 .dnsLookupFailed, .internationalRoamingOff, .dataNotAllowed:
                return .offline
            default:
                return .upstream(e.localizedDescription)
            }
        }
        if error is DecodingError { return .decoding(String(describing: error)) }
        return .upstream(error.localizedDescription)
    }

    static func isTransient(_ error: Error) -> Bool {
        if let e = error as? URLError {
            return [.timedOut, .networkConnectionLost, .cannotConnectToHost, .badServerResponse].contains(e.code)
        }
        if case .upstream(let m)? = error as? NoiseError { return m.hasPrefix("HTTP 5") || m.hasPrefix("HTTP 429") }
        return false
    }

    /// GET with the timeout from Config and two retries on a transient failure. Throws a `NoiseError`.
    func getData(_ url: URL) async throws -> Data {
        var attempt = 0
        var lastError: Error = NoiseError.upstream("no attempt")
        while attempt <= Config.httpRetries {
            attempt += 1
            do {
                var req = URLRequest(url: url)
                req.timeoutInterval = Config.httpTimeoutS
                req.setValue(Config.userAgent, forHTTPHeaderField: "User-Agent")
                let (data, resp) = try await session.data(for: req)
                let status = (resp as? HTTPURLResponse)?.statusCode ?? 200
                guard (200..<300).contains(status) else {
                    let msg = (try? JSONDecoder().decode(SocrataError.self, from: data))?.message ?? String(data: data.prefix(200), encoding: .utf8) ?? ""
                    throw NoiseError.upstream("HTTP \(status) \(msg)".trimmingCharacters(in: .whitespaces))
                }
                return data
            } catch {
                lastError = error
                if !Self.isTransient(error) || attempt > Config.httpRetries { break }
                try? await Task.sleep(nanoseconds: UInt64(500_000_000 * attempt))
            }
        }
        throw Self.mapError(lastError)
    }

    struct SocrataError: Decodable { var message: String? }

    /// Cache, then network, then the stale cache if allowed. `ttl` in seconds.
    func get<T: Codable & Sendable>(_ name: String, _ base: String, _ params: [(String, String)], ttl: TimeInterval,
                                    allowCache: Bool, as type: T.Type = T.self) async throws -> Fetched<T> {
        let url = try Self.url(base, params)
        let key = NoiseCache.key([base] + params.sorted { $0.0 < $1.0 }.map { "\($0.0)=\($0.1)" })
        let today = now()
        if let hit = cache.get(name, key: key, as: T.self, maxAge: ttl, now: today) {
            return Fetched(value: hit.value, fetchedAt: hit.fetchedAt, fromCache: false)
        }
        do {
            let data = try await getData(url)
            let value: T
            do { value = try JSONDecoder().decode(T.self, from: data) }
            catch { throw NoiseError.decoding("\(name): \(error)") }
            cache.put(name, key: key, request: url.absoluteString, value: value, fetchedAt: today)
            return Fetched(value: value, fetchedAt: today, fromCache: false)
        } catch {
            if allowCache, let stale = cache.get(name, key: key, as: T.self, now: today) {
                return Fetched(value: stale.value, fetchedAt: stale.fetchedAt, fromCache: true)
            }
            throw Self.mapError(error)
        }
    }

    // MARK: - Geocode (GeoSearch v2)

    struct GeoDoc: Decodable { var features: [GeoFeature] }
    struct GeoFeature: Decodable {
        var geometry: GeoGeometry
        var properties: GeoProps
    }
    struct GeoGeometry: Decodable { var coordinates: [Double] }
    struct GeoProps: Decodable {
        var label: String?
        var borough: String?
        var bbl: String?
        var bin: String?
        enum CodingKeys: String, CodingKey { case label, borough, addendum, padBbl = "pad_bbl", padBin = "pad_bin" }
        enum AddendumKeys: String, CodingKey { case pad }
        enum PadKeys: String, CodingKey { case bbl, bin }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            label = c.loose(.label); borough = c.loose(.borough)
            var padBbl: String?, padBin: String?
            if let a = try? c.nestedContainer(keyedBy: AddendumKeys.self, forKey: .addendum),
               let p = try? a.nestedContainer(keyedBy: PadKeys.self, forKey: .pad) {
                padBbl = p.loose(.bbl); padBin = p.loose(.bin)
            }
            bbl = padBbl ?? c.loose(.padBbl)
            bin = padBin ?? c.loose(.padBin)
        }
    }

    static func addresses(from doc: GeoDoc, query: String) -> [GeoAddress] {
        doc.features.compactMap { f in
            guard f.geometry.coordinates.count >= 2 else { return nil }
            let p = f.properties
            return GeoAddress(query: query, label: p.label, lat: f.geometry.coordinates[1], lng: f.geometry.coordinates[0],
                              bbl: p.bbl, bin: p.bin, borough: p.borough)
        }
    }

    /// GeoSearch `/v2/autocomplete?text=&size=5` if it answers, else `/v2/search?text=&size=5`. Never cached.
    public func suggest(_ text: String) async throws -> [GeoAddress] {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 3 else { return [] }
        let params = [("text", q), ("size", "5")]
        do {
            let data = try await getData(try Self.url(Self.geosearchAutocomplete, params))
            let doc = try JSONDecoder().decode(GeoDoc.self, from: data)
            return Self.addresses(from: doc, query: q)
        } catch {
            if case NoiseError.offline = Self.mapError(error) { throw NoiseError.offline }
            let data = try await getData(try Self.url(Self.geosearch, params))
            do {
                let doc = try JSONDecoder().decode(GeoDoc.self, from: data)
                return Self.addresses(from: doc, query: q)
            } catch {
                throw NoiseError.decoding("geocode: \(error)")
            }
        }
    }

    /// The single best match, Python's `geocode()`. Throws `noMatch` when GeoSearch has nothing.
    public func geocode(_ text: String) async throws -> GeoAddress {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let data = try await getData(try Self.url(Self.geosearch, [("text", q), ("size", "1")]))
        let doc: GeoDoc
        do { doc = try JSONDecoder().decode(GeoDoc.self, from: data) } catch { throw NoiseError.decoding("geocode: \(error)") }
        guard let a = Self.addresses(from: doc, query: q).first else { throw NoiseError.noMatch(q) }
        return a
    }

    // MARK: - The pulls

    static let pullTTL = TimeInterval(Config.cacheTtlDays * 86_400)
    static let recentTTL = TimeInterval(Config.cacheTtlRecentMinutes * 60)
    static let facilitiesTTL = TimeInterval(Config.cacheTtlFacilitiesDays * 86_400)

    func pluto(bbl: String?, allowCache: Bool) async throws -> Fetched<[PlutoRow]> {
        guard let bbl, !bbl.isEmpty else { return Fetched(value: [], fetchedAt: now(), fromCache: false) }
        return try await get("pluto", Dataset.pluto, [
            ("bbl", bbl),
            ("$select", "address,borough,yearbuilt,yearalter1,yearalter2,numfloors,bldgclass,unitsres,unitstotal,landuse,lotfront,bldgdepth,zonedist1"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    /// Approved permits on the same tax block since `sinceISO`. DOB NOW stores the block without leading zeros.
    func dobPermits(borough: String?, block: String?, sinceISO: String, allowCache: Bool) async throws -> Fetched<[PermitRow]> {
        guard let borough, !borough.isEmpty, let block, !block.isEmpty else { return Fetched(value: [], fetchedAt: now(), fromCache: false) }
        var b = String(block.drop(while: { $0 == "0" }))
        if b.isEmpty { b = "0" }
        return try await get("permits", Dataset.permits, [
            ("$select", "work_type,work_permit,job_description,approved_date,issued_date,expired_date,estimated_job_costs,house_no,street_name,bin"),
            ("$where", "borough='\(borough.uppercased())' AND block='\(b)' AND issued_date > '\(sinceISO)'"),
            ("$limit", "500"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    func complaints311(lat: Double, lng: Double, radiusM: Double, sinceISO: String, allowCache: Bool) async throws -> Fetched<[ComplaintRow]> {
        try await get("311", Dataset.complaints311, [
            ("$select", "unique_key,complaint_type,descriptor,created_date,latitude,longitude,bbl,incident_address"),
            ("$where", "within_circle(location,\(lat),\(lng),\(Self.num(radiusM))) AND complaint_type like 'Noise%' AND created_date > '\(sinceISO)'"),
            ("$limit", "20000"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    func liquor(lat: Double, lng: Double, radiusM: Double, allowCache: Bool) async throws -> Fetched<[LiquorRow]> {
        try await get("liquor", Dataset.liquor, [
            ("$select", "legalname,description,type,class,actualaddressofpremises,georeference"),
            ("$where", "within_circle(georeference,\(lat),\(lng),\(Self.num(radiusM)))"),
            ("$limit", "500"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    /// Socrata's within_circle on a line matches its vertices, not the line, so ask wide and let the model
    /// measure the true distance to each segment (NYC block faces run up to ~270 m).
    func roads(lat: Double, lng: Double, radiusM: Double, allowCache: Bool) async throws -> Fetched<[RoadRow]> {
        let r = max(radiusM, Config.roadsQueryRadiusM)
        return try await get("roads", Dataset.roads, [
            ("$select", "full_street_name,rw_type,streetwidth,trafdir,number_total_lanes,number_travel_lanes,posted_speed,snow_priority,status,the_geom"),
            ("$where", "within_circle(the_geom,\(lat),\(lng),\(Self.num(r)))"),
            ("$limit", "500"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    func railStations(lat: Double, lng: Double, radiusM: Double, allowCache: Bool) async throws -> Fetched<[StationRow]> {
        try await get("stations", Dataset.stations, [
            ("$select", "stop_name,daytime_routes,structure,gtfs_latitude,gtfs_longitude"),
            ("$where", "within_circle(georeference,\(lat),\(lng),\(Self.num(radiusM)))"),
            ("$limit", "50"),
        ], ttl: Self.pullTTL, allowCache: allowCache)
    }

    /// One FacDB row as Socrata sends it. Mapped to `FacilityRow` after the pull.
    struct FacDBRow: Codable, Sendable {
        var facname: String?
        var factype: String?
        var address: String?
        var latitude: String?
        var longitude: String?
        enum CodingKeys: String, CodingKey { case facname, factype, address, latitude, longitude }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            facname = c.loose(.facname); factype = c.loose(.factype); address = c.loose(.address)
            latitude = c.loose(.latitude); longitude = c.loose(.longitude)
        }
    }

    public static let facilityTypes = ["HOSPITAL", "ACUTE CARE HOSPITAL", "FIREHOUSE", "AMBULANCE STATION", "POLICE STATION"]

    static func kind(of factype: String?) -> FacilityRow.Kind? {
        switch (factype ?? "").uppercased() {
        case "HOSPITAL", "ACUTE CARE HOSPITAL": return .hospital
        case "FIREHOUSE", "AMBULANCE STATION": return .fire
        case "POLICE STATION": return .police
        default: return nil
        }
    }

    /// The citywide list (about 400 rows; `within_circle` on this dataset's `the_geom` returns nothing),
    /// cached 30 days under one key shared by every address, then filtered to `radiusM` here. [M11]
    func facilities(lat: Double, lng: Double, radiusM: Double, allowCache: Bool) async throws -> Fetched<[FacilityRow]> {
        let all: Fetched<[FacDBRow]> = try await get("facilities", Dataset.facilities, [
            ("$select", "facname,factype,address,latitude,longitude"),
            ("$where", "factype in(" + Self.facilityTypes.map { "'\($0)'" }.joined(separator: ",") + ")"),
            ("$limit", "2000"),
        ], ttl: Self.facilitiesTTL, allowCache: allowCache)
        let near = Self.nearbyFacilities(all.value, lat: lat, lng: lng, radiusM: radiusM)
        return Fetched(value: near, fetchedAt: all.fetchedAt, fromCache: all.fromCache)
    }

    static func nearbyFacilities(_ rows: [FacDBRow], lat: Double, lng: Double, radiusM: Double) -> [FacilityRow] {
        rows.compactMap { r in
            guard let kind = kind(of: r.factype), let la = r.latitude.double, let ln = r.longitude.double else { return nil }
            guard Geo.haversineM(lat, lng, la, ln) <= radiusM else { return nil }
            return FacilityRow(name: r.facname ?? "", kind: kind, address: r.address, latitude: la, longitude: ln)
        }
    }

    /// A number the way Python interpolates it: `150` for 150.0, `62.5` for 62.5.
    static func num(_ x: Double) -> String {
        x == x.rounded() && abs(x) < 1e15 ? String(Int(x)) : String(x)
    }

    static func daysAgoISO(_ days: Int, from date: Date) -> String {
        let d = Calendar.current.date(byAdding: .day, value: -days, to: date) ?? date.addingTimeInterval(-Double(days) * 86_400)
        return Scorer.isoDate(d)
    }

    // MARK: - NoiseDataSource

    static func pullKey(_ address: GeoAddress) -> String {
        NoiseCache.key(["pull", address.id, address.bbl ?? ""])
    }

    /// Everything the score needs, the pulls running concurrently, then the whole pull written to the cache
    /// so `cached(address:)` can replay it. The address is already geocoded (from `suggest`).
    public func pullAll(address: GeoAddress, allowCache: Bool) async throws -> Pulled {
        let today = now()
        let asOf = Scorer.isoDate(today)
        let since = Self.daysAgoISO(30 * Config.lookbackMonths, from: today)
        let permitsSince = Self.daysAgoISO(30 * Config.constructionPermitLookbackMonths, from: today)
        let lat = address.lat, lng = address.lng
        let radius = max(Config.radiusBlockM, Config.radiusNightlifeM)
        let block: String? = (address.bbl?.count == 10) ? String(address.bbl!.dropFirst(1).prefix(5)) : nil
        do {
            async let pl = pluto(bbl: address.bbl, allowCache: allowCache)
            async let co = complaints311(lat: lat, lng: lng, radiusM: radius, sinceISO: since, allowCache: allowCache)
            async let li = liquor(lat: lat, lng: lng, radiusM: Config.radiusNightlifeM, allowCache: allowCache)
            async let ro = roads(lat: lat, lng: lng, radiusM: Config.radiusRoadsM, allowCache: allowCache)
            async let st = railStations(lat: lat, lng: lng, radiusM: Config.radiusRailM, allowCache: allowCache)
            async let pe = dobPermits(borough: address.borough, block: block, sinceISO: permitsSince, allowCache: allowCache)
            async let fa = facilities(lat: lat, lng: lng, radiusM: Config.radiusSirensM, allowCache: allowCache)
            let (plutoF, complaintsF, liquorF, roadsF, stationsF, permitsF, facilitiesF) = try await (pl, co, li, ro, st, pe, fa)
            let parts: [(Date, Bool)] = [(plutoF.fetchedAt, plutoF.fromCache), (complaintsF.fetchedAt, complaintsF.fromCache),
                                         (liquorF.fetchedAt, liquorF.fromCache), (roadsF.fetchedAt, roadsF.fromCache),
                                         (stationsF.fetchedAt, stationsF.fromCache), (permitsF.fetchedAt, permitsF.fromCache),
                                         (facilitiesF.fetchedAt, facilitiesF.fromCache)]
            let fetchedAt = parts.map(\.0).min() ?? today
            let fromCache = parts.contains { $0.1 }
            let inputs = Inputs(address: address, asOf: asOf, lookbackMonths: Config.lookbackMonths, since: since,
                                pluto: plutoF.value.first, complaints: complaintsF.value, liquor: liquorF.value, roads: roadsF.value,
                                stations: stationsF.value, permits: permitsF.value, facilities: facilitiesF.value, sources: Self.sources)
            let pulled = Pulled(inputs: inputs, fetchedAt: fetchedAt, fromCache: fromCache)
            if !fromCache {
                cache.put("pull", key: Self.pullKey(address), request: address.label ?? address.id, value: inputs, fetchedAt: fetchedAt)
            }
            return pulled
        } catch {
            if allowCache, let c = cached(address: address) { return c }
            throw Self.mapError(error)
        }
    }

    /// The last whole pull for this address, whatever its age. Never touches the network.
    public func cached(address: GeoAddress) -> Pulled? {
        guard let hit = cache.get("pull", key: Self.pullKey(address), as: Inputs.self) else { return nil }
        return Pulled(inputs: hit.value, fetchedAt: hit.fetchedAt, fromCache: true)
    }

    /// Live 311 noise complaints for the map and list: recent, wide, with status and resolution. 15-minute TTL.
    public func recentComplaints(lat: Double, lng: Double, radiusM: Double, days: Int, allowCache: Bool) async throws -> PulledComplaints {
        let since = Self.daysAgoISO(days, from: now())
        let f: Fetched<[ComplaintRow]> = try await get("recent", Dataset.complaints311, [
            ("$select", "unique_key,created_date,closed_date,complaint_type,descriptor,incident_address,status,resolution_description,latitude,longitude,location_type,bbl"),
            ("$where", "starts_with(complaint_type,'Noise') AND created_date > '\(since)' AND within_circle(location,\(lat),\(lng),\(Self.num(radiusM)))"),
            ("$order", "created_date DESC"),
            ("$limit", "500"),
        ], ttl: Self.recentTTL, allowCache: allowCache)
        return PulledComplaints(complaints: f.value, fetchedAt: f.fetchedAt, fromCache: f.fromCache)
    }
}
