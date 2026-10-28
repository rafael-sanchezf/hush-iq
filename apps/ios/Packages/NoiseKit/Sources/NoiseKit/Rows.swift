import Foundation

// The data contract: one struct per upstream row, with exactly the fields the Python prototype
// selects (noise_score/sources.py) plus the few the app's detail view adds. Socrata returns most
// numbers as strings, but not all, so every scalar is decoded leniently into a String and parsed
// where it is used. Property names are camelCase; CodingKeys carry the Socrata field names, which
// are also the keys in the Python fixtures under Tests/NoiseKitTests/Fixtures.

// MARK: - Lenient decoding

extension KeyedDecodingContainer {
    /// A string from a value that may arrive as a string, a number or a bool. Missing or null is nil.
    func loose(_ key: Key) -> String? {
        if let s = try? decodeIfPresent(String.self, forKey: key) { return s }
        if let i = try? decodeIfPresent(Int.self, forKey: key) { return String(i) }
        if let d = try? decodeIfPresent(Double.self, forKey: key) { return String(d) }
        if let b = try? decodeIfPresent(Bool.self, forKey: key) { return b ? "true" : "false" }
        return nil
    }
}

public extension Optional where Wrapped == String {
    var double: Double? { flatMap(Double.init) }
    var int: Int? { flatMap { Int($0) ?? Double($0).map { Int($0) } } }
}

// MARK: - GeoJSON

/// The geometry shapes Socrata hands back: a point (liquor `georeference`) or a line (`the_geom` on roads).
public enum GeoJSON: Codable, Hashable, Sendable {
    /// (lng, lat), in GeoJSON order.
    case point(lng: Double, lat: Double)
    /// Each coordinate is [lng, lat].
    case lineString([[Double]])
    case multiLineString([[[Double]]])
    case other(type: String)

    enum CodingKeys: String, CodingKey { case type, coordinates }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let type = try c.decode(String.self, forKey: .type)
        switch type {
        case "Point":
            let xy = try c.decode([Double].self, forKey: .coordinates)
            guard xy.count >= 2 else { self = .other(type: type); return }
            self = .point(lng: xy[0], lat: xy[1])
        case "LineString":
            self = .lineString(try c.decode([[Double]].self, forKey: .coordinates))
        case "MultiLineString":
            self = .multiLineString(try c.decode([[[Double]]].self, forKey: .coordinates))
        default:
            self = .other(type: type)
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .point(lng, lat):
            try c.encode("Point", forKey: .type); try c.encode([lng, lat], forKey: .coordinates)
        case let .lineString(xs):
            try c.encode("LineString", forKey: .type); try c.encode(xs, forKey: .coordinates)
        case let .multiLineString(xs):
            try c.encode("MultiLineString", forKey: .type); try c.encode(xs, forKey: .coordinates)
        case let .other(type):
            try c.encode(type, forKey: .type)
        }
    }

    /// Every line of the geometry as a list of [lng, lat] pairs. Empty for points.
    public var lines: [[[Double]]] {
        switch self {
        case let .lineString(l): return [l]
        case let .multiLineString(ls): return ls
        default: return []
        }
    }
}

// MARK: - Rows

/// NYC 311 Service Requests, dataset erm2-nwe9. The score uses the first eight fields (24 months, around
/// the address); the map and detail screens also ask for status, resolution and location type.
public struct ComplaintRow: Codable, Hashable, Identifiable, Sendable {
    public var uniqueKey: String
    public var complaintType: String?
    public var descriptor: String?
    /// ISO local time as 311 gives it, e.g. "2026-10-21T00:35:53.000".
    public var createdDate: String?
    public var latitude: String?
    public var longitude: String?
    public var bbl: String?
    public var incidentAddress: String?
    public var status: String?
    public var resolutionDescription: String?
    public var locationType: String?
    public var closedDate: String?

    public var id: String { uniqueKey }

    enum CodingKeys: String, CodingKey {
        case uniqueKey = "unique_key", complaintType = "complaint_type", descriptor
        case createdDate = "created_date", latitude, longitude, bbl, incidentAddress = "incident_address"
        case status, resolutionDescription = "resolution_description", locationType = "location_type"
        case closedDate = "closed_date"
    }

