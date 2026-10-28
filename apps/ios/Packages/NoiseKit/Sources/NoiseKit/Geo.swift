import Foundation

/// Small geometry helpers, a port of noise_score/geo.py. Same equirectangular projection so distances match.
public enum Geo {
    public static let earthR = 6_371_000.0

    public static func haversineM(_ lat1: Double, _ lng1: Double, _ lat2: Double, _ lng2: Double) -> Double {
        let p1 = lat1 * .pi / 180, p2 = lat2 * .pi / 180
        let dp = p2 - p1
        let dl = (lng2 - lng1) * .pi / 180
        let a = pow(sin(dp / 2), 2) + cos(p1) * cos(p2) * pow(sin(dl / 2), 2)
        return 2 * earthR * asin(sqrt(a))
    }

    /// Equirectangular projection around (lat0, lng0), metres.
    static func localXY(lat: Double, lng: Double, lat0: Double, lng0: Double) -> (x: Double, y: Double) {
        let x = (lng - lng0) * .pi / 180 * cos(lat0 * .pi / 180) * earthR
        let y = (lat - lat0) * .pi / 180 * earthR
        return (x, y)
    }

    /// Distance in metres from (lat, lng) to the segment a-b, each a [lng, lat] pair as GeoJSON gives it.
    public static func pointToSegmentM(_ lat: Double, _ lng: Double, _ a: [Double], _ b: [Double]) -> Double {
        let (ax, ay) = localXY(lat: a[1], lng: a[0], lat0: lat, lng0: lng)
        let (bx, by) = localXY(lat: b[1], lng: b[0], lat0: lat, lng0: lng)
        let dx = bx - ax, dy = by - ay
        if dx == 0 && dy == 0 { return hypot(ax, ay) }
        let t = max(0.0, min(1.0, (-(ax * dx) - (ay * dy)) / (dx * dx + dy * dy)))
        let px = ax + t * dx, py = ay + t * dy
        return hypot(px, py)
    }

    /// Min distance to a GeoJSON LineString or MultiLineString. nil for no geometry or a geometry with no lines.
    public static func pointToMultilineM(_ lat: Double, _ lng: Double, _ geom: GeoJSON?) -> Double? {
        guard let geom else { return nil }
        var best: Double?
        for line in geom.lines {
            guard line.count >= 2 else { continue }
            for i in 0..<(line.count - 1) {
                let a = line[i], b = line[i + 1]
                guard a.count >= 2, b.count >= 2 else { continue }
                let d = pointToSegmentM(lat, lng, a, b)
                best = best.map { min($0, d) } ?? d
            }
        }
        return best
    }
}
