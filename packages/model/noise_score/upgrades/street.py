"""Street upgrade: what actually passes, per hour, by time slot. (Hackathon work, Oct 28.)

Today's street estimate comes from the road's class, lanes, speed and distance. This module keeps that estimate
and corrects it with the traffic that really uses the road: counted vehicles per hour (NYC DOT), the truck and
bus share, and the scheduled buses (MTA). Rules and sources: packages/model/upgrades/street.md.

Request time (`upgrade`): pure Python, reads data/upgrades/street.json.gz once, no network.
Build time (`build`): pulls public data (NYC Open Data, MTA GTFS), pure Python, under 2 minutes, needs network.
"""
import csv
import datetime
import gzip
import io
import json
import math
import re
import statistics
import time
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections import defaultdict
from pathlib import Path

from .. import config as C
from .. import config_v2 as V
from .. import recal
from . import DATA, SLOTS, Step, Upgrade, load, passthrough
from ._geo import GridIndex, dist_m

NAME = "street"

# ---------------------------------------------------------------- numbers (each says where it comes from)
# Slot hours come from today's model (config.WINDOWS): night 22-5, early 5-8, day 8-22.
SLOT_HOURS = {s: [h % 24 for h in range(a, b if b > a else b + 24)] for s, (a, b) in C.WINDOWS.items()}

# Heavy vehicle equivalence: one truck or bus makes as much sound energy as this many cars. Sourced, from the noise
# research of 2026-10-29 (config_v2 [V10]): NYC's CEQR manual uses 13 for a medium truck and 18 for a bus at 25 mph,
# and FTA puts a bus at 17.8 cars at 25 mph but 6.3 at 50, so 15 on city streets and 8 on highways. (Was 8 for all,
# decision U2.)
K_HEAVY = V.HEAVY_VEHICLE_FACTOR
K_HEAVY_HIGHWAY = V.HEAVY_VEHICLE_FACTOR_HIGHWAY


def heavy_factor(cls):
    """Cars one truck or bus equals on a road of this class."""
    return K_HEAVY_HIGHWAY if cls == "highway" else K_HEAVY

# The correction never moves a street by more than this many index points. Judgment: the counted Manhattan
# streets differ from their class median by roughly a factor of 4 either way (6 dB), and a ceiling stops one
# odd count (a street counted on a closure day) from dominating.
CORRECTION_CAP = 6.0

# Count years used. Judgment: 2020 and 2021 are skipped (pandemic traffic); 2019 and 2022 on are kept, and for a
# street counted in several years the latest wins. 2019 counts below 60th Street pre-date congestion pricing.
COUNT_YEARS = (2019, 2022, 2023, 2024, 2025, 2026)
# Weekdays only (Mon to Fri): renters sleep on weeknights and the counts include weekends of unequal coverage.
WEEKDAYS = (0, 1, 2, 3, 4)

# A direction's count is dropped as a counter fault or a closure when its day volume is under COUNT_MIN_DAY_VPH,
# when night or early volume is under COUNT_MIN_SLOT_RATIO of the day, or early is over COUNT_MAX_EARLY_RATIO times
# the day. Judgment, from the 126 counted directions: real streets keep night at 0.1 to 0.5 of the day and early
# at 0.5 to 1.3; the dropped ones show zero vehicles all day or all night.
COUNT_MIN_DAY_VPH = 25.0
COUNT_MIN_SLOT_RATIO = 0.05
COUNT_MAX_EARLY_RATIO = 3.0

# A count point is matched to the street centerline segment of the same name within this distance, or to the
# nearest drivable segment of any name within the shorter distance. Judgment, from the median match distance of
# 1 m and a longest correct match of 40 m (block-face midpoints vs. the physical segment).
COUNT_MATCH_NAMED_M = 40.0
COUNT_MATCH_ANY_M = 12.0
# A two-way street counted in one direction only is assumed to carry the same volume the other way. Judgment.
DOUBLE_ONE_DIRECTION = True

# A street without its own count borrows from the nearest counted segment of the same street name and traffic
# direction, fading linearly to nothing at this distance (then the class median alone). Judgment: an avenue's
# volume changes slowly over a kilometre but not over several.
BORROW_MAX_M = 1000.0
# Fewer counted segments than this in a class and the class median is not trusted: use the parent class below.
MIN_COUNTED_IN_CLASS = 3
CLASS_PARENT = {"ramp": "bridge", "bridge": "arterial", "one_lane": "two_lane", "two_lane": "arterial"}
# The bus timetable can never account for more than this share of a counted volume (rest is trucks and cars).
# Judgment: guards against a shape that runs on a parallel street being matched to this one.
BUS_MAX_SHARE = 0.5

# Bus and truck routes are matched to a centerline segment when they run within this distance and within this
# angle of it for at least half of its length. Judgment: 15 m is below the 20 m gap between the two carriageways
# of a divided avenue, so each direction lands on its own carriageway.
ROUTE_MATCH_M = 15.0
ROUTE_MATCH_ANGLE_DEG = 30.0
ROUTE_COVER_FRACTION = 0.5
SAMPLE_STEP_M = 15.0
# Weekday schedule: a Tuesday inside the current MTA school-year timetable (school-day service on).
GTFS_REFERENCE_DATE = datetime.date(2026, 11, 10)

# Evidence sentences mention buses only at or above this many per hour (day), trucks at or above this share.
EVIDENCE_MIN_BUSES = 4.0
EVIDENCE_MIN_TRUCK_SHARE = 0.04
EPS_VEHICLES = 0.5            # keeps log10 finite on a street with no vehicles (a bridge footpath)

M_PER_DEG_LAT = 111_000.0
M_PER_DEG_LNG = 84_300.0
CLASSES = ("highway", "ramp", "bridge", "arterial", "two_lane", "one_lane")
ROUTE_LABEL = {0: "not a truck route", 1: "a local truck route", 2: "a through truck route"}

