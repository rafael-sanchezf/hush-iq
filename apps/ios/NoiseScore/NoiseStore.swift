import Foundation
import Network
import Observation
import NoiseKit

/// The one model object the screens read. Holds the renter's answers, the last pull, the score and
/// the recent complaints; pulls both feeds concurrently; re-scores without the network when answers
/// change; watches the network path so the screens can say "offline" before a request fails.
@MainActor @Observable
final class NoiseStore {
    enum Phase: Equatable {
        case idle, loading, ready
        case failed(String)
    }

    // MARK: Answers
    var address: GeoAddress?
    var unit = Unit()
    var profile = Profile()
    /// The survey has been completed once (or skipped by launch argument).
    var hasAnswers = false

    // MARK: Data
    var pulled: Pulled?
    var result: ScoreResult?
    var recent: PulledComplaints?
    var phase: Phase = .idle
    var isOffline = false
    /// The no-network, no-cache fallback is on: everything shown is the bundled 2900 Broadway sample.
    var usingSample = false

    static let radiusM = 500.0
    static let days = 30

    @ObservationIgnored let source: any NoiseDataSource
    @ObservationIgnored let fallback: any NoiseDataSource
    /// The source is the bundled sample by choice (previews, `-NoiseScoreUseFixture`), not a fallback.
    @ObservationIgnored let replaysSample: Bool
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let monitor = NWPathMonitor()

    init(source: any NoiseDataSource, fallback: any NoiseDataSource, defaults: UserDefaults = .standard, replaysSample: Bool = false) {
        self.source = source
        self.fallback = fallback
        self.defaults = defaults
        self.replaysSample = replaysSample
        loadAnswers()
        startMonitor()
    }

    /// Set by `-NoiseScoreSimulateOffline YES`: every network call fails as if the phone had no signal,
    /// so the offline banner, the cache and the bundled-sample fallback can be shown on a connected Mac.
    var forceOffline = false

    /// The store the app runs. `-NoiseScoreUseFixture YES` replays the bundled sample instead of
    /// NYC Open Data (screenshots, demos); `-NoiseScoreSkipSurvey YES` seeds the sample answers so
    /// the Score tab is the first screen.
    static func forApp() -> NoiseStore {
        let defaults = UserDefaults.standard
        let useFixture = defaults.bool(forKey: "NoiseScoreUseFixture")
        let simulateOffline = defaults.bool(forKey: "NoiseScoreSimulateOffline")
        let source: any NoiseDataSource
        if useFixture {
            source = FixtureDataSource()
        } else if simulateOffline {
            let c = URLSessionConfiguration.ephemeral
            c.protocolClasses = [NoSignalProtocol.self]
            source = LiveDataSource(session: URLSession(configuration: c))
        } else {
            source = LiveDataSource()
        }
        let store = NoiseStore(source: source, fallback: FixtureDataSource(), defaults: defaults, replaysSample: useFixture)
        store.forceOffline = simulateOffline
        if defaults.bool(forKey: "NoiseScoreSkipSurvey"), !store.hasAnswers {
            store.seedSampleAnswers()
        }
        return store
    }

    /// Previews: the sample, answered, scored, no network.
    static func preview(answered: Bool = true, offline: Bool = false, sample: Bool = false) -> NoiseStore {
        let suite = UserDefaults(suiteName: "preview.\(UUID().uuidString)") ?? .standard
        let store = NoiseStore(source: FixtureDataSource(), fallback: FixtureDataSource(), defaults: suite, replaysSample: true)
        if answered {
            store.seedSampleAnswers()
            store.pulled = Pulled(inputs: FixtureDataSource.sampleInputs, fetchedAt: Date().addingTimeInterval(-180), fromCache: offline)
            store.recent = PulledComplaints(complaints: FixtureDataSource.sampleComplaints, fetchedAt: Date().addingTimeInterval(-180), fromCache: offline)
            store.rescore()
            store.phase = .ready
            store.isOffline = offline
            store.usingSample = sample
        }
        return store
    }

    // MARK: - Derived

    /// The address the shown data is about: the renter's, or 2900 Broadway while the sample is on.
    var shownAddress: GeoAddress? { usingSample ? pulled?.inputs.address : address }

    /// Recent complaints with coordinates, nearest first.
    var recentSorted: [ComplaintRow] {
        guard let rows = recent?.complaints, let a = shownAddress else { return [] }
        return rows
            .filter { $0.coordinate != nil }
            .sorted { ($0.distanceM(from: a) ?? .infinity) < ($1.distanceM(from: a) ?? .infinity) }
    }

    /// The offline or stale banner, or nil when the data is live.
    var bannerText: String? {
        if usingSample { return "Offline. Showing a saved sample for 2900 Broadway." }
        guard let pulled else { return isOffline ? "Offline." : nil }
        if isOffline { return "Offline. Showing data from \(Format.day(pulled.fetchedAt))." }
        if pulled.fromCache, !replaysSample { return "NYC Open Data did not answer. Showing data from \(Format.day(pulled.fetchedAt))." }
        return nil
    }