    public init(uniqueKey: String, complaintType: String? = nil, descriptor: String? = nil, createdDate: String? = nil,
                latitude: String? = nil, longitude: String? = nil, bbl: String? = nil, incidentAddress: String? = nil,
                status: String? = nil, resolutionDescription: String? = nil, locationType: String? = nil, closedDate: String? = nil) {
        self.uniqueKey = uniqueKey; self.complaintType = complaintType; self.descriptor = descriptor
        self.createdDate = createdDate; self.latitude = latitude; self.longitude = longitude; self.bbl = bbl
        self.incidentAddress = incidentAddress; self.status = status; self.resolutionDescription = resolutionDescription
        self.locationType = locationType; self.closedDate = closedDate
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        uniqueKey = c.loose(.uniqueKey) ?? UUID().uuidString
        complaintType = c.loose(.complaintType); descriptor = c.loose(.descriptor)
        createdDate = c.loose(.createdDate); latitude = c.loose(.latitude); longitude = c.loose(.longitude)
        bbl = c.loose(.bbl); incidentAddress = c.loose(.incidentAddress); status = c.loose(.status)
        resolutionDescription = c.loose(.resolutionDescription); locationType = c.loose(.locationType)
        closedDate = c.loose(.closedDate)
    }
}

/// NYC PLUTO, dataset 64uk-42ks: the tax lot the address sits on.
public struct PlutoRow: Codable, Hashable, Sendable {
    public var address: String?
    public var borough: String?
    public var yearbuilt: String?
    public var yearalter1: String?
    public var yearalter2: String?
    public var numfloors: String?
    public var bldgclass: String?
    public var unitsres: String?
    public var unitstotal: String?
    public var landuse: String?
    public var lotfront: String?
    public var bldgdepth: String?
    public var zonedist1: String?

    enum CodingKeys: String, CodingKey {
        case address, borough, yearbuilt, yearalter1, yearalter2, numfloors, bldgclass, unitsres, unitstotal, landuse, lotfront, bldgdepth, zonedist1
    }

    public init(address: String? = nil, borough: String? = nil, yearbuilt: String? = nil, yearalter1: String? = nil, yearalter2: String? = nil,
                numfloors: String? = nil, bldgclass: String? = nil, unitsres: String? = nil, unitstotal: String? = nil, landuse: String? = nil,
                lotfront: String? = nil, bldgdepth: String? = nil, zonedist1: String? = nil) {
        self.address = address; self.borough = borough; self.yearbuilt = yearbuilt; self.yearalter1 = yearalter1; self.yearalter2 = yearalter2
        self.numfloors = numfloors; self.bldgclass = bldgclass; self.unitsres = unitsres; self.unitstotal = unitstotal; self.landuse = landuse
        self.lotfront = lotfront; self.bldgdepth = bldgdepth; self.zonedist1 = zonedist1
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        address = c.loose(.address); borough = c.loose(.borough); yearbuilt = c.loose(.yearbuilt)
        yearalter1 = c.loose(.yearalter1); yearalter2 = c.loose(.yearalter2); numfloors = c.loose(.numfloors)
        bldgclass = c.loose(.bldgclass); unitsres = c.loose(.unitsres); unitstotal = c.loose(.unitstotal)
        landuse = c.loose(.landuse); lotfront = c.loose(.lotfront); bldgdepth = c.loose(.bldgdepth); zonedist1 = c.loose(.zonedist1)
    }
}

/// NYC Street Centerline, dataset inkn-q76z. `theGeom` is a LineString or MultiLineString.
public struct RoadRow: Codable, Hashable, Sendable {
    public var fullStreetName: String?
    public var rwType: String?
    public var streetwidth: String?
    public var trafdir: String?
    public var numberTotalLanes: String?
    public var numberTravelLanes: String?
    public var postedSpeed: String?
    public var snowPriority: String?
    public var status: String?
    public var theGeom: GeoJSON?

    enum CodingKeys: String, CodingKey {
        case fullStreetName = "full_street_name", rwType = "rw_type", streetwidth, trafdir
        case numberTotalLanes = "number_total_lanes", numberTravelLanes = "number_travel_lanes"
        case postedSpeed = "posted_speed", snowPriority = "snow_priority", status, theGeom = "the_geom"
    }

