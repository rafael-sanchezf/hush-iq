"""Sirens upgrade: where emergency vehicles actually drive, averaged with today's distance-to-station estimate.
(Hackathon work, Oct 28.) Plain-words write-up: packages/model/upgrades/sirens.md.

Two estimates of the same sirens, averaged inside this source (never an energy sum):
  today  hospitals, firehouses and police stations within 600 m, 5 dB per doubling (model.py's math with the
         research slope of 2026-10-29, recal.py [V10]; model.py itself, frozen, uses 4).
  routes every Manhattan FDNY fire response, EMS response and hospital transport of Oct 2025 to Sep 2026,
         routed on the OpenStreetMap drive network: passes per street segment per time slot. At an address,
         the passes on nearby segments are weighted by distance, summed per hour, and turned into a level
         with a log whose two constants are fitted so the routes sit on today's scale across the 300
         Manhattan baseline buildings (same median, same spread).
  level  0.5 x today + 0.5 x routes, per slot.

Runtime is pure standard library. Build time (build()) needs osmnx, networkx and shapely and the network.
"""
import ast
import collections
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config_v2 as V
from . import SLOTS, Step, Upgrade, load, passthrough, save
from ._geo import GridIndex, dist_m

NAME = "sirens"

# ---------------------------------------------------------------- constants
SLOT_HOURS = {"night": 7, "early": 3, "day": 14}                 # model.py WINDOWS: 22-5, 5-8, 8-22
CATS = ("fire", "ambulance", "transport")                        # artifact order; 3 slots each, 9 numbers a segment
CAT_LABEL = {"fire": "Fire responses", "ambulance": "Ambulance responses", "transport": "Hospital transports"}
WINDOW_FROM, WINDOW_TO = "2025-10-01", "2026-10-01"              # twelve full months, 365 days
WINDOW_DAYS = 365

RADIUS_M = 300.0          # judgment: about one avenue block each way
REF_M = 30.0              # judgment: distance at which a pass counts half
EXPONENT = 1.33           # judgment: decay between a line source (1) and a point source (2)
MIN_DIST_M = 10.0         # judgment: no pass counts more than at 10 m (street width, setback)
STEP_M = 25.0             # a road piece this long carries one weight unit
STREET_M = 50.0           # "this block": the nearest segment with trips, if within this distance
COVER_M = 500.0           # judgment: farther than this from every routed street, the routes say nothing (outside Manhattan)
MIX = 0.5                 # judgment: today and routes are equally good estimates
LEVEL_FLOOR, LEVEL_CEIL = 35.0, 70.0   # today's no-facility floor and energy-sum cap (config.py), for route levels

SOURCE_FIRE = ("NYC Open Data, Fire Incident Dispatch Data", "8m42-w767", "https://data.cityofnewyork.us/resource/8m42-w767")
SOURCE_EMS = ("NYC Open Data, EMS Incident Dispatch Data", "76xm-jjuj", "https://data.cityofnewyork.us/resource/76xm-jjuj")
SOURCE_BOX = ("NYC Open Data, FDNY alarm box locations", "v57i-gtxb", "https://data.cityofnewyork.us/resource/v57i-gtxb")
SOURCE_COMPANIES = ("NYC Open Data, Fire Companies", "bst7-5464", "https://data.cityofnewyork.us/resource/bst7-5464")
SOURCE_HOUSES = ("NYC Open Data, FDNY Firehouse Listing", "hc8x-tcnd", "https://data.cityofnewyork.us/resource/hc8x-tcnd")
SOURCE_FACDB = ("NYC Open Data, NYC Facilities Database", "67g2-p84d", "https://data.cityofnewyork.us/resource/67g2-p84d")
SOURCE_OSM = ("OpenStreetMap drive network via osmnx", "", "https://www.openstreetmap.org")
# Emergency vehicles prefer wide streets: assumed speed by OSM road class, mph. Judgment (limit 3 in sirens.md).
SPEED_MPH = {"motorway": 45, "trunk": 35, "primary": 30, "secondary": 26, "tertiary": 22}
DEFAULT_MPH = 16


def _slot_of_hour(h):
    return "night" if (h >= 22 or h < 5) else ("early" if h < 8 else "day")


def weight(d):
    """How much a pass at distance d (metres) counts: 1 / (1 + (max(d, 10) / 30) ^ 1.33)."""
    return 1.0 / (1.0 + (max(d, MIN_DIST_M) / REF_M) ** EXPONENT)


