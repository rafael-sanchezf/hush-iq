import SwiftUI
import MapKit
import NoiseKit

/// One 311 complaint, the separate detail view the assignment asks for. The accent is spent on the
/// status pill.
struct ComplaintDetailView: View {
    let row: ComplaintRow
    let address: GeoAddress?
    let profile: Profile

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                facts
                if let text = row.resolutionDescription, !text.isEmpty {
                    quote(text)
                }
                snippet
                footer
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 8)
            .padding(.bottom, 40)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemBackground))
        .navigationTitle("Complaint")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 14) {
                CategoryGlyph(category: row.category, matches: false, size: 48)
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.title)
                        .font(.system(.title, design: .rounded, weight: .bold))
                        .multilineTextAlignment(.leading)
                    Text([row.typeLabel, row.locationType].compactMap { $0 }.joined(separator: " · "))
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            Pill(text: row.status ?? "Unknown", accent: true)
                .accessibilityLabel("Status: \(row.status ?? "unknown")")
            if row.matches(profile) {
                Text("This is one of the things you said gets to you.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }

    private var facts: some View {
        VStack(alignment: .leading, spacing: 12) {
            fact("Where", row.incidentAddress?.capitalized ?? "Address withheld by 311")
            Divider()
            fact("Reported", row.created.map { Format.dateTime($0) } ?? row.createdDate ?? "Unknown")
            Divider()
            fact("Closed", row.closed.map { Format.dateTime($0) } ?? (row.isOpen ? "Still open" : "Unknown"))
            if let a = address, let m = row.distanceM(from: a) {
                Divider()
                fact("Distance", "\(Format.metres(m)) from \(a.displayLabel ?? "your place")")
            }
        }
        .card()
    }

    private func fact(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(label)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 80, alignment: .leading)
            Text(value).font(.body).multilineTextAlignment(.leading)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }

    private func quote(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionLabel(text: "What 311 said")
            HStack(alignment: .top, spacing: 14) {
                RoundedRectangle(cornerRadius: 2).fill(Color(.label).opacity(0.25)).frame(width: 3)
                Text(text)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineSpacing(3)
                    .multilineTextAlignment(.leading)
            }
            .padding(.vertical, 4)
        }
    }

    @ViewBuilder
    private var snippet: some View {
        if let c = row.coordinate {
            VStack(alignment: .leading, spacing: 10) {
                SectionLabel(text: "Where it is")
                Map(initialPosition: .region(MKCoordinateRegion(center: c, latitudinalMeters: 500, longitudinalMeters: 500)),
                    interactionModes: []) {
                    Annotation(row.title, coordinate: c, anchor: .center) {
                        ComplaintMarker(row: row, matches: false, selected: true)
                    }
                    .annotationTitles(.hidden)
                    if let a = address {
                        Annotation("Your place", coordinate: CLLocationCoordinate2D(latitude: a.lat, longitude: a.lng), anchor: .center) {
                            Circle().fill(Color(.label)).frame(width: 12, height: 12)
                                .overlay(Circle().stroke(Color(.systemBackground), lineWidth: 2.5))
                        }
                        .annotationTitles(.hidden)
                    }
                }
                .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
                .frame(height: 190)
                .clipShape(Theme.cardShape)
                .accessibilityLabel("Map of the complaint location")
            }
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 4) {
            Divider().padding(.bottom, 8)
            Text("311 key \(row.uniqueKey)")
            Text("NYC 311 Service Requests, dataset erm2-nwe9, via NYC Open Data.")
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
        .accessibilityElement(children: .combine)
    }
}

#Preview("Detail") {
    let store = NoiseStore.preview()
    NavigationStack {
        ComplaintDetailView(row: store.recentSorted[0], address: store.shownAddress, profile: store.profile)
    }
}