DATASETS = [
    {"id": "7ym2-wayt", "name": "NYC DOT Automated Traffic Volume Counts", "url": "https://data.cityofnewyork.us/d/7ym2-wayt"},
    {"id": "96ay-ea4r", "name": "NYC DOT Vehicle Classification Counts", "url": "https://data.cityofnewyork.us/d/96ay-ea4r"},
    {"id": "jjja-shxy", "name": "NYC Truck Routes", "url": "https://data.cityofnewyork.us/d/jjja-shxy"},
    {"id": "inkn-q76z", "name": "NYC Street Centerline (CSCL)", "url": "https://data.cityofnewyork.us/d/inkn-q76z"},
    {"id": "gtfs_m gtfs_bx gtfs_b gtfs_q gtfs_si gtfs_busco", "name": "MTA bus timetables (GTFS static)",
     "url": "https://new.mta.info/developers"},
]
GTFS_FEEDS = ["gtfs_m", "gtfs_bx", "gtfs_b", "gtfs_q", "gtfs_si", "gtfs_busco"]
GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/{}.zip"
SOCRATA = "https://data.cityofnewyork.us/resource/{}.json?"
MANHATTAN_BOX = (40.68, 40.89, -74.03, -73.90)   # lat0, lat1, lng0, lng1, for the bus shapes


# ================================================================ shared helpers (build and request time)
def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def road_class(rw, travel_lanes):
    """The class today's model gives a centerline segment (model.street)."""
    if rw == "2":
        return "highway"
    if rw == "9":
        return "ramp"
    if rw == "3":
        return "bridge"
    if travel_lanes >= 3:
        return "arterial"
    if travel_lanes == 2:
        return "two_lane"
    return "one_lane"


def today_road_level(cls, critical, speed, two_way, d, K=None):
    """Today's road level for one segment at distance d, before the hour offset: model.street line for line, with
    the research numbers [V10] (recal.street) unless K says otherwise."""
    K = K or recal.NUMBERS
    base = C.ROAD_BASE_DB[cls]
    if critical:
        base += C.ROAD_SNOW_CRITICAL_DB
    if K["road_speed_classes"] is None or cls in K["road_speed_classes"]:
        base += max(0.0, (speed - 25) / 5) * K["road_speed_db_per_5mph"]
    if two_way:
        base += K["road_two_way_db"]
    d = max(d, C.ROAD_REF_DISTANCE_M)
    return base - C.ROAD_DB_PER_DOUBLING * math.log2(d / C.ROAD_REF_DISTANCE_M)


def effective(q, b, tau, k=K_HEAVY):
    """Effective vehicles per hour per slot: cars + k x (trucks + buses). q = vehicles other than buses."""
    return [q[i] * (1 + (k - 1) * tau[i]) + k * b[i] for i in range(3)]


def correction_db(eff, ref):
    """10 x log10(effective / implied), capped."""
    return max(-CORRECTION_CAP, min(CORRECTION_CAP, 10 * math.log10(max(eff, EPS_VEHICLES) / max(ref, EPS_VEHICLES))))


def _norm(n):
    """Street names compared across datasets: 'WEST 145 STREET' and 'W  145 ST' are the same."""
    n = (n or "").upper()
    n = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", n)
    for a, b in (("EAST", "E"), ("WEST", "W"), ("NORTH", "N"), ("SOUTH", "S"), ("AVENUE", "AVE"), ("STREET", "ST"),
                 ("PLACE", "PL"), ("BOULEVARD", "BLVD"), ("ROAD", "RD"), ("DRIVE", "DR"), ("PARKWAY", "PKWY"),
                 ("EXPRESSWAY", "EXPY"), ("SQUARE", "SQ"), ("TERRACE", "TER"), ("HIGHWAY", "HWY"), ("BRIDGE", "BRG")):
        n = re.sub(r"\b" + a + r"\b", b, n)
    return re.sub(r"\s+", " ", n).strip()


def _pretty(name):
    """'W  42 ST' -> 'West 42nd St', 'AMSTERDAM AVE' -> 'Amsterdam Ave'."""
    toks = re.sub(r"\s+", " ", name or "").strip().split(" ")
    out = []
    for i, t in enumerate(toks):
        if t.isdigit():
            n = int(t)
            suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
            out.append(f"{n}{suf}")
        elif t in ("E", "W") and i == 0 and len(toks) > 1 and toks[1].isdigit():
            out.append("East" if t == "E" else "West")
        else:
            out.append(t.capitalize())
    return " ".join(out)


def _round_count(v):
    """A count a renter can read: nearest 100 from 1,000, nearest 10 from 100, nearest 5 from 20."""
    if v >= 1000:
        return f"{int(round(v, -2)):,}"
    if v >= 100:
        return str(int(round(v, -1)))
    if v >= 20:
        return str(int(round(v / 5.0) * 5))
    return str(int(round(v)))


# ================================================================ build
def _http(url, tries=4):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:      # network is flaky; retry politely
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def _socrata(ds_id, params, limit=5000, cache=None):
    path = Path(cache) / f"{ds_id}_{zlib.crc32(json.dumps(params, sort_keys=True).encode()):08x}.json" if cache else None
    if path and path.exists():
        return json.loads(path.read_text())
    rows, off = [], 0
    while True:
        p = dict(params)
        p["$limit"], p["$offset"] = limit, off
        page = json.loads(_http(SOCRATA.format(ds_id) + urllib.parse.urlencode(p)))
        rows += page
        if len(page) < limit:
            break
        off += limit
        time.sleep(0.5)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
    return rows


def _gtfs_zip(feed, cache=None):
    path = Path(cache) / f"{feed}.zip" if cache else None
    if path and path.exists():
        return zipfile.ZipFile(path)
    data = _http(GTFS_URL.format(feed))
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return zipfile.ZipFile(io.BytesIO(data))