# ================================================================ BUILD (offline, network)
def _cache_dir(cache):
    p = Path(cache or os.environ.get("HUSHIQ_BUILD_CACHE") or Path(os.environ.get("TMPDIR", "/tmp")) / "hushiq_sirens_cache")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get(ds, params, page=50000):
    rows, off = [], 0
    while True:
        q = dict(params, **{"$limit": page, "$offset": off})
        url = f"https://data.cityofnewyork.us/resource/{ds}.json?" + urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "hush-iq build"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    batch = json.load(r)
                break
            except Exception as e:   # network hiccup: wait and retry
                print("retry", ds, e, file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"pull failed: {ds}")
        rows += batch
        if len(batch) < page:
            return rows
        off += page


def _pull(cache):
    """The public pulls, cached as JSON in `cache` (delete a file to pull it again)."""
    when = f"incident_datetime >= '{WINDOW_FROM}T00:00:00' AND incident_datetime < '{WINDOW_TO}T00:00:00'"
    jobs = {
        "fire_dispatch": ("8m42-w767", {
            "$select": "alarm_box_number, alarm_box_location, zipcode, date_extract_hh(incident_datetime) as h, "
                       "incident_classification_group as grp, count(*) as n",
            "$where": f"incident_borough='MANHATTAN' AND {when}",
            "$group": "alarm_box_number, alarm_box_location, zipcode, h, grp"}),
        "ems_dispatch": ("76xm-jjuj", {
            "$select": "zipcode, date_extract_hh(incident_datetime) as h, count(*) as n, "
                       "count(first_to_hosp_datetime) as transported",
            "$where": f"borough='MANHATTAN' AND {when}",
            "$group": "zipcode, h"}),
        "alarm_boxes": ("v57i-gtxb", {"$select": "borobox, location, zip, latitude, longitude", "$where": "borough='Manhattan'"}),
        "fire_companies": ("bst7-5464", {}),
        "firehouses": ("hc8x-tcnd", {"$where": "borough='Manhattan'"}),
        "facilities_all": ("67g2-p84d", {
            "$select": "facname, factype, address, boro, latitude, longitude",
            "$where": "factype in('HOSPITAL','ACUTE CARE HOSPITAL','FIREHOUSE','AMBULANCE STATION','POLICE STATION')"}),
    }
    out = {}
    for name, (ds, params) in jobs.items():
        f = cache / f"{name}.json"
        if not f.exists():
            f.write_text(json.dumps(_get(ds, params)))
        out[name] = json.loads(f.read_text())
    return out


def _graph(cache):
    import osmnx as ox
    g = cache / "manhattan_drive.graphml"
    if g.exists():
        G = ox.load_graphml(g)
    else:
        ox.settings.cache_folder = str(cache / "osmnx")
        G = ox.graph_from_place("Manhattan, New York County, New York, USA", network_type="drive")
        ox.save_graphml(G, g)
    for u, v, k, d in G.edges(keys=True, data=True):
        hw = d.get("highway")
        if isinstance(hw, str) and hw.startswith("["):
            hw = ast.literal_eval(hw)   # osmnx writes merged classes as a list literal
        hw = hw[0] if isinstance(hw, list) else hw
        mph = SPEED_MPH.get(str(hw).replace("_link", ""), DEFAULT_MPH)
        d["tt"] = float(d["length"]) / (mph * 0.44704)
    return G


