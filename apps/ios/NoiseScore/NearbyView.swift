import SwiftUI
import MapKit
import NoiseKit

/// Nearby tab: the same 311 noise complaints (500 m, 30 days) as a map or a list. The accent is
/// spent on the pins that match what bothers the renter; every other pin is grey.
struct NearbyView: View {
    let store: NoiseStore

    enum Mode: String, CaseIterable { case map = "Map", list = "List" }
    @State private var mode: Mode = .map
    @State private var selectedPlaceID: String?
    @State private var camera: MapCameraPosition = .automatic

    var body: some View {
        NavigationStack {
            Group {
                switch store.phase {
                case .idle, .loading:
                    if store.recent != nil { content } else { LoadingView(text: "Pulling 311 noise complaints…") }
                case .failed(let message):
                    FailedView(message: message) { await store.refresh() }
                case .ready:
                    content
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Nearby")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: ComplaintRow.self) { row in
                ComplaintDetailView(row: row, address: store.shownAddress, profile: store.profile)
            }
        }
    }

    private var rows: [ComplaintRow] { store.recentSorted }

    private var content: some View {
        VStack(spacing: 0) {
            VStack(spacing: 12) {
                if let text = store.bannerText {
                    OfflineBanner(text: text) { await store.refresh() }
                }
                Picker("View", selection: $mode) {
                    ForEach(Mode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .accessibilityLabel("Map or list")

                summary
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 8)
            .padding(.bottom, 12)

            switch mode {
            case .map: mapView
            case .list: listView
            }
        }
        .onChange(of: mode) { _, _ in selectedPlaceID = nil }
    }

    private var summary: some View {
        let matching = rows.filter { $0.matches(store.profile) }.count
        return VStack(alignment: .leading, spacing: 3) {
            Text(rows.summary(days: NoiseStore.days))
                .font(.body.weight(.semibold))
                .multilineTextAlignment(.leading)
            if !rows.isEmpty {
                Text(matching == 0
                     ? "Within 500 m of \(store.shownAddress?.displayLabel ?? "the address"). None match what bothers you."
                     : "Within 500 m of \(store.shownAddress?.displayLabel ?? "the address"). \(matching) match what bothers you.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    // MARK: Map

    private var places: [ComplaintPlace] { ComplaintPlace.group(rows) }
    private var selectedPlace: ComplaintPlace? { places.first { $0.id == selectedPlaceID } }

    private var mapView: some View {
        ZStack(alignment: .bottom) {
            // Selection is the map's own: tapping a pin selects it, tapping the map clears it. No extra
            // gestures on the Map, so pinch and double-tap zoom stay MapKit's.
            Map(position: $camera, selection: $selectedPlaceID) {
                if let a = store.shownAddress {
                    let center = CLLocationCoordinate2D(latitude: a.lat, longitude: a.lng)
                    MapCircle(center: center, radius: NoiseStore.radiusM)
                        .foregroundStyle(Color(.label).opacity(0.05))
                        .stroke(Color(.label).opacity(0.3), lineWidth: 1)
                    Annotation("Your place", coordinate: center, anchor: .center) {
                        Circle()
                            .fill(Color(.label))
                            .frame(width: 14, height: 14)
                            .overlay(Circle().stroke(Color(.systemBackground), lineWidth: 3))
                            .accessibilityLabel("Your place")
                    }
                    .annotationTitles(.hidden)
                }
                ForEach(places) { place in
                    Annotation(place.title, coordinate: place.coordinate, anchor: .center) {
                        PlaceMarker(place: place, matches: place.matches(store.profile), selected: selectedPlaceID == place.id)
                            .accessibilityLabel(place.count == 1
                                                ? "\(place.rows[0].title), \(place.address ?? "")"
                                                : "\(place.count) complaints at \(place.address ?? "this address")")
                            .accessibilityHint("Shows the complaints here")
                    }
                    .annotationTitles(.hidden)
                    .tag(place.id)
                }
            }
            .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
            .mapControls { MapCompass(); MapScaleView() }
            .task(id: store.shownAddress?.id) { recentre() }
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
            .padding(.horizontal, Theme.gutter)
            .padding(.bottom, Theme.gutter)

            if let place = selectedPlace {
                PlaceCard(place: place, address: store.shownAddress, profile: store.profile)
                    .padding(.horizontal, Theme.gutter + 12)
                    .padding(.bottom, Theme.gutter + 12)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .animation(.spring(response: 0.3, dampingFraction: 0.85), value: selectedPlaceID)
            }
        }
        .overlay {
            if rows.isEmpty {
                ContentUnavailableView("No complaints nearby", systemImage: "checkmark.circle",
                                       description: Text("No 311 noise complaints within 500 m in the last 30 days."))
                    .background(Theme.cardShape.fill(.ultraThinMaterial))
                    .padding(Theme.gutter)
            }
        }
    }

    private func recentre() {
        guard let a = store.shownAddress else { return }
        camera = .region(MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: a.lat, longitude: a.lng),
                                            latitudinalMeters: NoiseStore.radiusM * 2.6, longitudinalMeters: NoiseStore.radiusM * 2.6))
    }

    // MARK: List

    @ViewBuilder
    private var listView: some View {
        if rows.isEmpty {
            ContentUnavailableView("No complaints nearby", systemImage: "checkmark.circle",
                                   description: Text("No 311 noise complaints within 500 m in the last 30 days."))
        } else {
            List(rows) { row in
                NavigationLink(value: row) {
                    ComplaintListRow(row: row, address: store.shownAddress, matches: row.matches(store.profile))
                }
                .listRowInsets(EdgeInsets(top: 10, leading: Theme.gutter, bottom: 10, trailing: Theme.gutter))
                .accessibilityHint("Opens the complaint")
            }
            .listStyle(.plain)
            .refreshable { await store.refresh() }
        }
    }
}

/// The pin: a circle with the category symbol. Accent when it matches a chosen bother, grey otherwise.
struct ComplaintMarker: View {
    let row: ComplaintRow
    let matches: Bool
    let selected: Bool

    var body: some View {
        Image(systemName: row.category.symbol)
            .font(.system(size: selected ? 14 : 11, weight: .bold))
            .foregroundStyle(matches ? Color.white : Color(.systemBackground))
            .frame(width: selected ? 34 : 26, height: selected ? 34 : 26)
            .background(Circle().fill(matches ? Theme.accent : Color(.systemGray2)))
            .overlay(Circle().stroke(Color(.systemBackground), lineWidth: selected ? 3 : 1.5))
            .shadow(color: .black.opacity(0.2), radius: selected ? 4 : 1, y: 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.7), value: selected)
    }
}

/// The category glyph used in rows and cards.
struct CategoryGlyph: View {
    let category: ComplaintCategory
    var matches: Bool
    var size: CGFloat = 40

    var body: some View {
        Image(systemName: category.symbol)
            .font(.system(size: size * 0.42, weight: .semibold))
            .foregroundStyle(matches ? Color.white : Color(.secondaryLabel))
            .frame(width: size, height: size)
            .background(RoundedRectangle(cornerRadius: size * 0.3, style: .continuous).fill(matches ? Theme.accent : Theme.track))
            .accessibilityHidden(true)
    }
}

/// The card under the map for the selected pin.
struct ComplaintCard: View {
    let row: ComplaintRow
    let address: GeoAddress?
    let matches: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            CategoryGlyph(category: row.category, matches: matches, size: 44)
            VStack(alignment: .leading, spacing: 4) {
                Text(row.title).font(.headline).foregroundStyle(.primary).lineLimit(2)
                Text(row.incidentAddress?.capitalized ?? "Address withheld").font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                HStack(spacing: 6) {
                    if let d = row.created { Text(Format.relative(d)) }
                    if let a = address, let m = row.distanceM(from: a) { Text("·"); Text(Format.metres(m)) }
                    Spacer(minLength: 8)
                    Pill(text: row.status ?? "Unknown")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
                .padding(.top, 4)
        }
        .multilineTextAlignment(.leading)
        .padding(14)
        .background(Theme.cardShape.fill(.regularMaterial))
        .overlay(Theme.cardShape.stroke(Color(.separator), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        .accessibilityElement(children: .combine)
    }
}

/// One row of the list: symbol, descriptor, address, relative time and distance, status pill.
struct ComplaintListRow: View {
    let row: ComplaintRow
    let address: GeoAddress?
    let matches: Bool

    var body: some View {
        HStack(spacing: 14) {
            CategoryGlyph(category: row.category, matches: matches)
            VStack(alignment: .leading, spacing: 3) {
                Text(row.title).font(.body.weight(.semibold)).lineLimit(1)
                Text(row.incidentAddress?.capitalized ?? "Address withheld").font(.subheadline).foregroundStyle(.secondary).lineLimit(1)
                HStack(spacing: 6) {
                    if let d = row.created { Text(Format.relative(d)) }
                    if let a = address, let m = row.distanceM(from: a) { Text("·"); Text(Format.metres(m)) }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 4)
            Pill(text: row.status ?? "Unknown")
        }
        .accessibilityElement(children: .combine)
    }
}

#Preview("Map") {
    NearbyView(store: NoiseStore.preview())
}

#Preview("Sample fallback") {
    NearbyView(store: NoiseStore.preview(offline: true, sample: true))
}