def _lcc_ny(x_ft, y_ft):
    """NAD83 / New York Long Island (ftUS, EPSG:2263) to (lng, lat). Lambert conformal conic, GRS80; checked
    against pyproj to 1e-9 degrees. DOT count points are in this system."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = 2 * f - f * f
    e = math.sqrt(e2)
    p1, p2, p0, l0 = (math.radians(v) for v in (40 + 40 / 60, 41 + 2 / 60, 40 + 10 / 60, -74.0))

    def m(p):
        return math.cos(p) / math.sqrt(1 - e2 * math.sin(p) ** 2)

    def t(p):
        s = math.sin(p)
        return math.tan(math.pi / 4 - p / 2) / (((1 - e * s) / (1 + e * s)) ** (e / 2))

    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
    F = m(p1) / (n * t(p1) ** n)
    r0 = a * F * t(p0) ** n
    ft = 1200 / 3937
    x, y = (x_ft - 300000.0 / 0.3048006096012192) * ft, y_ft * ft
    rp = math.copysign(math.hypot(x, r0 - y), n)
    tp = (rp / (a * F)) ** (1 / n)
    th = math.atan2(x, r0 - y)
    phi = math.pi / 2 - 2 * math.atan(tp)
    for _ in range(8):
        s = math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(tp * (((1 - e * s) / (1 + e * s)) ** (e / 2)))
    return math.degrees(th / n + l0), math.degrees(phi)


def _xy(lat, lng):
    return lng * M_PER_DEG_LNG, lat * M_PER_DEG_LAT


def _bearing(a_lat, a_lng, b_lat, b_lng):
    """Direction of a line, ignoring its sense, in radians in [0, pi)."""
    x1, y1 = _xy(a_lat, a_lng)
    x2, y2 = _xy(b_lat, b_lng)
    return math.atan2(y2 - y1, x2 - x1) % math.pi


def _angle_gap(a, b):
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _line_length_m(line):
    return sum(dist_m(a[1], a[0], b[1], b[0]) for a, b in zip(line, line[1:]))


def _samples(line, step=SAMPLE_STEP_M):
    """Points (lat, lng, bearing) along a (lng, lat) line, every `step` metres, starting half a step in."""
    out, carry = [], step / 2
    for a, b in zip(line, line[1:]):
        L = dist_m(a[1], a[0], b[1], b[0])
        if L == 0:
            continue
        brg = _bearing(a[1], a[0], b[1], b[0])
        pos = carry
        while pos < L:
            u = pos / L
            out.append((a[1] + u * (b[1] - a[1]), a[0] + u * (b[0] - a[0]), brg))
            pos += step
        carry = pos - L
    if not out and len(line) > 1:
        a, b = line[0], line[-1]
        out.append(((a[1] + b[1]) / 2, (a[0] + b[0]) / 2, _bearing(a[1], a[0], b[1], b[0])))
    return out


def _centerline(cache):
    rows = _socrata("inkn-q76z", {
        "$select": "physicalid,full_street_name,rw_type,number_travel_lanes,posted_speed,snow_priority,trafdir,the_geom",
        "$where": "boroughcode='1'", "$order": "physicalid"}, cache=cache)
    segs = []
    for r in rows:
        rw = str(r.get("rw_type"))
        g = r.get("the_geom")
        if rw in C.ROAD_IGNORE_RW_TYPES or not g:
            continue
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        parts = [[(p[0], p[1]) for p in part] for part in parts if len(part) > 1]
        if not parts:
            continue
        travel = int(_num(r.get("number_travel_lanes"), 1) or 1)
        speed = _num(r.get("posted_speed"), 25) or 25
        td = r.get("trafdir") or ""
        segs.append({"n": (r.get("full_street_name") or "unnamed").strip(), "k": road_class(rw, travel), "rw": rw,
                     "ln": travel, "sp": speed, "cr": int(r.get("snow_priority") == "C" and rw == "1"),
                     "tw": int(td == "TW"), "nv": int(td == "NV"), "td": td, "parts": parts})
    return segs


def _index_segments(segs, cell_m=100.0):
    gi = GridIndex(cell_m)
    for s in segs:
        for part in s["parts"]:
            for a, b in zip(part, part[1:]):
                gi.add_segment(a[1], a[0], b[1], b[0], s)
    return gi


def _mid(s):
    """Midpoint (lat, lng) of a segment's longest part."""
    part = max(s["parts"], key=_line_length_m)
    pts = _samples(part, step=_line_length_m(part) or 1.0)
    return (pts[0][0], pts[0][1]) if pts else (part[0][1], part[0][0])


def _cover(segs, pieces_gi):
    """For every segment, the payload values (shape ids / route types) that run along at least
    ROUTE_COVER_FRACTION of it: {segment_index: {value: fraction}}. Centerline-centric, so a route on a parallel
    street or crossing the segment at an intersection is not counted."""
    out = {}
    tol = math.radians(ROUTE_MATCH_ANGLE_DEG)
    for si, s in enumerate(segs):
        hits, total = defaultdict(int), 0
        for part in s["parts"]:
            for lat, lng, brg in _samples(part):
                total += 1
                seen = set()
                for d, pay in pieces_gi.near(lat, lng, ROUTE_MATCH_M):
                    key, pbrg = pay[0], pay[1]
                    if key in seen or _angle_gap(brg, pbrg) > tol:
                        continue
                    seen.add(key)
                    hits[key] += 1
        if total:
            good = {k: h / total for k, h in hits.items() if h / total >= ROUTE_COVER_FRACTION}
            if good:
                out[si] = good
    return out


def _truck_routes(segs, cache):
    rows = _socrata("jjja-shxy", {"$where": "boroname='Manhattan'"}, cache=cache)
    gi = GridIndex(25.0)
    seg_ids = {}
    for r in rows:
        g = r.get("the_geom")
        if not g:
            continue
        typ = 2 if (r.get("routetype") or "").lower().startswith("thr") else 1
        seg_ids.setdefault(r.get("segmentid", "").lstrip("0"), []).append(g)
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for part in parts:
            for a, b in zip(part, part[1:]):
                if a != b:
                    gi.add_segment(a[1], a[0], b[1], b[0], (typ, _bearing(a[1], a[0], b[1], b[0])))
    cov = _cover(segs, gi)
    route = {}
    for si, c in cov.items():
        route[si] = 2 if 2 in c else 1
    return route, len(rows), seg_ids


