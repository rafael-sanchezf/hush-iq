import SwiftUI
import NoiseKit

// The Score screen's language: a five-step verdict against Manhattan, the time-of-day verdicts with the
// estimated decibels beside them, and the sources in plain words. The percentile and the decibels are one
// tap away in "How it's worked out". The meter is the screen's one accent.

/// "Typical for Manhattan", the five-step meter, and who it is for.
struct VerdictCard: View {
    let rank: Baseline.Rank
    let addressLine: String
    let forWhom: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(addressLine)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text("\(rank.verdict.label) for Manhattan")
                .font(.system(.largeTitle, design: .rounded).weight(.bold))
                .foregroundStyle(.primary)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
                .fixedSize(horizontal: false, vertical: true)
            VerdictMeter(verdict: rank.verdict)
            Text("\(forWhom) Quieter than \(Int(rank.quieterThan.rounded()))% of Manhattan apartments.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 4) {
                Text("How it's worked out")
                Image(systemName: "chevron.right").font(.caption.weight(.semibold))
            }
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.primary)
            .padding(.top, 2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .multilineTextAlignment(.leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(rank.verdict.label) for Manhattan. \(forWhom) Quieter than \(Int(rank.quieterThan.rounded())) percent of Manhattan apartments.")
        .accessibilityHint("Shows how it's worked out")
    }
}

/// Five segments, Very loud to Very quiet; the one that applies is the accent.
struct VerdictMeter: View {
    let verdict: Verdict

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 5) {
                ForEach(Verdict.allCases, id: \.self) { v in
                    Capsule()
                        .fill(v == verdict ? Theme.accent : Theme.track)
                        .frame(height: 10)
                }
            }
            HStack {
                Text("Very loud")
                Spacer()
                Text("Very quiet")
            }
            .font(.caption)
            .foregroundStyle(.tertiary)
        }
        .accessibilityHidden(true)
    }
}

/// Night, early, day: the verdict word and the estimated decibels.
struct WindowRow: View {
    let rank: Baseline.WindowRank

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(rank.window.label).font(.body.weight(.semibold))
                Text(rank.window.hours).font(.caption).foregroundStyle(.secondary)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(rank.verdict.label).font(.body.weight(.semibold))
                Text("\(Int(rank.levelDb.rounded())) dB").font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(rank.window.label), \(rank.window.hours): \(rank.verdict.label), about \(Int(rank.levelDb.rounded())) decibels")
    }
}

/// One source in plain words: what it is, the fact to check at a viewing, its loudest decibels.
struct SourceRow: View {
    let ingredient: Ingredient

    var body: some View {
        let loud = ingredient.loudestWindow
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(SourceWords.title(ingredient)).font(.body.weight(.semibold)).foregroundStyle(.primary)
                Text(SourceWords.fact(ingredient))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if ingredient.weightedUp || ingredient.temporary {
                    HStack(spacing: 6) {
                        if ingredient.weightedUp { Pill(text: "matters to you") }
                        if ingredient.temporary { Pill(text: "temporary") }
                    }
                    .padding(.top, 4)
                }
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text("\(Int(loud.db.rounded())) dB").font(.body.weight(.semibold)).monospacedDigit().foregroundStyle(.primary)
                Text(loud.window == .day ? "by day" : loud.window == .night ? "at night" : "early").font(.caption).foregroundStyle(.secondary)
            }
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.tertiary)
                .padding(.top, 3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .multilineTextAlignment(.leading)
        .card()
    }
}

extension Ingredient {
    /// The window with the highest level. Night wins ties, since that is the one renters ask about.
    var loudestWindow: (window: Window, db: Double) {
        var best: (Window, Double) = (.night, levels[.night] ?? 0)
        for w in [Window.early, .day] {
            let l = levels[w] ?? 0
            if l > best.1 { best = (w, l) }
        }
        return best
    }

    var accessibilitySummary: String {
        let w = loudestWindow
        var s = "\(SourceWords.title(self)): about \(Int(w.db.rounded())) decibels, loudest \(w.window == .day ? "by day" : w.window == .night ? "at night" : "early morning"). \(SourceWords.fact(self))"
        if weightedUp { s += " Matters to you." }
        if temporary { s += " Temporary." }
        return s
    }
}

/// The evidence lines, turned into the words a renter reads. Falls back to the first evidence line.
enum SourceWords {
    static func title(_ ing: Ingredient) -> String {
        switch ing.name {
        case "street":
            if let first = ing.evidence.first, !first.hasPrefix("no road"), let colon = first.firstIndex(of: ":") {
                return "\(pretty(String(first[..<colon]))) traffic"
            }
            return "Street traffic"
        case "nightlife": return "Restaurants and bars"
        case "building": return "Neighbors"
        case "sirens": return "Sirens"
        case "construction": return "Construction"
        default: return ing.label
        }
    }

