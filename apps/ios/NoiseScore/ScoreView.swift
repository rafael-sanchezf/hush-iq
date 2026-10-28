import SwiftUI
import NoiseKit

/// Home tab. The verdict against Manhattan (the meter is the one accent), the time of day, the sources
/// windows, the ingredients, and a footer that says where the data came from and when.
struct ScoreView: View {
    let store: NoiseStore
    @State private var editing = false

    var body: some View {
        NavigationStack {
            Group {
                switch store.phase {
                case .idle, .loading:
                    if let result = store.result {
                        content(result)
                    } else {
                        LoadingView(text: "Pulling NYC Open Data for \(store.address?.displayLabel ?? "your address")…")
                    }
                case .failed(let message):
                    FailedView(message: message) { await store.refresh() }
                case .ready:
                    if let result = store.result {
                        content(result)
                    } else {
                        FailedView(message: "The model returned nothing for this address.") { await store.refresh() }
                    }
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Hush IQ")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Edit answers") { editing = true }
                        .accessibilityLabel("Edit your answers")
                }
            }
            .sheet(isPresented: $editing) {
                SurveyView(store: store) { editing = false }
            }
            .navigationDestination(for: Ingredient.self) { ing in
                IngredientDetailView(ingredient: ing, unit: store.unit, profile: store.profile)
            }
        }
    }

    private func content(_ result: ScoreResult) -> some View {
        let base = Baseline.manhattan
        let rank = base?.rank(level: result.internalLevel, unit: store.unit, profile: store.profile)
        let windowRanks = base.map { b in Window.allCases.map { b.windowRank(result, window: $0, unit: store.unit) } } ?? []
        return ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if let text = store.bannerText {
                    OfflineBanner(text: text) { await store.refresh() }
                }

                if let rank {
                    NavigationLink {
                        RankDetailView(rank: rank, windows: windowRanks, forWhom: forWhom)
                    } label: {
                        VerdictCard(rank: rank, addressLine: addressLine, forWhom: forWhom)
                    }
                    .buttonStyle(.plain)
                }

                if !windowRanks.isEmpty {
                    whenItsLoud(windowRanks, result)
                }

                whatYoullHear(result)

                footer(result)
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 8)
            .padding(.bottom, 40)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .refreshable { await store.refresh() }
    }

    /// "2900 Broadway · floor 4 · street side"
    private var addressLine: String {
        var parts = [store.shownAddress?.displayLabel.map { $0.components(separatedBy: ",").first ?? $0 } ?? "Your place"]
        if let f = store.unit.floor { parts.append("floor \(f)") }
        switch store.unit.position {
        case .front: parts.append("street side")
        case .rear: parts.append("back")
        case .unknown: break
        }
        return parts.joined(separator: " · ")
    }

    /// "For a light sleeper bothered by traffic, nightlife and sirens."
    private var forWhom: String {
        let p = store.profile
        let sleeper: String
        switch p.sleep {
        case .light: sleeper = "a light sleeper"
        case .normal: sleeper = "a normal sleeper"
        case .heavy: sleeper = "a heavy sleeper"
        }
        let names: [Bother: String] = [.traffic: "traffic", .people: "nightlife", .neighbors: "neighbors", .sirens: "sirens", .construction: "construction"]
        let bothers = Bother.allCases.filter { p.bothers.contains($0) }.compactMap { names[$0] }
        var s = "For \(sleeper)"
        if p.wfh { s += " who works from home" }
        if !bothers.isEmpty {
            let list = bothers.count == 1 ? bothers[0] : bothers.dropLast().joined(separator: ", ") + " and " + bothers.last!
            s += " bothered by \(list)"
        }
        return s + "."
    }

    // MARK: When it's loud

    private func whenItsLoud(_ ranks: [Baseline.WindowRank], _ result: ScoreResult) -> some View {
        let focus = ranks.max { a, b in
            let wa = result.windowWeights[a.window] ?? 0, wb = result.windowWeights[b.window] ?? 0
            return wa == wb ? a.window != .night && b.window == .night : wa < wb
        } ?? ranks[0]
        return VStack(alignment: .leading, spacing: 14) {
            SectionLabel(text: "When it's loud")
            VStack(spacing: 0) {
                ForEach(ranks, id: \.window) { r in
                    WindowRow(rank: r).padding(.vertical, 12)
                    if r.window != ranks.last?.window { Divider() }
                }
            }
            .padding(.horizontal, 16)
            .background(Theme.cardShape.fill(Theme.card))
            Text("\(focus.window.label) is about \(Int(focus.levelDb.rounded())) dB at your window, like \(Loudness.anchor(focus.levelDb)).")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: What you'll hear

    private func whatYoullHear(_ result: ScoreResult) -> some View {
        let sorted = result.ingredients.sorted { $0.loudestWindow.db > $1.loudestWindow.db }
        return VStack(alignment: .leading, spacing: 14) {
            SectionLabel(text: "What you'll hear")
            VStack(spacing: 10) {
                ForEach(sorted) { ing in
                    NavigationLink(value: ing) {
                        SourceRow(ingredient: ing)
                    }
                    .buttonStyle(PressableCardStyle())
                    .accessibilityLabel(ing.accessibilitySummary)
                    .accessibilityHint("Shows the evidence")
                }
            }
        }
    }

    // MARK: Footer

    private func footer(_ result: ScoreResult) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Divider()
            VStack(alignment: .leading, spacing: 4) {
                Text(store.shownAddress?.displayLabel ?? "No address")
                    .font(.body.weight(.semibold))
                HStack(spacing: 6) {
                    Image(systemName: store.isOffline || store.usingSample ? "wifi.slash" : "arrow.triangle.2.circlepath")
                        .font(.caption)
                    Text(store.pulledCaption)
                }
                .font(.subheadline)
                .foregroundStyle(.secondary)
                if let unitLine = unitLine {
                    Text(unitLine).font(.subheadline).foregroundStyle(.secondary)
                }
            }

            if let sources = store.pulled?.inputs.sources, !sources.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    SectionLabel(text: "Sources")
                    ForEach(sources, id: \.url) { s in
                        if let url = URL(string: s.url) {
                            Link(destination: url) {
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    Image(systemName: "arrow.up.right").font(.caption2.weight(.bold)).foregroundStyle(.tertiary)
                                    Text(s.name).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.leading)
                                }
                            }
                            .accessibilityLabel("Open \(s.name)")
                        } else {
                            Text(s.name).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            if !result.caveats.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    SectionLabel(text: "Caveats")
                    ForEach(result.caveats, id: \.self) { c in
                        Text(c).font(.footnote).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var unitLine: String? {
        let floor = store.unit.floor.map { "floor \($0)" } ?? "floor unknown"
        let side: String
        switch store.unit.position {
        case .front: side = "street side"
        case .rear: side = "courtyard or back"
        case .unknown: side = "side unknown"
        }
        let sleep: String
        switch store.profile.sleep {
        case .light: sleep = "light sleeper"
        case .normal: sleep = "normal sleeper"
        case .heavy: sleep = "heavy sleeper"
        }
        return "Scored for \(floor), \(side), \(sleep)\(store.profile.wfh ? ", works from home" : "")"
    }
}

// MARK: - States shared by both tabs

struct OfflineBanner: View {
    let text: String
    let retry: () async -> Void
    @State private var retrying = false

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "wifi.slash").font(.subheadline.weight(.semibold))
            Text(text).font(.footnote.weight(.medium)).multilineTextAlignment(.leading)
            Spacer(minLength: 4)
            Button(retrying ? "…" : "Retry") {
                retrying = true
                Task { await retry(); retrying = false }
            }
            .font(.footnote.weight(.semibold))
            .disabled(retrying)
            .accessibilityLabel("Retry loading live data")
        }
        .foregroundStyle(.primary)
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.track))
        .accessibilityElement(children: .contain)
    }
}

struct LoadingView: View {
    let text: String
    var body: some View {
        VStack(spacing: 16) {
            ProgressView().controlSize(.large)
            Text(text).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(Theme.gutter)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct FailedView: View {
    let message: String
    let retry: () async -> Void
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle").font(.largeTitle).foregroundStyle(.secondary)
            Text("Could not load").font(.title3.weight(.semibold))
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button("Retry") { Task { await retry() } }
                .buttonStyle(PrimaryButtonStyle())
                .frame(maxWidth: 240)
        }
        .padding(Theme.gutter)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

#Preview("Score") {
    ScoreView(store: NoiseStore.preview())
}

#Preview("Score, offline") {
    ScoreView(store: NoiseStore.preview(offline: true))
}

#Preview("Score, sample fallback") {
    ScoreView(store: NoiseStore.preview(offline: true, sample: true))
}