def _gtfs_buses(segs, cache):
    """Weekday buses per hour per slot per segment, from trips (first-stop hour), stop_times and shapes."""
    ref = GTFS_REFERENCE_DATE
    dow = ref.strftime("%A").lower()
    slot_of = {h: s for s, hs in SLOT_HOURS.items() for h in hs}
    gi = GridIndex(25.0)
    shape_trips = {}            # shape key -> [trips night, early, day]
    n_trips = 0
    pid = 0
    for feed in GTFS_FEEDS:
        zf = _gtfs_zip(feed, cache)
        names = zf.namelist()

        def rd(fn, zf=zf):
            with zf.open(fn) as fh:
                yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
        active = set()
        if "calendar.txt" in names:
            for r in rd("calendar.txt"):
                if r[dow] == "1" and r["start_date"] <= ref.strftime("%Y%m%d") <= r["end_date"]:
                    active.add(r["service_id"])
        if "calendar_dates.txt" in names:
            for r in rd("calendar_dates.txt"):
                if r["date"] == ref.strftime("%Y%m%d"):
                    (active.add if r["exception_type"] == "1" else active.discard)(r["service_id"])
        trips = {r["trip_id"]: r["shape_id"] for r in rd("trips.txt") if r["service_id"] in active and r.get("shape_id")}
        first = {}
        with zf.open("stop_times.txt") as fh:
            rdr = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
            hdr = next(rdr)
            it, ds, sq = hdr.index("trip_id"), hdr.index("departure_time"), hdr.index("stop_sequence")
            for row in rdr:
                t = row[it]
                if t in trips:
                    s = int(row[sq])
                    cur = first.get(t)
                    if cur is None or s < cur[0]:
                        first[t] = (s, row[ds])
        for t, (_, dep) in first.items():
            try:
                h = int(dep.split(":")[0]) % 24
            except ValueError:
                continue
            key = (feed, trips[t])
            shape_trips.setdefault(key, [0, 0, 0])[SLOTS.index(slot_of[h])] += 1
            n_trips += 1
        # shapes inside Manhattan
        pts = defaultdict(list)
        for r in rd("shapes.txt"):
            if (feed, r["shape_id"]) in shape_trips:
                lat, lng = float(r["shape_pt_lat"]), float(r["shape_pt_lon"])
                pts[r["shape_id"]].append((int(r["shape_pt_sequence"]), lat, lng))
        for sid, p in pts.items():
            p.sort()
            for (_, la, ln), (_, lb, lm) in zip(p, p[1:]):
                if MANHATTAN_BOX[0] <= la <= MANHATTAN_BOX[1] and MANHATTAN_BOX[2] <= ln <= MANHATTAN_BOX[3] and (la, ln) != (lb, lm):
                    gi.add_segment(la, ln, lb, lm, ((feed, sid), _bearing(la, ln, lb, lm)))
                    pid += 1
    cov = _cover(segs, gi)
    buses = {}
    for si, c in cov.items():
        tot = [0.0, 0.0, 0.0]
        for key in c:
            for i in range(3):
                tot[i] += shape_trips[key][i]
        buses[si] = [tot[i] / len(SLOT_HOURS[SLOTS[i]]) for i in range(3)]
    return buses, n_trips, len(shape_trips)


def _count_volumes(cache):
    """{(segmentid, direction): {"year", "vph": [3], "street", "x", "y"}} weekday mean vehicles per hour per
    slot, latest usable year per segment and direction."""
    rows = _socrata("7ym2-wayt", {"$where": "boro='Manhattan' AND yr>=2019", "$order": "requestid,segmentid,direction,yr,m,d,hh,mm"},
                    limit=20000, cache=cache)
    cells = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    info = {}
    for r in rows:
        y, m, d = int(r["yr"]), int(r["m"]), int(r["d"])
        if y not in COUNT_YEARS:
            continue
        dt = datetime.date(y, m, d)
        if dt.weekday() not in WEEKDAYS:
            continue
        c = cells[(r["segmentid"], r["direction"], y)][(dt, int(r["hh"]))]
        c[0] += int(r["vol"])
        c[1] += 1
        info[r["segmentid"]] = (r["street"], r["wktgeom"])
    by = defaultdict(dict)
    dropped = []
    for (sid, direction, y), hours in cells.items():
        per_hour = defaultdict(list)
        for (dt, hh), (v, n) in hours.items():
            if n == 4:                      # a full hour of four 15-minute counts
                per_hour[hh].append(v)
        vph = []
        for s in SLOTS:
            hs = [_median(per_hour[h]) for h in SLOT_HOURS[s] if per_hour[h]]     # median over counted days
            if len(hs) < 0.7 * len(SLOT_HOURS[s]):
                vph = None
                break
            vph.append(sum(hs) / len(hs))
        if vph and vph[2] >= COUNT_MIN_DAY_VPH and min(vph[0], vph[1]) >= COUNT_MIN_SLOT_RATIO * vph[2] \
                and vph[1] <= COUNT_MAX_EARLY_RATIO * vph[2]:
            by[(sid, direction)][y] = vph
        elif vph:
            dropped.append((sid, direction, y))
    out = {}
    for k, ys in by.items():
        y = max(ys)
        m = re.match(r"POINT \(([-\d.]+) ([-\d.]+)\)", info[k[0]][1])
        x, yy = _lcc_ny(float(m[1]), float(m[2]))
        out[k] = {"year": y, "vph": ys[y], "street": info[k[0]][0], "lng": x, "lat": yy}
    return out, len(rows), dropped


