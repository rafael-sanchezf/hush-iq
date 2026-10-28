import SwiftUI
import NoiseKit

/// Welcome and survey: three steps, one question each, a progress line on top and Continue at the
/// bottom. Shown on first launch and from the Score toolbar as "Edit answers". The accent is spent
/// on the selected option and nothing else.
struct SurveyView: View {
    let store: NoiseStore
    var onDone: () -> Void = {}

    @State private var step = 0
    @State private var sleep: Sleep
    @State private var bothers: Set<Bother>
    @State private var wfh: Bool
    @State private var addressText: String
    @State private var picked: GeoAddress?
    @State private var suggestions: [GeoAddress] = []
    @State private var floor: Int
    @State private var floorUnknown: Bool
    @State private var position: Position
    @State private var locating = false
    @State private var addressNote: String?
    @State private var saving = false
    @FocusState private var addressFocused: Bool

    private static let columbia = "2900 Broadway, New York"

    init(store: NoiseStore, onDone: @escaping () -> Void = {}) {
        self.store = store
        self.onDone = onDone
        _sleep = State(initialValue: store.profile.sleep)
        _bothers = State(initialValue: Set(store.profile.bothers))
        _wfh = State(initialValue: store.profile.wfh)
        _picked = State(initialValue: store.address)
        _addressText = State(initialValue: store.address?.displayLabel ?? "")
        _floor = State(initialValue: store.unit.floor ?? 4)
        _floorUnknown = State(initialValue: store.unit.floor == nil)
        _position = State(initialValue: store.unit.position)
    }