    public init(fullStreetName: String? = nil, rwType: String? = nil, streetwidth: String? = nil, trafdir: String? = nil,
                numberTotalLanes: String? = nil, numberTravelLanes: String? = nil, postedSpeed: String? = nil,
                snowPriority: String? = nil, status: String? = nil, theGeom: GeoJSON? = nil) {
        self.fullStreetName = fullStreetName; self.rwType = rwType; self.streetwidth = streetwidth; self.trafdir = trafdir
        self.numberTotalLanes = numberTotalLanes; self.numberTravelLanes = numberTravelLanes; self.postedSpeed = postedSpeed
        self.snowPriority = snowPriority; self.status = status; self.theGeom = theGeom
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        fullStreetName = c.loose(.fullStreetName); rwType = c.loose(.rwType); streetwidth = c.loose(.streetwidth)
        trafdir = c.loose(.trafdir); numberTotalLanes = c.loose(.numberTotalLanes); numberTravelLanes = c.loose(.numberTravelLanes)
        postedSpeed = c.loose(.postedSpeed); snowPriority = c.loose(.snowPriority); status = c.loose(.status)
        theGeom = try? c.decodeIfPresent(GeoJSON.self, forKey: .theGeom)
    }
}

/// DOB NOW approved permits, dataset rbx6-tga4, on the same tax block.
public struct PermitRow: Codable, Hashable, Sendable {
    public var workType: String?
    public var workPermit: String?
    public var jobDescription: String?
    public var approvedDate: String?
    public var issuedDate: String?
    public var expiredDate: String?
    public var estimatedJobCosts: String?
    public var houseNo: String?
    public var streetName: String?
    public var bin: String?

    enum CodingKeys: String, CodingKey {
        case workType = "work_type", workPermit = "work_permit", jobDescription = "job_description"
        case approvedDate = "approved_date", issuedDate = "issued_date", expiredDate = "expired_date"
        case estimatedJobCosts = "estimated_job_costs", houseNo = "house_no", streetName = "street_name", bin
    }

    public init(workType: String? = nil, workPermit: String? = nil, jobDescription: String? = nil, approvedDate: String? = nil,
                issuedDate: String? = nil, expiredDate: String? = nil, estimatedJobCosts: String? = nil, houseNo: String? = nil,
                streetName: String? = nil, bin: String? = nil) {
        self.workType = workType; self.workPermit = workPermit; self.jobDescription = jobDescription; self.approvedDate = approvedDate
        self.issuedDate = issuedDate; self.expiredDate = expiredDate; self.estimatedJobCosts = estimatedJobCosts
        self.houseNo = houseNo; self.streetName = streetName; self.bin = bin
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        workType = c.loose(.workType); workPermit = c.loose(.workPermit); jobDescription = c.loose(.jobDescription)
        approvedDate = c.loose(.approvedDate); issuedDate = c.loose(.issuedDate); expiredDate = c.loose(.expiredDate)
        estimatedJobCosts = c.loose(.estimatedJobCosts); houseNo = c.loose(.houseNo); streetName = c.loose(.streetName); bin = c.loose(.bin)
    }
}

/// NYS Liquor Authority active licenses, dataset 9s3h-dpkz on data.ny.gov. `georeference` is a Point.
public struct LiquorRow: Codable, Hashable, Sendable {
    public var legalname: String?
    public var description: String?
    public var type: String?
    public var `class`: String?
    public var actualaddressofpremises: String?
    public var georeference: GeoJSON?

    enum CodingKeys: String, CodingKey { case legalname, description, type, `class`, actualaddressofpremises, georeference }

    public init(legalname: String? = nil, description: String? = nil, type: String? = nil, class: String? = nil,
                actualaddressofpremises: String? = nil, georeference: GeoJSON? = nil) {
        self.legalname = legalname; self.description = description; self.type = type; self.class = `class`
        self.actualaddressofpremises = actualaddressofpremises; self.georeference = georeference
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        legalname = c.loose(.legalname); description = c.loose(.description); type = c.loose(.type)
        `class` = c.loose(.class); actualaddressofpremises = c.loose(.actualaddressofpremises)
        georeference = try? c.decodeIfPresent(GeoJSON.self, forKey: .georeference)
    }
}

/// MTA subway stations, dataset 39hk-dx4f on data.ny.gov.
public struct StationRow: Codable, Hashable, Sendable {
    public var stopName: String?
    public var daytimeRoutes: String?
    public var structure: String?
    public var gtfsLatitude: String?
    public var gtfsLongitude: String?

    enum CodingKeys: String, CodingKey {
        case stopName = "stop_name", daytimeRoutes = "daytime_routes", structure, gtfsLatitude = "gtfs_latitude", gtfsLongitude = "gtfs_longitude"
    }