def _match_counts(segs, gi, vols):
    """Attach counted volumes to centerline segments. Returns {segment_index: {...}} and the unmatched list."""
    index_of = {id(s): i for i, s in enumerate(segs)}
    got = defaultdict(dict)         # seg idx -> {direction key: record}
    unmatched = []
    for (sid, direction), v in vols.items():
        near = [(d, s) for d, s in gi.near(v["lat"], v["lng"], COUNT_MATCH_NAMED_M) if not s["nv"]]
        named = [c for c in near if _norm(c[1]["n"]) == _norm(v["street"])]
        pick = named[0] if named else (near[0] if near and near[0][0] <= COUNT_MATCH_ANY_M else None)
        if not pick:
            unmatched.append((sid, direction, v["street"]))
            continue
        i = index_of[id(pick[1])]
        got[i][(sid, direction)] = v
    counted = {}
    for i, recs in got.items():
        s = segs[i]
        by_dir = defaultdict(list)
        for (sid, direction), v in recs.items():
            by_dir[direction].append(v)
        vph, year = [0.0, 0.0, 0.0], 0
        for direction, vs in by_dir.items():     # two LION segments for one direction: average
            for k in range(3):
                vph[k] += sum(v["vph"][k] for v in vs) / len(vs)
            year = max(year, max(v["year"] for v in vs))
        doubled = bool(s["tw"] and len(by_dir) == 1 and DOUBLE_ONE_DIRECTION)
        if doubled:
            vph = [2 * x for x in vph]
        counted[i] = {"vph": vph, "year": year, "dirs": len(by_dir), "doubled": doubled}
    return counted, unmatched