def _route(raw, G):
    """Passes per directed edge per slot and category, and the station-door legs, from the pulled dispatch data.
    Returns (passes, stubs, stats)."""
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    norm = lambda s: re.sub(r"\s+", " ", (s or "").upper().strip())
    boxes, box_by_loc = {}, {}
    for b in raw["alarm_boxes"]:
        if b.get("latitude"):
            xy = (float(b["latitude"]), float(b["longitude"]))
            boxes[b["borobox"]] = xy
            box_by_loc.setdefault(norm(b["location"]), xy)

    def locate(r):
        return boxes.get("M" + str(r.get("alarm_box_number", "")).zfill(4)) or box_by_loc.get(norm(r.get("alarm_box_location")))

    # first-due firehouse: the engine company whose district holds the box
    houses = []
    for f in raw["firehouses"]:
        engines = [int(x) for x in re.findall(r"Engine\s+(\d+)", f["facilityname"])]
        houses.append({"name": f["facilityname"], "lat": float(f["latitude"]), "lng": float(f["longitude"]), "engines": engines})
    engine_house = {e: h for h in houses for e in h["engines"]}
    polys, owners = [], []
    for c in raw["fire_companies"]:
        if c["fire_co_type"] == "E" and int(c["fire_co_num"]) in engine_house:
            polys.append(shape(c["the_geom"]))
            owners.append(engine_house[int(c["fire_co_num"])])
    tree = STRtree(polys)

    def first_due(lat, lng):
        p = Point(lng, lat)
        for i in tree.query(p):
            if polys[i].contains(p):
                return owners[i]
        return min(houses, key=lambda h: (h["lat"] - lat) ** 2 + ((h["lng"] - lng) * 0.76) ** 2)

    fac = [f for f in raw["facilities_all"] if f.get("latitude") and (f.get("boro") or "").upper() == "MANHATTAN"]
    hospitals = [{"name": f["facname"], "lat": float(f["latitude"]), "lng": float(f["longitude"])} for f in fac
                 if f["factype"] in ("HOSPITAL", "ACUTE CARE HOSPITAL")]
    amb = [{"name": f["facname"], "lat": float(f["latitude"]), "lng": float(f["longitude"])} for f in fac
           if f["factype"] == "AMBULANCE STATION"] + hospitals
    near = lambda pts, lat, lng: min(pts, key=lambda h: (h["lat"] - lat) ** 2 + ((h["lng"] - lng) * 0.76) ** 2)

    # trips: (origin, call location, slot) -> count
    fire_trips, amb_trips, transports = collections.Counter(), collections.Counter(), collections.Counter()
    fire_total = fire_unplaced = 0
    med_by_zip = collections.defaultdict(collections.Counter)   # where medical calls happen inside each zip
    for r in raw["fire_dispatch"]:
        n, h, loc = int(r["n"]), int(r["h"]), locate(r)
        fire_total += n
        if not loc:
            fire_unplaced += n
            continue
        fire_trips[(("house", first_due(*loc)["name"]), loc, _slot_of_hour(h))] += n
        if r["grp"] and r["grp"].startswith("Medical"):
            med_by_zip[r.get("zipcode")][loc] += n
    ems_total = ems_unplaced = 0
    for r in raw["ems_dispatch"]:
        z, h, n, t = r.get("zipcode"), int(r["h"]), int(r["n"]), int(r["transported"])
        ems_total += n
        dist = med_by_zip.get(z)
        if not dist:
            ems_unplaced += n
            continue
        tot = sum(dist.values())
        for loc, c in dist.items():
            share = c / tot
            amb_trips[(("amb", near(amb, *loc)["name"]), loc, _slot_of_hour(h))] += n * share
            transports[(loc, ("hosp", near(hospitals, *loc)["name"]), _slot_of_hour(h))] += t * share

    named = {("house", h["name"]): (h["lat"], h["lng"]) for h in houses}
    named.update({("amb", a["name"]): (a["lat"], a["lng"]) for a in amb})
    named.update({("hosp", h["name"]): (h["lat"], h["lng"]) for h in hospitals})
    nodecache = {}

    def nd(x):
        if x not in nodecache:
            lat, lng = named[x] if x in named else x
            nodecache[x] = int(ox.distance.nearest_nodes(G, float(lng), float(lat)))
        return nodecache[x]

    Gr = G.reverse(copy=False)
    cheapest = lambda u, v, d: min(e["tt"] for e in d.values())

    def push(graph, src, demand, reverse, passes):
        pred, dist = nx.dijkstra_predecessor_and_distance(graph, src, weight=cheapest)
        acc = collections.defaultdict(collections.Counter)
        for n_, slots in demand.items():
            acc[n_].update(slots)
        for n_ in sorted(dist, key=lambda x: -dist[x]):
            if n_ == src or not acc.get(n_) or not pred.get(n_):
                continue
            p = pred[n_][0]
            key = (n_, p) if reverse else (p, n_)
            for s, c in acc[n_].items():
                passes[key][s] += c
            acc[p].update(acc[n_])

    new = lambda: collections.defaultdict(lambda: {"night": 0.0, "early": 0.0, "day": 0.0})
    passes = {"fire": new(), "ambulance": new(), "transport": new()}
    for cat, trips in (("fire", fire_trips), ("ambulance", amb_trips)):
        by_origin = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
        for (o, d, s), c in trips.items():
            by_origin[nd(o)][nd(d)][s] += c
        for src, demand in by_origin.items():
            push(G, src, demand, False, passes[cat])
    by_hosp = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for (o, d, s), c in transports.items():
        by_hosp[nd(d)][nd(o)][s] += c
    for dst, demand in by_hosp.items():
        push(Gr, dst, demand, True, passes["transport"])

    # The last leg between a station's door and the nearest intersection (median 64 m for a firehouse): routes
    # start and end at street nodes, so without this leg the block in front of a station would carry no trips.
    stubs = {}

    def stub(key, cat, slot, n):
        lat, lng = named[key]
        st = stubs.setdefault((lat, lng), {"name": key[1], "node": nd(key), "counts": [0.0] * 9})
        st["counts"][CATS.index(cat) * 3 + SLOTS.index(slot)] += n

    for (o, _d, s), c in fire_trips.items():
        stub(o, "fire", s, c)
    for (o, _d, s), c in amb_trips.items():
        stub(o, "ambulance", s, c)
    for (_o, d, s), c in transports.items():
        stub(d, "transport", s, c)

    stats = {"fire_incidents": fire_total, "fire_unplaced": fire_unplaced, "ems_incidents": ems_total,
             "ems_unplaced": ems_unplaced, "trips": {"fire": round(sum(fire_trips.values())),
                                                     "ambulance": round(sum(amb_trips.values())),
                                                     "transport": round(sum(transports.values()))},
             "hospitals": len(hospitals), "ambulance_origins": len(amb), "firehouses": len(houses)}
    return passes, stubs, stats