    var body: some View {
        VStack(spacing: 0) {
            progress
                .padding(.horizontal, Theme.gutter)
                .padding(.top, 16)
                .padding(.bottom, 8)

            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    switch step {
                    case 0: sleepStep
                    case 1: bothersStep
                    default: placeStep
                    }
                }
                .padding(.horizontal, Theme.gutter)
                .padding(.top, 16)
                .padding(.bottom, 24)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .scrollDismissesKeyboard(.interactively)

            footer
                .padding(.horizontal, Theme.gutter)
                .padding(.vertical, 12)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
                .background(.bar)
        }
        .background(Color(.systemBackground))
        .animation(.easeInOut(duration: 0.2), value: step)
    }

    // MARK: Progress and footer

    private var progress: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                ForEach(0..<3, id: \.self) { i in
                    Capsule()
                        .fill(i <= step ? Color(.label) : Theme.track)
                        .frame(height: 4)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Step \(step + 1) of 3")
            Text(step == 0 ? "Welcome to Hush IQ" : "Step \(step + 1) of 3")
                .font(.footnote.weight(.semibold))
                .textCase(.uppercase)
                .kerning(1.2)
                .foregroundStyle(.secondary)
        }
    }

    private var footer: some View {
        HStack(spacing: 12) {
            if step > 0 {
                Button("Back") { step -= 1 }
                    .font(.headline)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .accessibilityLabel("Back to the previous question")
            }
            Button(step == 2 ? (saving ? "Scoring…" : "See my score") : "Continue") {
                if step < 2 { step += 1 } else { finish() }
            }
            .buttonStyle(PrimaryButtonStyle())
            .disabled(step == 2 && (picked == nil || saving))
            .accessibilityHint(step == 2 && picked == nil ? "Pick an address first" : "")
        }
    }

    private func finish() {
        guard let picked, !saving else { return }
        saving = true
        let unit = Unit(floor: floorUnknown ? nil : floor, position: position)
        let profile = Profile(sleep: sleep, wfh: wfh, bothers: Bother.allCases.filter { bothers.contains($0) })
        Task {
            await store.saveAnswers(address: picked, unit: unit, profile: profile)
            saving = false
            onDone()
        }
    }

    // MARK: Step 1

    private var sleepStep: some View {
        Group {
            question("How do you sleep?", sub: "Night noise counts more for a light sleeper.")
            VStack(spacing: 12) {
                option("Light sleeper", "A car horn at 2 am wakes me.", selected: sleep == .light) { sleep = .light }
                option("Normal sleeper", "Steady noise is fine, sudden noise is not.", selected: sleep == .normal) { sleep = .normal }
                option("Heavy sleeper", "I sleep through almost anything.", selected: sleep == .heavy) { sleep = .heavy }
            }
        }
    }

    // MARK: Step 2

    private var bothersStep: some View {
        Group {
            question("What gets to you?", sub: "Pick any. These count extra, and the map lights them up.")
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 10)], spacing: 10) {
                chip("Neighbors", .neighbors)
                chip("Nightlife and people", .people)
                chip("Traffic", .traffic)
                chip("Sirens", .sirens)
                chip("Construction", .construction)
            }
            Toggle(isOn: $wfh) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("I work from home most days").font(.body.weight(.semibold))
                    Text("Daytime noise counts more.").font(.subheadline).foregroundStyle(.secondary)
                }
            }
            .tint(Theme.accent)
            .card()
        }
    }

    private func chip(_ title: String, _ bother: Bother) -> some View {
        let on = bothers.contains(bother)
        return Button {
            if on { bothers.remove(bother) } else { bothers.insert(bother) }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: on ? "checkmark.circle.fill" : "circle")
                    .font(.body.weight(.semibold))
                Text(title).font(.body.weight(.semibold))
                Spacer(minLength: 0)
            }
            .foregroundStyle(on ? Color.white : Color.primary)
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(on ? Theme.accent : Theme.card))
        }
        .buttonStyle(PressableCardStyle())
        .accessibilityLabel(title)
        .accessibilityAddTraits(on ? [.isSelected] : [])
    }

    // MARK: Step 3

    private var placeStep: some View {
        Group {
            question("Your place", sub: "Any NYC address. The floor and the side change the score.")

            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                    TextField("Street address", text: $addressText)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .focused($addressFocused)
                        .submitLabel(.search)
                        .accessibilityLabel("Street address")
                    if !addressText.isEmpty {
                        Button {
                            addressText = ""; picked = nil; suggestions = []
                        } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                        }
                        .accessibilityLabel("Clear address")
                    }
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Theme.card))

                if let picked, picked.label == addressText {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.accent)
                        Text(picked.displayLabel ?? "Address matched").font(.subheadline.weight(.semibold))
                        Spacer()
                    }
                    .padding(.horizontal, 4)
                    .accessibilityElement(children: .combine)
                } else if !suggestions.isEmpty {
                    VStack(spacing: 0) {
                        ForEach(suggestions) { s in
                            Button { choose(s) } label: {
                                HStack {
                                    Text(s.displayLabel ?? "\(s.lat), \(s.lng)")
                                        .font(.body)
                                        .foregroundStyle(.primary)
                                        .multilineTextAlignment(.leading)
                                    Spacer()
                                }
                                .padding(.vertical, 12)
                                .padding(.horizontal, 4)
                                .contentShape(Rectangle())
                            }
                            .accessibilityLabel("Use \(s.displayLabel ?? "this address")")
                            Divider()
                        }
                    }
                }

                if let addressNote {
                    Text(addressNote).font(.footnote).foregroundStyle(.secondary)
                }

                HStack(spacing: 10) {
                    secondary("Use Columbia", symbol: "building.columns") { useColumbia() }
                    secondary(locating ? "Locating…" : "Use my location", symbol: "location") { useMyLocation() }
                        .disabled(locating)
                }
            }
            .task(id: addressText) { await suggest() }

            VStack(alignment: .leading, spacing: 12) {
                SectionLabel(text: "Floor")
                HStack(spacing: 12) {
                    Stepper(value: $floor, in: 1...60) {
                        HStack(spacing: 8) {
                            BigNumber(value: floor, style: .title2, color: floorUnknown ? Color(.tertiaryLabel) : .primary)
                            Text(floor == 1 ? "ground" : "floor \(floor)")
                                .font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                    .disabled(floorUnknown)
                    .accessibilityLabel("Floor \(floor)")
                }
                .card()
                option("Not sure which floor", nil, selected: floorUnknown, compact: true) { floorUnknown.toggle() }
            }

            VStack(alignment: .leading, spacing: 12) {
                SectionLabel(text: "Your windows face")
                HStack(spacing: 10) {
                    face("Street", .front)
                    face("Courtyard or back", .rear)
                    face("Not sure", .unknown)
                }
            }
        }
    }

    private func face(_ title: String, _ p: Position) -> some View {
        let on = position == p
        return Button { position = p } label: {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .multilineTextAlignment(.center)
                .foregroundStyle(on ? Color.white : Color.primary)
                .frame(maxWidth: .infinity, minHeight: 52)
                .padding(.horizontal, 6)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(on ? Theme.accent : Theme.card))
        }
        .buttonStyle(PressableCardStyle())
        .accessibilityLabel(title)
        .accessibilityAddTraits(on ? [.isSelected] : [])
    }

    private func secondary(_ title: String, symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Theme.card))
        }
        .buttonStyle(PressableCardStyle())
    }

    // MARK: Address lookups

    private func suggest() async {
        if let picked, picked.label == addressText { suggestions = []; return }
        guard addressText.count >= 3 else { suggestions = []; return }
        try? await Task.sleep(for: .milliseconds(300))
        if Task.isCancelled { return }
        do {
            suggestions = try await store.source.suggest(addressText)
            addressNote = suggestions.isEmpty ? "No NYC address matches yet. Keep typing." : nil
        } catch {
            suggestions = []
            addressNote = store.isOffline ? "Offline: address search needs a connection." : error.localizedDescription
        }
    }

    private func choose(_ s: GeoAddress) {
        picked = s
        addressText = s.displayLabel ?? addressText
        suggestions = []
        addressNote = nil
        addressFocused = false
    }

    private func useColumbia() {
        addressFocused = false
        Task {
            addressNote = nil
            if let s = try? await store.source.suggest(Self.columbia).first {
                choose(s)
            } else {
                addressText = Self.columbia
                addressNote = "Could not match 2900 Broadway right now."
            }
        }
    }

    private func useMyLocation() {
        addressFocused = false
        locating = true
        addressNote = nil
        Task {
            defer { locating = false }
            do {
                let label = try await LocationFinder().currentAddressLabel()
                if let s = try await store.source.suggest(label).first {
                    choose(s)
                } else {
                    addressText = label
                    addressNote = "Found \(label) but NYC GeoSearch has no match. Try editing it."
                }
            } catch {
                addressNote = error.localizedDescription
            }
        }
    }

    // MARK: Pieces

    private func question(_ title: String, sub: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(.largeTitle, design: .rounded, weight: .bold))
            Text(sub).font(.body).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private func option(_ title: String, _ sentence: String?, selected: Bool, compact: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(compact ? .subheadline.weight(.semibold) : .title3.weight(.semibold))
                    if let sentence { Text(sentence).font(.subheadline).opacity(0.85) }
                }
                .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .opacity(selected ? 1 : 0.4)
            }
            .foregroundStyle(selected ? Color.white : Color.primary)
            .padding(compact ? 14 : 18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.cardShape.fill(selected ? Theme.accent : Theme.card))
        }
        .buttonStyle(PressableCardStyle())
        .accessibilityLabel(sentence.map { "\(title). \($0)" } ?? title)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

#Preview("First launch") {
    SurveyView(store: NoiseStore.preview(answered: false))
}

#Preview("Edit answers") {
    SurveyView(store: NoiseStore.preview())
}
