"""Small geometry helpers. No dependencies."""
import math

EARTH_R = 6_371_000.0


def haversine_m(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _local_xy(lat, lng, lat0, lng0):
    """Equirectangular projection around (lat0, lng0), metres."""
    x = math.radians(lng - lng0) * math.cos(math.radians(lat0)) * EARTH_R
    y = math.radians(lat - lat0) * EARTH_R
    return x, y


def point_to_segment_m(lat, lng, a, b):
    """Distance in metres from (lat, lng) to the segment a-b, each a (lng, lat) pair as GeoJSON gives it."""
    ax, ay = _local_xy(a[1], a[0], lat, lng)
    bx, by = _local_xy(b[1], b[0], lat, lng)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, (-(ax * dx) - (ay * dy)) / (dx * dx + dy * dy)))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(px, py)


def point_to_multiline_m(lat, lng, geom):
    """Min distance to a GeoJSON LineString or MultiLineString."""
    if not geom:
        return None
    lines = geom.get("coordinates", [])
    if geom.get("type") == "LineString":
        lines = [lines]
    best = None
    for line in lines:
        for a, b in zip(line, line[1:]):
            d = point_to_segment_m(lat, lng, a, b)
            best = d if best is None else min(best, d)
    return best