def _segments(G, passes, stubs=()):
    """Merge directed edges into street segments (both directions summed, endpoints as lat/lng), then add the
    station-door legs as short segments from the station to its nearest intersection."""
    seg = {}
    for ci, cat in enumerate(CATS):
        for (u, v), sl in passes[cat].items():
            a = seg.setdefault((min(u, v), max(u, v)), [0.0] * 9)
            for si, s in enumerate(SLOTS):
                a[ci * 3 + si] += sl[s]
    names, name_ix, rows = [], {}, []

    def name_of(nm):
        if nm not in name_ix:
            name_ix[nm] = len(names)
            names.append(nm)
        return name_ix[nm]

    for (u, v), a in sorted(seg.items()):
        counts = [int(round(x)) for x in a]
        if not any(counts):
            continue
        d = min(G[u][v].values(), key=lambda e: e["length"]) if G.has_edge(u, v) else min(G[v][u].values(), key=lambda e: e["length"])
        nm = d.get("name")
        nm = nm[0] if isinstance(nm, list) else nm
        rows.append([round(G.nodes[u]["y"], 6), round(G.nodes[u]["x"], 6), round(G.nodes[v]["y"], 6),
                     round(G.nodes[v]["x"], 6), name_of(nm), counts])
    for (lat, lng), st in sorted(stubs.items() if isinstance(stubs, dict) else stubs):
        n = st["node"]
        counts = [int(round(x)) for x in st["counts"]]
        if any(counts) and dist_m(lat, lng, G.nodes[n]["y"], G.nodes[n]["x"]) >= 5:
            rows.append([round(lat, 6), round(lng, 6), round(G.nodes[n]["y"], 6), round(G.nodes[n]["x"], 6),
                         name_of(f"{st['name']} (station door)"), counts])
    return rows, names


def _facilities(raw):
    """Facility kinds as model.py reads them (config.SIRENS_KINDS), citywide, for the nearest-distance steps."""
    kinds = {"HOSPITAL": "hospital", "ACUTE CARE HOSPITAL": "hospital", "FIREHOUSE": "fire",
             "AMBULANCE STATION": "fire", "POLICE STATION": "police"}
    out = {"hospital": [], "fire": [], "police": []}
    for f in raw["facilities_all"]:
        if f.get("latitude") and f.get("longitude") and f["factype"] in kinds:
            out[kinds[f["factype"]]].append([round(float(f["latitude"]), 6), round(float(f["longitude"]), 6), f.get("facname")])
    return out


def _baseline_samples():
    p = Path(__file__).resolve().parent.parent / "data" / "manhattan_baseline.json"
    return json.loads(p.read_text())["samples"]


def _wquantile(pairs, q):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total - 1e-9:
            return v
    return pairs[-1][0]


def recalibrate():
    """Refit the built artifact's calibration to today's levels with the research numbers (recal_sample.json), so
    routes and today stay on one scale [V10]. Offline; rewrites sirens.json.gz."""
    from .. import recal
    doc, start = load(NAME), recal.sample()
    if doc is None or start is None:
        raise RuntimeError("needs data/upgrades/sirens.json.gz and recal_sample.json")
    samples = [dict(s, levels=start[s["bbl"]]) for s in _baseline_samples()]
    doc["calibration"] = calibrate(doc, samples)
    save(NAME, doc)
    _set_artifact(None)
    return doc["calibration"]


