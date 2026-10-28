import Foundation
import CoreLocation
import NoiseKit

/// How a 311 noise complaint reads on the map, the list and the detail: its category (symbol), which
/// renter bother it matches, its time and its distance from the address.
enum ComplaintCategory: String, CaseIterable {
    case residential, vehicle, music, commercial, construction, other

    var symbol: String {
        switch self {
        case .residential: return "person.2"
        case .vehicle: return "car"
        case .music: return "music.note"
        case .commercial: return "storefront"
        case .construction: return "hammer"
        case .other: return "speaker.wave.2"
        }
    }

    var label: String {
        switch self {
        case .residential: return "Residential"
        case .vehicle: return "Vehicle"
        case .music: return "Music or party"
        case .commercial: return "Commercial"
        case .construction: return "Construction"
        case .other: return "Other"
        }
    }

    /// The renter's bother this category speaks to. Street and sidewalk noise is people; sirens have
    /// no 311 category, so that bother matches nothing on the map.
    var bother: Bother? {
        switch self {
        case .residential: return .neighbors
        case .vehicle: return .traffic
        case .music, .commercial, .other: return .people
        case .construction: return .construction
        }
    }

    init(_ row: ComplaintRow) {
        let descriptor = (row.descriptor ?? "").lowercased()
        let type = (row.complaintType ?? "").lowercased()
        if descriptor.contains("music") || descriptor.contains("party") { self = .music }
        else if descriptor.contains("construction") || descriptor.contains("jack hammer") || type.contains("construction") { self = .construction }
        else if type.contains("residential") { self = .residential }
        else if type.contains("vehicle") || descriptor.contains("horn") || descriptor.contains("engine") || descriptor.contains("truck") { self = .vehicle }
        else if type.contains("commercial") { self = .commercial }
        else { self = .other }
    }
}

extension ComplaintRow {
    var category: ComplaintCategory { ComplaintCategory(self) }

    var coordinate: CLLocationCoordinate2D? {
        guard let lat = latitude.double, let lng = longitude.double else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lng)
    }

    var created: Date? { Format.date(fromSocrata: createdDate) }
    var closed: Date? { Format.date(fromSocrata: closedDate) }

    var title: String { descriptor ?? complaintType ?? "Noise complaint" }

    /// "Noise - Residential" reads as "Residential" once the word noise is implied by the app.
    var typeLabel: String {
        guard let t = complaintType else { return "Noise" }
        let parts = t.split(separator: "-", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
        return parts.count == 2 ? parts[1] : t
    }

    var isOpen: Bool { (status ?? "").lowercased() != "closed" }

    func matches(_ profile: Profile) -> Bool {
        guard let b = category.bother else { return false }
        return profile.bothers.contains(b)
    }

    func distanceM(from address: GeoAddress) -> Double? {
        guard let c = coordinate else { return nil }
        return Distance.haversineM(lat1: address.lat, lng1: address.lng, lat2: c.latitude, lng2: c.longitude)
    }
}

/// Great-circle distance for the list sort and the detail footer. The model's own geometry lives in
/// NoiseKit; this one is only for display.
enum Distance {
    static func haversineM(lat1: Double, lng1: Double, lat2: Double, lng2: Double) -> Double {
        let r = 6_371_000.0
        let p1 = lat1 * .pi / 180, p2 = lat2 * .pi / 180
        let dp = (lat2 - lat1) * .pi / 180, dl = (lng2 - lng1) * .pi / 180
        let a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }
}

extension Array where Element == ComplaintRow {
    /// "{n} noise complaints in 30 days, mostly {top descriptor}".
    func summary(days: Int) -> String {
        if isEmpty { return "No noise complaints in \(days) days" }
        var counts: [String: Int] = [:]
        for row in self { counts[row.title, default: 0] += 1 }
        let top = counts.max { $0.value < $1.value }?.key ?? ""
        let noun = count == 1 ? "noise complaint" : "noise complaints"
        return "\(count) \(noun) in \(days) days, mostly \(top.lowercased())"
    }
}
