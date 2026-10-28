import SwiftUI
import NoiseKit

/// One source: its decibels by time of day, the evidence as a checklist the renter can verify on the
/// street, and the position adjustment in words. The accent is spent on the number.
struct IngredientDetailView: View {
    let ingredient: Ingredient
    let unit: Unit
    let profile: Profile
    @State private var checked: Set<Int> = []
    @ScaledMetric(relativeTo: .largeTitle) private var numeralSize: CGFloat = 64

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                header
                windows
                evidence
                position
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 8)
            .padding(.bottom, 40)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemBackground))
        .navigationTitle(ingredient.label)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var header: some View {
        let loud = ingredient.loudestWindow
        return VStack(alignment: .leading, spacing: 8) {
            Text(SourceWords.title(ingredient))
                .font(.title2.weight(.bold))
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text("\(Int(loud.db.rounded())) dB")
                    .font(.system(size: numeralSize, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.accent)
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                VStack(alignment: .leading, spacing: 2) {
                    Text("loudest \(loud.window == .day ? "by day" : loud.window == .night ? "at night" : "early morning")")
                        .font(.subheadline.weight(.semibold))
                    Text("at your window, like \(Loudness.anchor(loud.db))")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            .accessibilityElement(children: .combine)
            Text(SourceWords.fact(ingredient))
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                if ingredient.weightedUp { Pill(text: "matters to you") }
                if ingredient.temporary { Pill(text: "temporary") }
            }
            if ingredient.weightedUp {
                Text("Counts extra in your verdict because you said it gets to you.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            if ingredient.temporary {
                Text("Temporary: permits expire and complaints fade.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }

    private var windows: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionLabel(text: "By time of day")
            VStack(spacing: 0) {
                ForEach(Window.allCases, id: \.self) { w in
                    let level = ingredient.levels[w] ?? 0
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(w.label).font(.body.weight(.semibold))
                            Text(w.hours).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer(minLength: 8)
                        Text("\(Int(level.rounded())) dB").font(.body.weight(.semibold)).monospacedDigit()
                    }
                    .padding(.vertical, 12)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(w.label), \(w.hours): about \(Int(level.rounded())) decibels")
                    if w != .day { Divider() }
                }
            }
            .padding(.horizontal, 16)
            .background(Theme.cardShape.fill(Theme.card))
        }
    }

    private var evidence: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionLabel(text: "Check it yourself")
            Text("Tick each line as you confirm it on the street.")
                .font(.subheadline).foregroundStyle(.secondary)
            VStack(spacing: 0) {
                ForEach(Array(ingredient.evidence.enumerated()), id: \.offset) { i, line in
                    let on = checked.contains(i)
                    Button {
                        if on { checked.remove(i) } else { checked.insert(i) }
                    } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Image(systemName: on ? "checkmark.square.fill" : "square")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(on ? Color.primary : Color(.tertiaryLabel))
                            Text(line)
                                .font(.body)
                                .foregroundStyle(on ? .secondary : .primary)
                                .strikethrough(false)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 0)
                        }
                        .padding(.vertical, 12)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(line)
                    .accessibilityValue(on ? "checked" : "not checked")
                    .accessibilityAddTraits(.isButton)
                    if i < ingredient.evidence.count - 1 { Divider() }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
            .background(Theme.cardShape.fill(Theme.card))
        }
    }

    private var position: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionLabel(text: "Your position")
            VStack(alignment: .leading, spacing: 6) {
                Text(positionWords)
                    .font(.body.weight(.semibold))
                Text("Modelled at \(String(format: "%.0f", ingredient.rawLevel)) dB outside before your floor and side.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .card()
        }
    }

    /// "Floor 4 at the front: -3 dB".
    private var positionWords: String {
        let floor = unit.floor.map { $0 == 1 ? "Ground floor" : "Floor \($0)" } ?? "Floor unknown"
        let side: String
        switch unit.position {
        case .front: side = "at the front"
        case .rear: side = "at the back"
        case .unknown: side = "side unknown"
        }
        return "\(floor) \(side): \(Format.db(ingredient.positionDb))"
    }
}

#Preview("Street") {
    let store = NoiseStore.preview()
    NavigationStack {
        IngredientDetailView(ingredient: store.result!.ingredients[0], unit: store.unit, profile: store.profile)
    }
}

#Preview("Construction") {
    let store = NoiseStore.preview()
    NavigationStack {
        IngredientDetailView(ingredient: store.result!.ingredients.last!, unit: store.unit, profile: store.profile)
    }
}