def calibrate(doc, samples=None):
    """Fit level = a + b x log10(rate + eps) so route levels match today's median and spread over the baseline.

    Pooled over the three slots and the 300 baseline buildings (weights = building weights). Spread is the
    interquartile range, which the cap at 70 and the 35 floor of today's estimate cannot distort."""
    samples = samples or _baseline_samples()
    idx = _Index(doc)
    eps = doc["calibration"]["eps"]
    xs, ys = [], []
    for s in samples:
        r = idx.rates(s["lat"], s["lng"])
        if not r["covered"]:
            continue
        rate = r["total"]
        for sl in SLOTS:
            xs.append((math.log10(rate[sl] + eps), s.get("weight", 1)))
            ys.append((s["levels"]["sirens"][sl], s.get("weight", 1)))
    mx, my = _wquantile(xs, 0.5), _wquantile(ys, 0.5)
    sx = _wquantile(xs, 0.75) - _wquantile(xs, 0.25)
    sy = _wquantile(ys, 0.75) - _wquantile(ys, 0.25)
    b = sy / sx
    a = my - b * mx
    return {"a": round(a, 3), "b": round(b, 3), "eps": eps,
            "target": {"median": round(my, 3), "iqr": round(sy, 3)}, "log_median": round(mx, 4), "log_iqr": round(sx, 4)}


def build(out_dir, cache=None):
    """Pull the public data, route every response, write sirens.json.gz into out_dir. Needs the network, osmnx,
    networkx and shapely (not part of the API's runtime). Raw pulls and the street graph are cached in `cache`
    (or $HUSHIQ_BUILD_CACHE) so a rerun is offline."""
    out_dir = Path(out_dir)
    cache = _cache_dir(cache)
    raw = _pull(cache)
    G = _graph(cache)
    passes, stubs, stats = _route(raw, G)
    segments, names = _segments(G, passes, stubs)
    doc = {
        "name": NAME, "built": dt.date.today().isoformat(), "window": [WINDOW_FROM, WINDOW_TO], "days": WINDOW_DAYS,
        "cats": list(CATS), "slots": list(SLOTS), "slot_hours": SLOT_HOURS,
        "datasets": [{"name": n, "id": i, "url": u} for n, i, u in
                     (SOURCE_FIRE, SOURCE_EMS, SOURCE_BOX, SOURCE_COMPANIES, SOURCE_HOUSES, SOURCE_FACDB, SOURCE_OSM)],
        "stats": stats, "names": names, "segments": segments, "facilities": _facilities(raw),
        "params": {"radius_m": RADIUS_M, "ref_m": REF_M, "exponent": EXPONENT, "min_dist_m": MIN_DIST_M, "step_m": STEP_M,
                   "street_m": STREET_M, "cover_m": COVER_M, "mix": MIX, "floor": LEVEL_FLOOR, "ceil": LEVEL_CEIL},
        "calibration": {"eps": 0.01},
    }
    doc["calibration"] = calibrate(doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / f"{NAME}.json.gz", "wt") as f:
        json.dump(doc, f, separators=(",", ":"))
    return doc


# ================================================================ RUNTIME (pure Python, no network)
DOOR = "(station door)"