    static func fact(_ ing: Ingredient) -> String {
        let ev = ing.evidence
        switch ing.name {
        case "street":
            guard let first = ev.first, !first.hasPrefix("no road") else { return "No busy road within 60 m." }
            var parts: [String] = []
            if first.contains("bus or truck route") {
                parts.append("Bus and truck route")
            } else if let lanes = match(first, #"(\d+) travel lane"#) {
                parts.append("\(lanes) lane\(lanes == "1" ? "" : "s")")
            }
            if let d = match(first, #"(\d+) m away"#) { parts.append("\(d) m away") }
            if ev.contains(where: { $0.contains("subway") }) { parts.append("elevated subway nearby") }
            return parts.isEmpty ? first : parts.joined(separator: ", ") + "."
        case "nightlife":
            if let first = ev.first, let n = match(first, #"^(\d+) licensed venues"#) {
                return n == "1" ? "1 licensed bar or restaurant within a block." : "\(n) licensed bars and restaurants within a block."
            }
            return "No licensed bar or restaurant within a block."
        case "building":
            if let line = ev.first(where: { $0.contains("residential noise complaints") }),
               let n = match(line, #"^(\d+) residential"#),
               let x = match(line, #"\((\d+(?:\.\d+)?)x after"#), let r = Double(x) {
                if n == "0" { return "No noise complaints at this building in 2 years." }
                let rel = r < 0.8 ? "below average" : r <= 1.25 ? "about average" : "above average"
                return "\(n) complaint\(n == "1" ? "" : "s") at this building in 2 years, \(rel) for its size."
            }
            return ev.first ?? ""
        case "sirens":
            let near = ev.dropFirst().prefix(2).compactMap { line -> String? in
                line.split(separator: "(").first.map { pretty(String($0).trimmingCharacters(in: .whitespaces)) }
            }
            return near.isEmpty ? "No hospital, firehouse or police station within 600 m." : near.joined(separator: " and ") + " nearby."
        case "construction":
            if let first = ev.first, let n = match(first, #"^(\d+) construction noise complaints"#) {
                return "\(n) complaint\(n == "1" ? "" : "s") within a block in 2 years."
            }
            if ev.contains(where: { $0.contains("loud-work permits") && !$0.hasPrefix("no ") }) {
                return "Active loud-work permits on the block."
            }
            return "None nearby."
        default:
            return ev.first ?? ""
        }
    }

    /// "MOUNT SINAI MORNINGSIDE" to "Mount Sinai Morningside", "NYPD 28TH PRECINCT" to "NYPD 28th Precinct".
    static func pretty(_ s: String) -> String {
        var out = s.capitalized
        for (a, b) in [("Nypd", "NYPD"), ("Ems", "EMS"), ("Fdny", "FDNY")] { out = out.replacingOccurrences(of: a, with: b) }
        if let re = try? NSRegularExpression(pattern: #"(\d+)(St|Nd|Rd|Th)\b"#) {
            let ns = out as NSString
            var result = out
            for m in re.matches(in: out, range: NSRange(location: 0, length: ns.length)).reversed() {
                result = (result as NSString).replacingCharacters(in: m.range(at: 2), with: ns.substring(with: m.range(at: 2)).lowercased())
            }
            out = result
        }
        return out
    }

    static func match(_ s: String, _ pattern: String) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern),
              let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)), m.numberOfRanges > 1,
              let r = Range(m.range(at: 1), in: s) else { return nil }
        return String(s[r])
    }
}

/// "How it's worked out": the exact percentile, the decibels per time of day against Manhattan, and how
/// to read a decibel number.
struct RankDetailView: View {
    let rank: Baseline.Rank
    let windows: [Baseline.WindowRank]
    let forWhom: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("\(rank.verdict.label) for Manhattan")
                        .font(.system(.title, design: .rounded).weight(.bold))
                    VerdictMeter(verdict: rank.verdict)
                    Text("Quieter than \(String(format: "%.0f", rank.quieterThan))% of Manhattan apartments. \(forWhom)")
                        .font(.body.weight(.semibold))
                    Text("\(rank.n) apartments were drawn from every Manhattan community district, weighted by size, and scored with the same public data as yours. Each was re-scored for your floor, side and answers, then ranked. Each step of the meter is one fifth of Manhattan.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .fixedSize(horizontal: false, vertical: true)

                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(text: "Decibels by time of day")
                    VStack(spacing: 0) {
                        ForEach(windows, id: \.window) { w in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack(alignment: .firstTextBaseline) {
                                    Text(w.window.label).font(.body.weight(.semibold))
                                    Text(w.window.hours).font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                    Text(w.verdict.label).font(.body.weight(.semibold))
                                }
                                Text("Yours about \(Int(w.levelDb.rounded())) dB, like \(Loudness.anchor(w.levelDb)). Manhattan typical \(Int(w.medianDb.rounded())) dB, middle half \(Int(w.p25Db.rounded())) to \(Int(w.p75Db.rounded())) dB. Quieter than \(Int(w.quieterThan.rounded()))%.")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .padding(.vertical, 12)
                            .accessibilityElement(children: .combine)
                            if w.window != windows.last?.window { Divider() }
                        }
                    }
                    .padding(.horizontal, 16)
                    .background(Theme.cardShape.fill(Theme.card))
                    Text("These are sound levels at your window, the same for anyone in this apartment. Your answers change the verdict above, not these numbers.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 14) {
                    SectionLabel(text: "Reading decibels")
                    VStack(spacing: 10) {
                        ForEach(Loudness.anchors, id: \.db) { a in
                            HStack {
                                Text("\(a.db) dB").font(.body.weight(.semibold)).monospacedDigit().frame(width: 64, alignment: .leading)
                                Text(a.sound.prefix(1).uppercased() + a.sound.dropFirst()).font(.body)
                                Spacer()
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                    .card()
                    Text("3 dB more is barely noticeable. 10 dB more sounds about twice as loud.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Text("Estimated from NYC open data, not measured. Manhattan sample pulled \(rank.asOf).")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, Theme.gutter)
            .padding(.top, 8)
            .padding(.bottom, 40)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemBackground))
        .navigationTitle("How it's worked out")
        .navigationBarTitleDisplayMode(.inline)
    }
}