    /// "Data pulled 3 minutes ago" or "From Oct 21, offline".
    var pulledCaption: String {
        guard let pulled else { return "No data yet" }
        if usingSample || replaysSample { return "Saved sample from \(Format.day(pulled.fetchedAt))" }
        if isOffline || pulled.fromCache { return "From \(Format.day(pulled.fetchedAt)), offline" }
        return "Data pulled \(Format.relative(pulled.fetchedAt))"
    }

    // MARK: - Pull and score

    func refresh() async {
        guard let address else { phase = .failed("Pick an address first."); return }
        phase = .loading
        do {
            async let p = source.pullAll(address: address, allowCache: true)
            async let r = source.recentComplaints(lat: address.lat, lng: address.lng, radiusM: Self.radiusM, days: Self.days, allowCache: true)
            let (pulled, recent) = try await (p, r)
            self.pulled = pulled
            self.recent = recent
            usingSample = false
            rescore()
            phase = .ready
        } catch {
            await recover(from: error, address: address)
        }
    }

    /// The network failed: the last cache for this address, else (offline) the bundled sample, else
    /// a readable error with Retry. Never an empty screen.
    private func recover(from error: Error, address: GeoAddress) async {
        if let cached = source.cached(address: address) {
            pulled = cached
            if let r = try? await source.recentComplaints(lat: address.lat, lng: address.lng, radiusM: Self.radiusM, days: Self.days, allowCache: true) {
                recent = r
            } else if recent == nil {
                recent = PulledComplaints(complaints: [], fetchedAt: cached.fetchedAt, fromCache: true)
            }
            usingSample = false
            rescore()
            phase = .ready
            return
        }
        if isOffline || Self.isOffline(error) {
            let sample = FixtureDataSource.sampleAddress
            if let p = try? await fallback.pullAll(address: sample, allowCache: true),
               let r = try? await fallback.recentComplaints(lat: sample.lat, lng: sample.lng, radiusM: Self.radiusM, days: Self.days, allowCache: true) {
                pulled = p
                recent = r
                usingSample = true
                rescore()
                phase = .ready
                return
            }
        }
        phase = .failed(error.localizedDescription)
    }

    /// Re-run the model on the last pull. No network.
    func rescore() {
        guard let inputs = pulled?.inputs else { return }
        result = Scorer.score(inputs, unit: unit, profile: profile)
    }

    private static func isOffline(_ error: Error) -> Bool {
        if case NoiseError.offline = error { return true }
        if let e = error as? URLError {
            return [.notConnectedToInternet, .networkConnectionLost, .cannotFindHost, .cannotConnectToHost, .timedOut].contains(e.code)
        }
        return false
    }

    // MARK: - Answers

    /// Called by the survey. A new address pulls again; the same address only re-scores.
    func saveAnswers(address: GeoAddress, unit: Unit, profile: Profile) async {
        let moved = self.address?.id != address.id || pulled == nil
        self.address = address
        self.unit = unit
        self.profile = profile
        hasAnswers = true
        persistAnswers()
        if moved || usingSample {
            await refresh()
        } else {
            rescore()
        }
    }

    private func seedSampleAnswers() {
        address = FixtureDataSource.sampleAddress
        unit = FixtureDataSource.sampleUnit
        profile = FixtureDataSource.sampleProfile
        hasAnswers = true
        persistAnswers()
    }

    private enum Key {
        static let profile = "answers.profile", unit = "answers.unit", address = "answers.address", done = "answers.done"
    }

    private func persistAnswers() {
        let enc = JSONEncoder()
        defaults.set(try? enc.encode(profile), forKey: Key.profile)
        defaults.set(try? enc.encode(unit), forKey: Key.unit)
        defaults.set(try? enc.encode(address), forKey: Key.address)
        defaults.set(hasAnswers, forKey: Key.done)
    }

    private func loadAnswers() {
        let dec = JSONDecoder()
        if let d = defaults.data(forKey: Key.profile), let p = try? dec.decode(Profile.self, from: d) { profile = p }
        if let d = defaults.data(forKey: Key.unit), let u = try? dec.decode(Unit.self, from: d) { unit = u }
        if let d = defaults.data(forKey: Key.address), let a = try? dec.decode(GeoAddress.self, from: d) { address = a }
        hasAnswers = defaults.bool(forKey: Key.done) && address != nil
    }

    // MARK: - Network

    private func startMonitor() {
        monitor.pathUpdateHandler = { [weak self] path in
            let offline = path.status != .satisfied
            Task { @MainActor [weak self] in self?.isOffline = offline || (self?.forceOffline ?? false) }
        }
        monitor.start(queue: DispatchQueue(label: "NoiseScore.path"))
    }
}

/// Fails every request the way iOS does with no signal, so the live source takes its real offline path
/// (cache, then the bundled sample). Only used with the `-NoiseScoreSimulateOffline YES` launch argument.
final class NoSignalProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)) }
    override func stopLoading() {}
}
