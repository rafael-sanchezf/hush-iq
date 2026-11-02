"""Pure-Python spatial lookups for the upgrade modules: a grid index over points and line segments."""
import math
from collections import defaultdict

M_PER_DEG_LAT = 111_000.0
M_PER_DEG_LNG = 84_300.0   # at Manhattan's latitude (40.78 N)
CELL_M = 100.0


def _xy(lat, lng):
    return lng * M_PER_DEG_LNG, lat * M_PER_DEG_LAT


def dist_m(lat1, lng1, lat2, lng2):
    x1, y1 = _xy(lat1, lng1)
    x2, y2 = _xy(lat2, lng2)
    return math.hypot(x2 - x1, y2 - y1)


def point_segment_m(lat, lng, a_lat, a_lng, b_lat, b_lng):
    px, py = _xy(lat, lng)
    ax, ay = _xy(a_lat, a_lng)
    bx, by = _xy(b_lat, b_lng)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class GridIndex:
    """Items are points (lat, lng) or segments (lat1, lng1, lat2, lng2), each with a payload."""

    def __init__(self, cell_m=CELL_M):
        self.cell = cell_m
        self.cells = defaultdict(list)

    def _key(self, lat, lng):
        x, y = _xy(lat, lng)
        return int(x // self.cell), int(y // self.cell)

    def add_point(self, lat, lng, payload):
        self.cells[self._key(lat, lng)].append(("p", (lat, lng), payload))

    def add_segment(self, lat1, lng1, lat2, lng2, payload):
        k1, k2 = self._key(lat1, lng1), self._key(lat2, lng2)
        item = ("s", (lat1, lng1, lat2, lng2), payload)
        for i in range(min(k1[0], k2[0]), max(k1[0], k2[0]) + 1):
            for j in range(min(k1[1], k2[1]), max(k1[1], k2[1]) + 1):
                self.cells[(i, j)].append(item)

    def near(self, lat, lng, radius_m):
        """[(distance_m, payload)] within the radius, nearest first, each item once."""
        ci, cj = self._key(lat, lng)
        r = int(math.ceil(radius_m / self.cell))
        seen, out = set(), []
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for kind, g, payload in self.cells.get((i, j), ()):
                    if id(payload) in seen:
                        continue
                    seen.add(id(payload))
                    d = dist_m(lat, lng, *g) if kind == "p" else point_segment_m(lat, lng, *g)
                    if d <= radius_m:
                        out.append((d, payload))
        out.sort(key=lambda x: x[0])
        return out