class _Index:
    """Segments and their 25 m pieces on a grid, plus the facilities, built once from the artifact."""

    def __init__(self, doc):
        self.doc = doc
        p = doc.get("params", {})
        self.radius = float(p.get("radius_m", RADIUS_M))
        self.step = float(p.get("step_m", STEP_M))
        self.street_m = float(p.get("street_m", STREET_M))
        self.cover = float(p.get("cover_m", COVER_M))
        self.days = float(doc.get("days", WINDOW_DAYS))
        self.seg = doc["segments"]
        names = doc.get("names", [])
        self.pieces = GridIndex()      # every segment, cut into pieces, for the distance-weighted sum
        self.streets = GridIndex()     # real streets only (not station-door legs), for "this block"
        for i, (la, ln, lb, lc, nm, _c) in enumerate(self.seg):
            L = dist_m(la, ln, lb, lc)
            n = max(1, int(math.ceil(L / self.step)))
            pw = (L / n) / self.step
            for j in range(n):
                t = (j + 0.5) / n
                self.pieces.add_point(la + t * (lb - la), ln + t * (lc - ln), (i, pw, j))
            if not (nm is not None and nm < len(names) and str(names[nm]).endswith(DOOR)):
                self.streets.add_segment(la, ln, lb, lc, (i,))
        self.fac = {k: [(r[0], r[1], r[2]) for r in v] for k, v in doc.get("facilities", {}).items()}

    def rates(self, lat, lng):
        """Distance-weighted trips per hour in each slot, per category and in total (route exposure), and whether
        any routed street lies within `cover_m` (when none does, the routes say nothing about this point)."""
        hours = self.doc.get("slot_hours", SLOT_HOURS)
        acc = [0.0] * 9
        hits = self.pieces.near(lat, lng, self.cover)
        for d, (i, pw, _j) in hits:
            if d > self.radius:
                break          # nearest first
            w = pw * weight(d)
            c = self.seg[i][5]
            for k in range(9):
                if c[k]:
                    acc[k] += w * c[k]
        out = {c: {} for c in CATS}
        out["total"] = {}
        out["covered"] = bool(hits)
        for si, s in enumerate(SLOTS):
            per = self.days * hours[s]
            tot = 0.0
            for ci, c in enumerate(CATS):
                out[c][s] = acc[ci * 3 + si] / per
                tot += out[c][s]
            out["total"][s] = tot
        return out

    def per_day(self, i):
        """Trips a day on segment i, both directions: {category: n}."""
        c = self.seg[i][5]
        return {k: sum(c[ci * 3:ci * 3 + 3]) / self.days for ci, k in enumerate(CATS)}

    def street(self, lat, lng):
        """The nearest street segment with trips within `street_m`: (distance, index) or None."""
        hit = self.streets.near(lat, lng, self.street_m)
        return (hit[0][0], hit[0][1][0]) if hit else None

    def busiest(self, lat, lng):
        """Trips a day on the busiest street segment within the radius, all categories."""
        best = 0.0
        for _d, (i,) in self.streets.near(lat, lng, self.radius):
            best = max(best, sum(self.seg[i][5]) / self.days)
        return best

    def nearest(self, kind, lat, lng):
        best = None
        for la, ln, nm in self.fac.get(kind, ()):
            d = dist_m(lat, lng, la, ln)
            if best is None or d < best[0]:
                best = (d, nm)
        return best


_cached = {"doc": None, "idx": None, "done": False}


def _set_artifact(doc):
    """Use this artifact instead of the file on disk (tests); None clears it so the file is read again."""
    _cached["doc"], _cached["idx"], _cached["done"] = doc, (_Index(doc) if doc else None), doc is not None


def _index():
    if not _cached["done"]:
        _cached["done"] = True
        try:
            doc = load(NAME)
            _cached["doc"], _cached["idx"] = (doc, _Index(doc)) if doc else (None, None)
        except Exception:
            _cached["doc"], _cached["idx"] = None, None
    return _cached["idx"]


def route_level(rate_total, cal, params):
    """Calibrated log of the weighted trips per hour, kept inside today's range."""
    x = math.log10(rate_total + cal["eps"])
    return min(params.get("ceil", LEVEL_CEIL), max(params.get("floor", LEVEL_FLOOR), cal["a"] + cal["b"] * x))


def _r(x, n=1):
    return round(float(x), n)


def _about(x):
    """A trip count a renter can read: 3.4 -> 3, 47 -> 45, 212 -> 210."""
    if x < 10:
        return max(1, int(round(x)))
    return int(round(x / 5.0)) * 5 if x < 100 else int(round(x, -1))


def _metres(d):
    return "under 10 m" if d < 10 else f"{int(round(d, -1))} m"


def upgrade(lat, lng, today, facts):
    """Combined sirens level per slot, the math-board steps and the renter-facing sentences. Never raises."""
    try:
        slots_today = {s: float((today or {}).get(s, LEVEL_FLOOR)) for s in SLOTS}
    except Exception:
        slots_today = {s: LEVEL_FLOOR for s in SLOTS}
    try:
        idx = _index()
        if idx is None or lat is None or lng is None or not (math.isfinite(lat) and math.isfinite(lng)):
            return passthrough(NAME, slots_today)
        return _upgrade(idx, float(lat), float(lng), slots_today)
    except Exception:
        return passthrough(NAME, slots_today)


