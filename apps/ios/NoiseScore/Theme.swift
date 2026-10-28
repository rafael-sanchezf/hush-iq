import SwiftUI
import NoiseKit

/// Foundation also has a `Unit` (NSUnit); in this module the bare name means the apartment.
typealias Unit = NoiseKit.Unit

/// The visual signature, carried over from the HW2 app: one corner radius, one gutter, rounded
/// bold numerals, greyscale first. Colour is spent on exactly one element per screen (the score
/// ring, the matching pins, the status pill or the number, the selected survey option); everything
/// else carries hierarchy through size, weight, grey and spacing.
enum Theme {
    /// Corner radius for every card and tile.
    static let corner: CGFloat = 22
    /// Horizontal margin on every screen.
    static let gutter: CGFloat = 20
    /// The one accent, from Assets.xcassets/AccentColor.
    static let accent = Color("AccentColor")
    /// Grey track behind every bar and ring.
    static let track = Color(.tertiarySystemFill)
    /// Card fill.
    static let card = Color(.secondarySystemBackground)

    static let cardShape = RoundedRectangle(cornerRadius: corner, style: .continuous)
}

// MARK: - Shared pieces

/// A horizontal 0 to 100 bar. Grey by default; the fill colour is the caller's choice so a screen
/// can keep its one accent for something else.
struct ScoreBar: View {
    let value: Int
    var fill: Color = Color(.label)
    var height: CGFloat = 8

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.track)
                Capsule().fill(fill)
                    .frame(width: max(height, geo.size.width * CGFloat(min(max(value, 0), 100)) / 100))
            }
        }
        .frame(height: height)
        .accessibilityHidden(true)
    }
}

/// A small rounded label: "weighted up", "temporary", a status. Grey unless the screen spends its
/// accent on it.
struct Pill: View {
    let text: String
    var accent = false

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(accent ? Color.white : Color(.secondaryLabel))
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .background(Capsule().fill(accent ? Theme.accent : Theme.track))
    }
}

/// Section label in the HW2 style: small, grey, uppercase.
struct SectionLabel: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .textCase(.uppercase)
            .kerning(1.2)
            .foregroundStyle(.secondary)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A big rounded numeral, the signature of every screen.
struct BigNumber: View {
    let value: Int
    var style: Font.TextStyle = .largeTitle
    var color: Color = .primary
    var body: some View {
        Text("\(value)")
            .font(.system(style, design: .rounded, weight: .bold))
            .foregroundStyle(color)
            .monospacedDigit()
    }
}

/// A slight press-down so cards feel tappable. Same as HW2.
struct PressableCardStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.92 : 1)
            .animation(.spring(response: 0.28, dampingFraction: 0.75), value: configuration.isPressed)
    }
}

/// Full-width primary button in greyscale: white on label-black. Never the accent.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .foregroundStyle(Color(.systemBackground))
            .background(Theme.cardShape.fill(Color(.label).opacity(isEnabled ? 1 : 0.35)))
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.spring(response: 0.28, dampingFraction: 0.75), value: configuration.isPressed)
    }
}

extension View {
    /// The card treatment used on every screen.
    func card() -> some View {
        self
            .padding(16)
            .background(Theme.cardShape.fill(Theme.card))
    }
}

// MARK: - Formatting

enum Format {
    static let relative: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .full
        return f
    }()

    /// "3 minutes ago", "yesterday".
    static func relative(_ date: Date, from now: Date = Date()) -> String {
        relative.localizedString(for: date, relativeTo: now)
    }

    /// 311 gives local New York time with no zone, e.g. "2026-10-21T00:35:53.000".
    static let socrata: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSS"
        return f
    }()
    static let socrataShort: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()
    static let dayOnly: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func date(fromSocrata s: String?) -> Date? {
        guard let s else { return nil }
        return socrata.date(from: s) ?? socrataShort.date(from: String(s.prefix(19))) ?? dayOnly.date(from: String(s.prefix(10)))
    }

    static func dateTime(_ d: Date) -> String {
        d.formatted(date: .abbreviated, time: .shortened)
    }

    static func day(_ d: Date) -> String {
        d.formatted(date: .abbreviated, time: .omitted)
    }

    static func metres(_ m: Double) -> String {
        m < 1000 ? "\(Int(m.rounded())) m" : String(format: "%.1f km", m / 1000)
    }

    static func db(_ v: Double) -> String {
        let s = v == v.rounded() ? "\(Int(v))" : String(format: "%.1f", v)
        return (v > 0 ? "+" : "") + s + " dB"
    }
}

extension GeoAddress {
    /// The GeoSearch label, made readable: "2900 B'WAY, New York, NY, USA" reads "2900 Broadway, New York, NY".
    var displayLabel: String? {
        guard var s = label else { return nil }
        s = s.replacingOccurrences(of: "B'WAY", with: "Broadway")
        if s.hasSuffix(", USA") { s.removeLast(5) }
        return s
    }
}
