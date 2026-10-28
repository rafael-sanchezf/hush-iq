import SwiftUI
import MapKit
import NoiseKit

/// One pin per address. 311 logs repeat calls about the same building at the same coordinates, so
/// the complaints are grouped by exact location; the pin carries a count and tapping it lists them.
struct ComplaintPlace: Identifiable, Hashable {
    let id: String
    let coordinate: CLLocationCoordinate2D
    let address: String?
    let rows: [ComplaintRow]

    static func == (a: ComplaintPlace, b: ComplaintPlace) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }

    var count: Int { rows.count }
    /// The category drawn on the pin: the most frequent one at this address.
    var category: ComplaintCategory {
        var counts: [ComplaintCategory: Int] = [:]
        for r in rows { counts[r.category, default: 0] += 1 }
        return counts.max { a, b in a.value == b.value ? a.key.label > b.key.label : a.value < b.value }?.key ?? .other
    }
    func matches(_ profile: Profile) -> Bool { rows.contains { $0.matches(profile) } }
    var title: String { count == 1 ? rows[0].title : "\(count) complaints" }

    /// Groups rows (already sorted nearest first) by exact coordinate, keeping that order.
    static func group(_ rows: [ComplaintRow]) -> [ComplaintPlace] {
        var order: [String] = []
        var bucket: [String: [ComplaintRow]] = [:]
        for r in rows {
            guard let lat = r.latitude, let lng = r.longitude, r.coordinate != nil else { continue }
            let key = "\(lat),\(lng)"
            if bucket[key] == nil { order.append(key) }
            bucket[key, default: []].append(r)
        }
        return order.compactMap { key in
            guard let rs = bucket[key], let c = rs[0].coordinate else { return nil }
            let newestFirst = rs.sorted { ($0.created ?? .distantPast) > ($1.created ?? .distantPast) }
            return ComplaintPlace(id: key, coordinate: c, address: rs[0].incidentAddress, rows: newestFirst)
        }
    }
}

/// The pin: a circle with the category symbol, a count badge when more than one complaint sits here.
/// Accent when any complaint here matches a chosen bother, grey otherwise.
struct PlaceMarker: View {
    let place: ComplaintPlace
    let matches: Bool
    let selected: Bool

    var body: some View {
        let size: CGFloat = selected ? 34 : 26
        Image(systemName: place.category.symbol)
            .font(.system(size: selected ? 14 : 11, weight: .bold))
            .foregroundStyle(matches ? Color.white : Color(.systemBackground))
            .frame(width: size, height: size)
            .background(Circle().fill(matches ? Theme.accent : Color(.systemGray2)))
            .overlay(Circle().stroke(Color(.systemBackground), lineWidth: selected ? 3 : 1.5))
            .overlay(alignment: .topTrailing) {
                if place.count > 1 {
                    Text("\(place.count)")
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(Color(.systemBackground))
                        .padding(.horizontal, 5)
                        .frame(minWidth: 17, minHeight: 17)
                        .background(Capsule().fill(Color(.label)))
                        .overlay(Capsule().stroke(Color(.systemBackground), lineWidth: 1.5))
                        .offset(x: 8, y: -7)
                }
            }
            .shadow(color: .black.opacity(0.2), radius: selected ? 4 : 1, y: 1)
    }
}

/// The card under the map for a selected pin: one complaint opens its detail directly; several list
/// them, newest first, each opening its detail.
struct PlaceCard: View {
    let place: ComplaintPlace
    let address: GeoAddress?
    let profile: Profile

    var body: some View {
        if place.count == 1 {
            NavigationLink(value: place.rows[0]) {
                ComplaintCard(row: place.rows[0], address: address, matches: place.rows[0].matches(profile))
            }
            .buttonStyle(PressableCardStyle())
            .accessibilityHint("Opens the complaint")
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(place.address?.capitalized ?? "Address withheld").font(.headline).lineLimit(1)
                        Text("\(place.count) complaints in 30 days").font(.subheadline).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    if let a = address, let m = place.rows[0].distanceM(from: a) {
                        Text(Format.metres(m)).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(14)
                Divider()
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(place.rows) { row in
                            NavigationLink(value: row) {
                                HStack(spacing: 12) {
                                    CategoryGlyph(category: row.category, matches: row.matches(profile), size: 32)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(row.title).font(.subheadline.weight(.semibold)).foregroundStyle(.primary).lineLimit(1)
                                        if let d = row.created { Text(Format.relative(d)).font(.caption).foregroundStyle(.secondary) }
                                    }
                                    Spacer(minLength: 4)
                                    Pill(text: row.status ?? "Unknown")
                                    Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(.tertiary)
                                }
                                .padding(.horizontal, 14)
                                .padding(.vertical, 9)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint("Opens the complaint")
                            if row.id != place.rows.last?.id { Divider().padding(.leading, 58) }
                        }
                    }
                }
                .frame(maxHeight: 200)
            }
            .background(Theme.cardShape.fill(.regularMaterial))
            .overlay(Theme.cardShape.stroke(Color(.separator), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        }
    }
}