def _classification(segs, gi, seg_geoms, counts_pts, routes, cache):
    """Truck share of non-bus vehicles per slot, from DOT classification counts in Manhattan.
    A classification segment is placed on the map when it is also a truck route segment (same LION segment id) or
    also an automated-count segment, and then belongs to one centerline segment. The rest are kept for the pooled
    share only, when the street and both cross streets are Manhattan names and the street is wholly a truck route
    or wholly not. Returns ({seg_index: (tau[3], nonbus[3])}, [(route_type, tau[3], nonbus[3])], n_rows)."""
    rows = _socrata("96ay-ea4r", {"$where": "date>='2019-01-01'"}, cache=cache)
    loc = {}
    for sid, geoms in seg_geoms.items():
        g = geoms[0]
        part = (g["coordinates"][0] if g["type"] == "MultiLineString" else g["coordinates"])
        mid = part[len(part) // 2]
        loc[sid] = (mid[1], mid[0])
    for sid, (lat, lng) in counts_pts.items():
        loc.setdefault(sid, (lat, lng))
    # column order is the hour of day, 12-1 am first
    order = ["_12_00_1_00_am", "_1_00_2_00am", "_2_00_3_00am", "_3_00_4_00am", "_4_00_5_00am", "_5_00_6_00am",
             "_6_00_7_00am", "_7_00_8_00am", "_8_00_9_00am", "_9_00_10_00am", "_10_00_11_00am", "_11_00_12_00pm",
             "_12_00_1_00pm", "_1_00_2_00pm", "_2_00_3_00pm", "_3_00_4_00pm", "_4_00_5_00pm", "_5_00_6_00pm",
             "_6_00_7_00pm", "_7_00_8_00pm", "_8_00_9_00pm", "_9_00_10_00pm", "_10_00_11_00pm", "_11_00_12_00am"]
    acc = defaultdict(lambda: {"all": [0.0] * 3, "bus": [0.0] * 3, "truck": [0.0] * 3})
    names = {}
    for r in rows:
        sid = r["segmentid"]
        names[sid] = (_norm(r["roadway_name"]), _norm(r["from"]), _norm(r["to"]))
        dt = datetime.date.fromisoformat(r["date"][:10])
        if dt.year not in COUNT_YEARS or dt.weekday() not in WEEKDAYS:
            continue
        cls = " ".join(r["veh_class_type"].split())
        a = acc[sid]
        for si, s in enumerate(SLOTS):
            tot = sum(_num(r.get(order[h]), 0.0) for h in SLOT_HOURS[s])
            a["all"][si] += tot
            if cls in ("Other Bus", "School Bus"):
                a["bus"][si] += tot
            elif cls in ("Medium Truck", "Heavy Truck"):
                a["truck"][si] += tot
    street_names = defaultdict(list)
    for i, s in enumerate(segs):
        street_names[_norm(s["n"])].append(routes.get(i, 0))
    placed, named = {}, []
    for sid, a in acc.items():
        nonbus = [a["all"][i] - a["bus"][i] for i in range(3)]
        if min(nonbus) < 200:
            continue
        tau = [a["truck"][i] / nonbus[i] for i in range(3)]
        road, frm, to = names[sid]
        if sid in loc:
            lat, lng = loc[sid]
            near = [(d, s) for d, s in gi.near(lat, lng, COUNT_MATCH_NAMED_M) if not s["nv"] and _norm(s["n"]) == road]
            if near:
                placed[sid] = (near[0][1], tau, nonbus)
        elif road in street_names and frm in street_names and to in street_names:
            kinds = street_names[road]
            frac = sum(1 for k in kinds if k) / len(kinds)
            if frac <= 0.05:
                named.append((0, tau, nonbus))
            elif frac >= 0.8:
                named.append((max(set(kinds), key=kinds.count), tau, nonbus))
    return placed, named, len(rows)


def _estimate(segs, counted, buses):
    """Non-bus vehicles per hour for every segment: counted, borrowed from the same street, or class median."""
    n_counted = {}
    for i, c in counted.items():
        b = buses.get(i, [0.0, 0.0, 0.0])
        n_counted[i] = [max(c["vph"][k] - min(b[k], BUS_MAX_SHARE * c["vph"][k]), 0.0) for k in range(3)]
    by_class = defaultdict(list)
    for i, q in n_counted.items():
        by_class[segs[i]["k"]].append(q)

    def med(c):
        qs = by_class.get(c, [])
        while len(qs) < MIN_COUNTED_IN_CLASS and c in CLASS_PARENT:
            c = CLASS_PARENT[c]
            qs = by_class.get(c, [])
        if not qs:
            qs = [q for v in by_class.values() for q in v]
        return [statistics.median(q[k] for q in qs) for k in range(3)], len(by_class.get(c, []))
    class_q = {c: med(c)[0] for c in CLASSES}
    # same-street borrowing
    street_counted = defaultdict(list)
    mids = {i: _mid(s) for i, s in enumerate(segs)}
    for i in n_counted:
        s = segs[i]
        street_counted[(_norm(s["n"]), s["td"], s["rw"])].append(i)
    est = {}
    for i, s in enumerate(segs):
        if s["nv"]:
            est[i] = ([0.0, 0.0, 0.0], 0, None)
        elif i in n_counted:
            est[i] = (n_counted[i], 2, None)
        else:
            base = class_q[s["k"]]
            cand = []
            for j in street_counted.get((_norm(s["n"]), s["td"], s["rw"]), ()):
                d = dist_m(*mids[i], *mids[j])
                if d <= BORROW_MAX_M:
                    cand.append((d, j))
            cand.sort()
            if cand:
                near = cand[:2]
                wts = [1.0 / (d + 50.0) for d, _ in near]
                nb = [sum(w * n_counted[j][k] for w, (_, j) in zip(wts, near)) / sum(wts) for k in range(3)]
                lam = 1 - near[0][0] / BORROW_MAX_M
                est[i] = ([lam * nb[k] + (1 - lam) * base[k] for k in range(3)], 1, near[0][0])
            else:
                est[i] = (base, 0, None)
    return est, class_q, {c: len(v) for c, v in by_class.items()}


def _encode_part(part):
    """Absolute first vertex, then deltas, in 1e-5 degrees (about 1 m)."""
    out, px, py = [], 0, 0
    for k, (x, y) in enumerate(part):
        xi, yi = int(round(x * 1e5)), int(round(y * 1e5))
        out += [xi - px, yi - py]
        px, py = xi, yi
    return out


def build(out_dir=None, cache_dir=None, log=print):
    """Pull the public data and write street.json.gz into out_dir (default data/upgrades). cache_dir keeps the raw
    pulls so a rerun does not hit the network again. Pure Python, under 2 minutes with network."""
    out_dir = Path(out_dir) if out_dir else DATA
    cache = str(cache_dir) if cache_dir else None
    t0 = time.time()
    segs = _centerline(cache)
    gi = _index_segments(segs)
    log(f"centerline: {len(segs)} drivable-class segments in Manhattan  [{time.time() - t0:.0f}s]")
    routes, n_truck_rows, truck_geoms = _truck_routes(segs, cache)
    log(f"truck routes: {n_truck_rows} rows, {len(routes)} segments designated  [{time.time() - t0:.0f}s]")
    buses, n_trips, n_shapes = _gtfs_buses(segs, cache)
    log(f"bus timetables: {n_trips} weekday trips, {n_shapes} shapes, {len(buses)} segments with buses  [{time.time() - t0:.0f}s]")
    vols, n_count_rows, dropped = _count_volumes(cache)
    counted, unmatched = _match_counts(segs, gi, vols)
    log(f"counts: {n_count_rows} rows, {len(dropped)} segment-direction-years dropped as faults, {len(vols)} segment-directions, {len(counted)} centerline segments counted, "
        f"{len(unmatched)} unmatched {unmatched}  [{time.time() - t0:.0f}s]")
    pts = {sid: (v["lat"], v["lng"]) for (sid, _), v in vols.items()}
    placed, named, n_class_rows = _classification(segs, gi, truck_geoms, pts, routes, cache)
    log(f"classification: {n_class_rows} rows, {len(placed)} segments placed on the map, {len(named)} more by street name  [{time.time() - t0:.0f}s]")
    # truck share: pooled per route type and slot (ratio of sums), and per placed segment
    seg_tau = {}
    pool = defaultdict(lambda: [0.0] * 6)
    n_pool = defaultdict(int)
    index_of = {id(s): i for i, s in enumerate(segs)}
    for sid, (s, tau, nonbus) in placed.items():
        i = index_of[id(s)]
        seg_tau[i] = [round(t, 4) for t in tau]
    for rt, tau, nonbus in [(routes.get(index_of[id(s)], 0), tau, nb) for s, tau, nb in placed.values()] + named:
        n_pool[rt] += 1
        for k in range(3):
            pool[rt][k] += tau[k] * nonbus[k]
            pool[rt][3 + k] += nonbus[k]
    all_t = [sum(pool[r][k] for r in pool) for k in range(3)]
    all_n = [sum(pool[r][3 + k] for r in pool) for k in range(3)]
    tau_pool = {}
    for rt in (0, 1, 2):
        if n_pool[rt] >= MIN_COUNTED_IN_CLASS:
            tau_pool[rt] = [round(pool[rt][k] / pool[rt][3 + k], 4) for k in range(3)]
        else:
            tau_pool[rt] = [round(all_t[k] / all_n[k], 4) for k in range(3)]
    log(f"truck share pooled by route type {tau_pool}; classification segments per type {dict(n_pool)}")
    est, class_q, n_by_class = _estimate(segs, counted, buses)
    out_segs = []
    for i, s in enumerate(segs):
        q, tier, ds = est[i]
        rec = {"n": s["n"], "k": s["k"], "ln": s["ln"], "sp": s["sp"], "cr": s["cr"], "tw": s["tw"], "nv": s["nv"],
               "t": routes.get(i, 0), "s": tier, "q": [round(x, 1) for x in q],
               "b": [round(x, 1) for x in buses.get(i, [0, 0, 0])],
               "g": [_encode_part(p) for p in s["parts"]]}
        if ds is not None:
            rec["ds"] = int(round(ds))
        if i in seg_tau:
            rec["ta"] = seg_tau[i]
        if i in counted:
            c = counted[i]
            rec["cy"], rec["cd"] = c["year"], c["dirs"]
            if c["doubled"]:
                rec["x2"] = 1
        out_segs.append(rec)
    doc = {
        "meta": {
            "built": datetime.date.today().isoformat(), "gtfs_date": GTFS_REFERENCE_DATE.isoformat(),
            "datasets": DATASETS, "count_years": list(COUNT_YEARS),
            "rows": {"counts": n_count_rows, "classification": n_class_rows, "truck_routes": n_truck_rows,
                     "bus_trips": n_trips, "centerline": len(segs)},
            "counted_segments": len(counted), "counted_by_class": n_by_class, "class_nonbus_median": class_q,
            "classification_segments": len(placed) + len(named), "classification_by_route_type": dict(n_pool),
        },
        "tau": {str(k): v for k, v in tau_pool.items()},
        "segs": out_segs,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{NAME}.json.gz"
    with gzip.open(path, "wt") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"wrote {path} ({path.stat().st_size / 1e6:.2f} MB)  [{time.time() - t0:.0f}s]")
    return doc["meta"]


# ================================================================ request time
_STATE = {}


def _decode(part):
    x = y = 0
    pts = []
    for k in range(0, len(part), 2):
        x += part[k]
        y += part[k + 1]
        pts.append((y / 1e5, x / 1e5))          # (lat, lng)
    return pts


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _prepare(doc):
    gi = GridIndex()
    segs = doc["segs"]
    for s in segs:
        for part in s["g"]:
            pts = _decode(part)
            for a, b in zip(pts, pts[1:]):
                gi.add_segment(a[0], a[1], b[0], b[1], s)
    tau = {int(k): v for k, v in doc["tau"].items()}
    # What each road class implies: the median effective volume of its counted segments, by slot, counted with
    # the class's own heavy-vehicle factor so a street and its class are on one footing.
    by_class = defaultdict(list)
    for s in segs:
        if s["s"] == 2 and not s["nv"]:
            by_class[s["k"]].append((s["q"], s["b"], s.get("ta") or tau[s["t"]]))
    ref = {}
    for c in CLASSES:
        k = c
        while len(by_class.get(k, ())) < MIN_COUNTED_IN_CLASS and k in CLASS_PARENT:
            k = CLASS_PARENT[k]
        vs = [effective(*x, heavy_factor(c)) for x in (by_class.get(k) or [x for y in by_class.values() for x in y])]
        ref[c] = ([_median([v[i] for v in vs]) for i in range(3)], k, len(by_class.get(k, ())))
    return {"doc": doc, "gi": gi, "tau": tau, "ref": ref}


def _state():
    if "ready" not in _STATE:
        try:
            doc = load(NAME)
            _STATE["st"] = _prepare(doc) if doc else None
        except Exception:
            _STATE["st"] = None
        _STATE["ready"] = True
    return _STATE["st"]


def _energy_sum(levels):
    return 10 * math.log10(sum(10 ** (v / 10) for v in levels))


def upgrade(lat, lng, today, facts=None):
    """Today's street level per slot, corrected for the traffic that actually passes. Never raises."""
    today = dict(today) if isinstance(today, dict) else {}
    try:
        return _upgrade(lat, lng, today)
    except Exception:
        return passthrough(NAME, today)


def _no_road(today):
    return Upgrade(levels=dict(today), steps=[
        Step(id="street.today_level", label="Today's street level", kind="today_input", value=dict(today),
             unit="index", source="today's model", feeds=["street.level"], status="live"),
        Step(id="street.level", label="Street level", kind="result", value=dict(today), unit="index", source="",
             formula=f"no street within {int(C.RADIUS_ROADS_M)} m in the road data, today's estimate unchanged",
             status="new"),
    ], evidence=[f"No street lies within {int(C.RADIUS_ROADS_M)} m of this point, so traffic is not adjusted."])


def _upgrade(lat, lng, today):
    st = _state()
    if st is None:
        return passthrough(NAME, today)
    near = st["gi"].near(lat, lng, C.RADIUS_ROADS_M)
    by_name = {}
    for d, s in near:
        lv = today_road_level(s["k"], s["cr"], s["sp"], s["tw"], d)
        cur = by_name.get(s["n"])
        if cur is None or lv > cur[0]:
            by_name[s["n"]] = (lv, d, s)
    if not by_name:
        return _no_road(today)
    ref = st["ref"]
    rows = []
    for name, (lv, d, s) in by_name.items():
        tau = s.get("ta") or st["tau"][s["t"]]
        eff = effective(s["q"], s["b"], tau, heavy_factor(s["k"]))
        r = ref[s["k"]][0]
        rows.append({"name": name, "lv": lv, "d": d, "s": s, "tau": tau, "eff": eff, "ref": r,
                     "delta": [correction_db(eff[i], r[i]) for i in range(3)]})
    rows.sort(key=lambda x: -x["lv"])
    main = rows[0]
    base0 = _energy_sum([r["lv"] for r in rows])
    D, road_today = {}, {}
    for i, slot in enumerate(SLOTS):
        off = C.STREET_WINDOW_OFFSET[slot]
        road_today[slot] = round(base0 + off, 2)
        D[slot] = round(_energy_sum([r["lv"] + r["delta"][i] for r in rows]) - base0, 2)
    levels = {slot: round(today[slot] + D[slot], 2) for slot in SLOTS}
    return Upgrade(levels=levels, steps=_steps(main, rows, today, road_today, D, levels, st), evidence=_evidence(main, st))


def _per_slot(vals, nd=1):
    return {slot: round(vals[i], nd) for i, slot in enumerate(SLOTS)}


def _basis_text(s):
    if s["nv"]:
        return "not a street for vehicles (footpath or bike path): no traffic"
    if s["s"] == 2:
        if s.get("x2"):
            how = "one direction counted, doubled for the other"
        elif s.get("cd", 1) > 1:
            how = "both directions"
        else:
            how = "the one direction of a one-way street"
        return f"counted by NYC DOT in {s.get('cy')} ({how})"
    if s["s"] == 1:
        return f"estimated: nearest count on the same street is {s['ds']} m away, blended with counted streets of the same class"
    return "estimated from counted streets of the same road class (no count on this street)"


def _steps(main, rows, today, road_today, D, levels, st):
    s, tau = main["s"], main["tau"]
    q, b = s["q"], s["b"]
    total = [q[i] + b[i] for i in range(3)]
    eff, ref = main["eff"], main["ref"]
    ref_class, ref_n = st["ref"][s["k"]][1], st["ref"][s["k"]][2]
    delta = {slot: round(main["delta"][i], 2) for i, slot in enumerate(SLOTS)}
    ds = st["doc"]["meta"]
    steps = [
        Step("street.today_level", "Today's street level", "today_input", dict(today), "index", "today's model",
             "", ["street.level"], "live"),
        Step("street.road_class", "Road class of the loudest street", "today_input",
             f"{main['name']}: {s['k'].replace('_', ' ')}, {s['ln']} travel lane{'s' if s['ln'] != 1 else ''}, {int(s['sp'])} mph",
             "", "NYC Street Centerline (inkn-q76z), today's model", "", ["street.road_today", "street.implied_volume"], "live"),
        Step("street.distance", "Distance to that street", "today_input", int(round(main["d"])), "m",
             "NYC Street Centerline (inkn-q76z), today's model", "", ["street.road_today"], "live"),
        Step("street.road_today", "Today's road level", "rule", road_today, "index", "today's model",
             "class base, plus the snow route bump and, on highways and ramps, the speed bump, minus 3 for every "
             "doubling of distance beyond 10 m, energy-summed over the streets within 60 m, plus the hour offset",
             ["street.correction"], "live"),
        Step("street.volume_basis", "Where the traffic number comes from", "new_input", _basis_text(s), "",
             "NYC DOT Automated Traffic Volume Counts (7ym2-wayt)", "", ["street.vehicles_per_hour"], "new"),
        Step("street.vehicles_per_hour", "Vehicles per hour, all types", "new_input", _per_slot(total, 0), "veh/h",
             "NYC DOT Automated Traffic Volume Counts (7ym2-wayt)",
             "weekday average per slot; where uncounted, the counted streets of the same class or the nearest count on the same street",
             ["street.effective_vehicles"], "new"),
        Step("street.truck_route", "Truck route designation", "new_input", ROUTE_LABEL[s["t"]], "",
             "NYC Truck Routes (jjja-shxy)", "", ["street.truck_share"], "new"),
        Step("street.truck_share", "Trucks, share of vehicles other than buses", "new_input",
             {slot: round(100 * tau[i], 1) for i, slot in enumerate(SLOTS)}, "%",
             "NYC DOT Vehicle Classification Counts (96ay-ea4r)",
             "medium and heavy trucks over all vehicles but buses, from the street's own classification count where it has one, "
             "else the pooled share of Manhattan streets with the same truck route designation",
             ["street.effective_vehicles"], "new"),
        Step("street.buses_per_hour", "Scheduled buses per hour", "new_input", _per_slot(b, 1), "buses/h",
             "MTA bus timetables (GTFS static)",
             f"weekday trips per slot divided by its hours, every route whose path runs along this street ({ds['gtfs_date']} timetable)",
             ["street.effective_vehicles"], "new"),
        Step("street.heavy_equivalent", "Cars one truck or bus equals", "new_input", heavy_factor(s["k"]), "cars",
             "NYC CEQR manual (13 medium truck, 18 bus at 25 mph) and FTA 2018 (bus 17.8 cars at 25 mph, 6.3 at 50); "
             "noise research, 2026-10-29",
             f"{K_HEAVY:g} on city streets, {K_HEAVY_HIGHWAY:g} on highways", ["street.effective_vehicles"], "new"),
        Step("street.effective_vehicles", "Effective vehicles per hour", "rule", _per_slot(eff, 0), "veh/h", "street upgrade",
             f"cars + {heavy_factor(s['k']):g} x (trucks + buses), where cars = vehicles other than buses less the trucks",
             ["street.correction"], "new"),
        Step("street.implied_volume", "Volume today's road class implies", "rule", _per_slot(ref, 0), "veh/h",
             f"NYC DOT counts, {ref_n} counted {ref_class.replace('_', ' ')} segments in Manhattan",
             "median effective vehicles per hour of the counted streets in the same road class, per slot",
             ["street.correction"], "new"),
        Step("street.cap", "Largest correction", "new_input", CORRECTION_CAP, "index",
             "judgment, about a factor of four in traffic either way", "", ["street.correction"], "judgment"),
        Step("street.correction", "Correction to today's level", "rule", dict(D), "index", "street upgrade",
             "10 x log10(effective vehicles / implied volume) for each street, capped at plus or minus "
             f"{CORRECTION_CAP:g}; with several streets within 60 m, their corrections are combined weighted by how loud each is today",
             ["street.level"], "new"),
        Step("street.level", "Street level", "result", dict(levels), "index", "", "today's level + the correction", [], "new"),
    ]
    return steps


def _evidence(main, st):
    s = main["s"]
    name = _pretty(main["name"])
    out = []
    q, b = s["q"], s["b"]
    tot = [q[i] + b[i] for i in range(3)]
    if s["nv"]:
        out.append(f"{name} is a footpath or bike path with no motor traffic.")
    elif s["s"] == 2:
        out.append(f"NYC DOT counted about {_round_count(tot[2])} vehicles an hour on {name} by day and about "
                   f"{_round_count(tot[0])} an hour at night ({s['cy']} count).")
    elif s["s"] == 1:
        out.append(f"{name} has no count on this block; the nearest count on the same street, {s['ds']} m away, and similar "
                   f"streets suggest about {_round_count(tot[2])} vehicles an hour by day and {_round_count(tot[0])} at night.")
    else:
        out.append(f"{name} has no traffic count; streets like it carry about {_round_count(tot[2])} vehicles an hour by day "
                   f"and {_round_count(tot[0])} at night.")
    if b[2] >= EVIDENCE_MIN_BUSES:
        out.append(f"About {_round_count(b[2])} buses an hour pass on {name} in the day and {_round_count(b[0])} at night."
                   if b[0] >= 1 else f"About {_round_count(b[2])} buses an hour pass on {name} in the day.")
    tau = main["tau"]
    if s["t"] and tau[2] >= EVIDENCE_MIN_TRUCK_SHARE:
        out.append(f"{name} is {ROUTE_LABEL[s['t']]}; about {int(round(100 * tau[2]))} in 100 daytime vehicles are trucks.")
    elif s["t"]:
        out.append(f"{name} is {ROUTE_LABEL[s['t']]}.")
    return out[:3]
