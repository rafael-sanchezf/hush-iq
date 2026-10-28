import Foundation
import CoreLocation

/// One-shot "where am I": when-in-use permission, one fix, a street-address label from CLGeocoder.
/// The survey then runs that label through GeoSearch so the match carries a BBL and BIN.
@MainActor
final class LocationFinder: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation, Error>?

    enum Failure: LocalizedError {
        case denied, noFix
        var errorDescription: String? {
            switch self {
            case .denied: return "Location is off for Hush IQ. Type the address instead."
            case .noFix: return "Could not get a location fix. Type the address instead."
            }
        }
    }

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    /// A short address label ("2920 Broadway, New York") for where the phone is.
    func currentAddressLabel() async throws -> String {
        let location = try await fix()
        let marks = try await CLGeocoder().reverseGeocodeLocation(location)
        guard let m = marks.first else { throw Failure.noFix }
        let street = [m.subThoroughfare, m.thoroughfare].compactMap { $0 }.joined(separator: " ")
        let city = m.locality ?? "New York"
        return street.isEmpty ? (m.name ?? city) : "\(street), \(city)"
    }

    private func fix() async throws -> CLLocation {
        if manager.authorizationStatus == .notDetermined {
            manager.requestWhenInUseAuthorization()
        }
        return try await withCheckedThrowingContinuation { cont in
            continuation = cont
            manager.requestLocation()
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            if status == .denied || status == .restricted {
                continuation?.resume(throwing: Failure.denied)
                continuation = nil
            } else if status == .authorizedWhenInUse || status == .authorizedAlways, continuation != nil {
                manager.requestLocation()
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let best = locations.last
        Task { @MainActor in
            guard let cont = continuation else { return }
            continuation = nil
            if let best { cont.resume(returning: best) } else { cont.resume(throwing: Failure.noFix) }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in
            guard let cont = continuation else { return }
            continuation = nil
            let denied = (error as? CLError)?.code == .denied
            cont.resume(throwing: denied ? Failure.denied : Failure.noFix)
        }
    }
}