    public init(stopName: String? = nil, daytimeRoutes: String? = nil, structure: String? = nil, gtfsLatitude: String? = nil, gtfsLongitude: String? = nil) {
        self.stopName = stopName; self.daytimeRoutes = daytimeRoutes; self.structure = structure
        self.gtfsLatitude = gtfsLatitude; self.gtfsLongitude = gtfsLongitude
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stopName = c.loose(.stopName); daytimeRoutes = c.loose(.daytimeRoutes); structure = c.loose(.structure)
        gtfsLatitude = c.loose(.gtfsLatitude); gtfsLongitude = c.loose(.gtfsLongitude)
    }
}

/// An emergency facility near the address, normalised from its source dataset by the Sources layer.
/// The sirens ingredient (DECISIONS.md M11) reads these. Not present in fixtures written before M11.
public struct FacilityRow: Codable, Hashable, Sendable {
    public enum Kind: String, Codable, Sendable { case hospital, fire, police }
    public var name: String
    public var kind: Kind
    public var address: String?
    public var latitude: Double
    public var longitude: Double

    public init(name: String, kind: Kind, address: String? = nil, latitude: Double, longitude: Double) {
        self.name = name; self.kind = kind; self.address = address; self.latitude = latitude; self.longitude = longitude
    }
}

/// The geocoded address, from NYC GeoSearch (geosearch.planninglabs.nyc/v2/search).
public struct GeoAddress: Codable, Hashable, Identifiable, Sendable {
    public var query: String?
    public var label: String?
    public var lat: Double
    public var lng: Double
    public var bbl: String?
    public var bin: String?
    public var borough: String?

    public var id: String { "\(lat),\(lng)" }

    public init(query: String? = nil, label: String? = nil, lat: Double, lng: Double, bbl: String? = nil, bin: String? = nil, borough: String? = nil) {
        self.query = query; self.label = label; self.lat = lat; self.lng = lng; self.bbl = bbl; self.bin = bin; self.borough = borough
    }
}

public struct SourceRef: Codable, Hashable, Sendable {
    public var name: String
    public var url: String
    public init(name: String, url: String) { self.name = name; self.url = url }
}

/// Everything the model needs for one address: the shape of Python's `sources.pull_all` and of the
/// `*.inputs.json` fixtures. Keys are snake_case in JSON.
public struct Inputs: Codable, Hashable, Sendable {
    public var address: GeoAddress
    /// "YYYY-MM-DD", the day the pulls were made. Drives permit expiry.
    public var asOf: String
    public var lookbackMonths: Int
    public var since: String?
    public var pluto: PlutoRow?
    public var complaints: [ComplaintRow]
    public var liquor: [LiquorRow]
    public var roads: [RoadRow]
    public var stations: [StationRow]
    public var permits: [PermitRow]
    public var facilities: [FacilityRow]
    public var sources: [SourceRef]

    enum CodingKeys: String, CodingKey {
        case address, asOf = "as_of", lookbackMonths = "lookback_months", since, pluto, complaints, liquor, roads, stations, permits, facilities, sources
    }

    public init(address: GeoAddress, asOf: String, lookbackMonths: Int, since: String? = nil, pluto: PlutoRow? = nil,
                complaints: [ComplaintRow] = [], liquor: [LiquorRow] = [], roads: [RoadRow] = [], stations: [StationRow] = [],
                permits: [PermitRow] = [], facilities: [FacilityRow] = [], sources: [SourceRef] = []) {
        self.address = address; self.asOf = asOf; self.lookbackMonths = lookbackMonths; self.since = since; self.pluto = pluto
        self.complaints = complaints; self.liquor = liquor; self.roads = roads; self.stations = stations; self.permits = permits
        self.facilities = facilities; self.sources = sources
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        address = try c.decode(GeoAddress.self, forKey: .address)
        asOf = c.loose(.asOf) ?? ""
        lookbackMonths = c.loose(.lookbackMonths).int ?? 24
        since = c.loose(.since)
        pluto = try? c.decodeIfPresent(PlutoRow.self, forKey: .pluto)
        complaints = (try? c.decodeIfPresent([ComplaintRow].self, forKey: .complaints)) ?? []
        liquor = (try? c.decodeIfPresent([LiquorRow].self, forKey: .liquor)) ?? []
        roads = (try? c.decodeIfPresent([RoadRow].self, forKey: .roads)) ?? []
        stations = (try? c.decodeIfPresent([StationRow].self, forKey: .stations)) ?? []
        permits = (try? c.decodeIfPresent([PermitRow].self, forKey: .permits)) ?? []
        facilities = (try? c.decodeIfPresent([FacilityRow].self, forKey: .facilities)) ?? []
        sources = (try? c.decodeIfPresent([SourceRef].self, forKey: .sources)) ?? []
    }
}