def _upgrade(idx, lat, lng, today):
    doc = idx.doc
    p, cal = doc["params"], doc["calibration"]
    mix = float(p.get("mix", MIX))
    rates = idx.rates(lat, lng)
    if not rates["covered"]:
        return Upgrade(levels=dict(today), steps=[
            Step(id="sirens.today_level", label="Today's sirens level (distance to stations)", kind="today_input",
                 value=dict(today), unit="index", source="today's model", feeds=["sirens.level"], status="live"),
            Step(id="sirens.level", label="Sirens level", kind="result", value=dict(today), unit="index", source="",
                 formula=f"no emergency route within {idx.cover:g} m of this address in the Manhattan route data, "
                         "so today's estimate is unchanged", status="live")])
    route = {s: route_level(rates["total"][s], cal, p) for s in SLOTS}
    combined = {s: (1 - mix) * today[s] + mix * route[s] for s in SLOTS}

    st = idx.street(lat, lng)
    street = idx.per_day(st[1]) if st else {c: 0.0 for c in CATS}
    busiest = idx.busiest(lat, lng)
    hosp, fire, police = (idx.nearest(k, lat, lng) for k in ("hospital", "fire", "police"))
    ds = lambda x: (x[0] if x else None)

    steps = []
    add = steps.append
    facdata = "NYC Facilities Database (67g2-p84d)"
    # ---- today's inputs (live)
    add(Step(id="sirens.hospital_m", label="Nearest hospital", kind="today_input", value=_r(ds(hosp), 0) if hosp else None,
             unit="m", source=facdata, formula="straight-line distance to the nearest hospital",
             feeds=["sirens.today_level"], status="live"))
    add(Step(id="sirens.firehouse_m", label="Nearest firehouse or ambulance station", kind="today_input",
             value=_r(ds(fire), 0) if fire else None, unit="m", source=facdata,
             formula="straight-line distance to the nearest firehouse or ambulance station",
             feeds=["sirens.today_level"], status="live"))
    add(Step(id="sirens.police_m", label="Nearest police station", kind="today_input",
             value=_r(ds(police), 0) if police else None, unit="m", source=facdata,
             formula="straight-line distance to the nearest police station", feeds=["sirens.today_level"], status="live"))
    add(Step(id="sirens.today_level", label="Today's sirens level (distance to stations)", kind="rule", value=dict(today),
             unit="index", source="today's model",
             formula=f"each hospital, firehouse and police station within 600 m starts at a base level and loses "
                     f"{V.SIRENS_DB_PER_DOUBLING:g} per "
                     "doubling of distance beyond 50 m; the levels are added as energy and capped at 70; night -3, early -2",
             feeds=["sirens.level"], status="live"))
    # ---- new inputs: what drives where
    src_fire = f"{SOURCE_FIRE[0]} ({SOURCE_FIRE[1]}), routed on OpenStreetMap"
    src_ems = f"{SOURCE_EMS[0]} ({SOURCE_EMS[1]}), routed on OpenStreetMap"
    add(Step(id="sirens.street_fire", label="Fire responses on the nearest street", kind="new_input",
             value=_r(street["fire"]), unit="trips/day", source=src_fire,
             formula="fire units sent to calls in the last 12 months, from the first-due firehouse by the quickest "
                     "street route, both directions, per day", feeds=["sirens.near_fire"], status="new"))
    add(Step(id="sirens.street_ambulance", label="Ambulance responses on the nearest street", kind="new_input",
             value=_r(street["ambulance"]), unit="trips/day", source=src_ems,
             formula="ambulances sent to calls, from the nearest hospital or ambulance station, both directions, per day",
             feeds=["sirens.near_ambulance"], status="new"))
    add(Step(id="sirens.street_transport", label="Hospital transports on the nearest street", kind="new_input",
             value=_r(street["transport"]), unit="trips/day", source=src_ems,
             formula="patients taken from the call to the nearest hospital, both directions, per day",
             feeds=["sirens.near_transport"], status="new"))
    add(Step(id="sirens.busiest_street", label="Busiest street within 300 m", kind="new_input", value=_r(busiest),
             unit="trips/day", source=f"{src_fire}; {src_ems}",
             formula="all fire, ambulance and transport trips on the busiest street segment within 300 m, per day",
             feeds=["sirens.exposure"], status="new"))
    for c, short, src in (("fire", "fire responses", SOURCE_FIRE), ("ambulance", "ambulance responses", SOURCE_EMS),
                          ("transport", "hospital transports", SOURCE_EMS)):
        add(Step(id=f"sirens.near_{c}", label=f"{CAT_LABEL[c]} within 300 m, distance-weighted", kind="new_input",
                 value={s: _r(rates[c][s], 3) for s in SLOTS}, unit="trips/h", source=f"routes built from {src[0]} ({src[1]})",
                 formula=f"{short} on every street segment within 300 m, each times its distance weight, added up, "
                         "divided by the hours of the slot over the year", feeds=["sirens.exposure"], status="new"))
    add(Step(id="sirens.radius_m", label="Reach of the street search", kind="rule", value=_r(p["radius_m"], 0), unit="m",
             source="judgment", formula="about one avenue block each way", feeds=["sirens.exposure"], status="judgment"))
    add(Step(id="sirens.decay", label="Distance weight", kind="rule",
             value=f"1 / (1 + (max(d, {p['min_dist_m']:g}) / {p['ref_m']:g}) ^ {p['exponent']:g})", unit="", source="judgment",
             formula="a pass 30 m away counts half of one at the curb; the weight fades faster than a line source "
                     "(exponent 1) and slower than a point source (exponent 2)", feeds=["sirens.exposure"], status="judgment"))
    add(Step(id="sirens.exposure", label="Route exposure", kind="rule", value={s: _r(rates["total"][s], 3) for s in SLOTS},
             unit="trips/h", source="", formula="fire responses + ambulance responses + hospital transports, each "
                                                "weighted by distance, per hour of the slot",
             feeds=["sirens.route_level"], status="new"))
    add(Step(id="sirens.cal_offset", label="Calibration offset", kind="rule", value=cal["a"], unit="index",
             source="judgment: match today's median over the 300 Manhattan baseline buildings",
             formula=f"chosen so the median route level equals today's median ({cal['target']['median']})",
             feeds=["sirens.route_level"], status="judgment"))
    add(Step(id="sirens.cal_scale", label="Calibration scale", kind="rule", value=cal["b"], unit="index",
             source="judgment: match today's spread over the 300 Manhattan baseline buildings",
             formula=f"chosen so the middle half of route levels is as wide as today's ({cal['target']['iqr']})",
             feeds=["sirens.route_level"], status="judgment"))
    add(Step(id="sirens.route_level", label="Route level", kind="rule", value={s: _r(route[s], 2) for s in SLOTS},
             unit="index", source="",
             formula=f"offset + scale x log10(exposure + {cal['eps']:g}), kept between {p['floor']:g} and {p['ceil']:g}",
             feeds=["sirens.level"], status="new"))
    add(Step(id="sirens.mix", label="Share of the route estimate", kind="rule", value=mix, unit="", source="judgment",
             formula="today's estimate and the routes are two guesses at the same sirens, so they are averaged, "
                     "half and half, never added", feeds=["sirens.level"], status="judgment"))
    add(Step(id="sirens.level", label="Sirens level", kind="result", value={s: _r(combined[s], 2) for s in SLOTS},
             unit="index", source="",
             formula="(1 - share) x today's level + share x route level, per slot: an average of two estimates, never a sum",
             status="new"))

    # ---- renter-facing sentences: counts and distances only
    ev = []
    amb, fr = street["ambulance"] + street["transport"], street["fire"]
    hospital_said = False
    if amb >= 0.5:
        n = _about(amb)
        s1 = f"About {n} ambulance trip{'' if n == 1 else 's'} a day pass{'es' if n == 1 else ''} on this block"
        if street["transport"] >= street["ambulance"] and hosp and hosp[0] <= 600:
            s1 += f", most heading to a hospital about {_metres(hosp[0])} away"
            hospital_said = True
        ev.append(s1 + ".")
    if fr >= 0.5:
        n = _about(fr)
        ev.append(f"About {n} fire engine run{'' if n == 1 else 's'} a day {'uses' if n == 1 else 'use'} it"
                  + (" too." if amb >= 0.5 else "."))
    if amb < 0.5 and fr < 0.5:
        ev.append("Almost no ambulance or fire engine trips pass this block.")
        if busiest >= 2:
            ev.append(f"The busiest street within 300 m carries about {_about(busiest)} emergency trips a day.")
    near = []
    if hosp and hosp[0] <= 600 and not hospital_said:
        near.append(f"a hospital about {_metres(hosp[0])} away")
    if fire and fire[0] <= 600:
        near.append(f"a fire or ambulance station about {_metres(fire[0])} away")
    if near:
        ev.append("Nearby: " + " and ".join(near) + ".")
    return Upgrade(levels=combined, steps=steps, evidence=ev[:3])
