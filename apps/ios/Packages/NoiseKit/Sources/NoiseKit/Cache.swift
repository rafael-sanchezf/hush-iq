import CryptoKit
import Foundation

/// Disk cache for upstream pulls, a port of noise_score/cache.py. [T4]
///
/// One JSON file per request under `Application Support/NoiseScore/cache/`, named by the request name
/// and a SHA-256 of the request, each carrying `fetchedAt`. The TTL is the caller's: `get` with a `maxAge`
/// returns nil past it, `get` without one returns whatever is there (the stale fallback when the network fails).
public struct NoiseCache: Sendable {
    public let directory: URL

    /// `Application Support/NoiseScore/cache/` in the user domain (the app sandbox on iOS).
    public static let `default` = NoiseCache(directory: defaultDirectory())

    public init(directory: URL) {
        self.directory = directory
    }

    public static func defaultDirectory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent("NoiseScore", isDirectory: true).appendingPathComponent("cache", isDirectory: true)
    }

    struct Envelope<T: Codable>: Codable {
        var fetchedAt: Date
        var name: String
        var request: String
        var value: T
    }

    /// Hex SHA-256 of the request description, so a key never carries an address into a file name.
    public static func key(_ parts: [String]) -> String {
        let raw = parts.joined(separator: "\u{1f}")
        return SHA256.hash(data: Data(raw.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func fileURL(name: String, key: String) -> URL {
        directory.appendingPathComponent("\(name)-\(key).json")
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    /// The cached value, or nil when there is none, it does not decode, or it is older than `maxAge` seconds.
    public func get<T: Codable>(_ name: String, key: String, as type: T.Type = T.self, maxAge: TimeInterval? = nil,
                                now: Date = Date()) -> (value: T, fetchedAt: Date)? {
        let url = fileURL(name: name, key: key)
        guard let data = try? Data(contentsOf: url),
              let env = try? Self.decoder.decode(Envelope<T>.self, from: data) else { return nil }
        if let maxAge, now.timeIntervalSince(env.fetchedAt) > maxAge { return nil }
        return (env.value, env.fetchedAt)
    }

    /// Writes the value. Failures are swallowed: the cache is an accelerator, never a dependency.
    @discardableResult
    public func put<T: Codable>(_ name: String, key: String, request: String = "", value: T, fetchedAt: Date = Date()) -> Bool {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let data = try Self.encoder.encode(Envelope(fetchedAt: fetchedAt, name: name, request: request, value: value))
            try data.write(to: fileURL(name: name, key: key), options: .atomic)
            return true
        } catch {
            return false
        }
    }

    public func remove(_ name: String, key: String) {
        try? FileManager.default.removeItem(at: fileURL(name: name, key: key))
    }

    /// Deletes every cached file.
    public func clear() {
        try? FileManager.default.removeItem(at: directory)
    }

    /// Bytes on disk, for a settings row.
    public var sizeOnDisk: Int {
        let files = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.fileSizeKey])) ?? []
        return files.reduce(0) { $0 + ((try? $1.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0) }
    }
}
