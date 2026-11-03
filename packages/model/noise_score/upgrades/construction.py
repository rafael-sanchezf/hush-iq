"""Construction upgrade for engine v2: street work and after-hours work, on top of today's building permits.

Today's construction estimate (model.construction) counts DOB NOW building permits of loud work types and 311
construction complaints, then applies a blanket night offset (-15) and early offset (-3). It misses two things:

  1. Work in the street: Con Ed and other utility openings, city reconstruction, milling and paving, sidewalk
     and curb work. Source: NYC DOT Street Construction Permits 2022 to present (tqtj-sjs8).
  2. Work at night and before 7 am. Source: DOB After Hour Variance Permits (g76y-dcqj), which list the dates
     and hours a site may work outside weekday 7 am to 6 pm, plus night hours stated in the DOT permit text.

The two are merged with today's estimate inside this source, never by adding decibels:
  Day:   street-work intensity (site-years of work within 100 m) lifts the level by the model's own rule of 3 dB
         per doubling, shrunk where today's level is already near its ceiling (311 complaints about street work are
         already in it), and capped.
  Night and early: a night is either a work night, at the working level, or a quiet night, at today's blanket
         level. The share of work nights comes from the variances and permit hours; the level is the energy
         average of the two kinds of night.

Permits are a snapshot (the artifact records its build date) and expire as work ends. Build offline with
build(out_dir); at request time only the standard library is used.
"""
import datetime as dt
import gzip
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from . import DATA, SLOTS, Step, Upgrade, load, passthrough
from ._geo import GridIndex, dist_m

NAME = "construction"

# ------------------------------------------------------------------------------------------------ constants
# Each is "sourced" (a number from a dataset, a standard or today's model) or "judgment" (chosen by us).

# --- copied from today's model (config.py), so the correction starts exactly where today's estimate ends.
BASE_DB = 40.0                 # sourced: today's model, construction base level (CONSTRUCTION_BASE_DB)
DB_PER_DOUBLING = 3.0          # sourced: today's model, dB per doubling of permits (CONSTRUCTION_PERMIT_DB_PER_DOUBLING)
MAX_BUMP_DB = 25.0             # sourced: today's model, the most its permits and complaints can add (CONSTRUCTION_MAX_BUMP_DB)

# --- the window and the reach
WINDOW_DAYS = 365              # sourced: the brief, permits active in the 12 months to the build date
FUTURE_DAYS = 60               # judgment: variances already scheduled this far ahead are listed in the evidence
RADIUS_M = 100.0               # sourced: the brief, "street-work density within about 100 m"
NEAR_M = 20.0                  # judgment: a building centre sits 15 to 25 m from the street centreline, so work on
                               # its own street counts in full; the weight then falls in a straight line to 0 at RADIUS_M

# --- street work (day)
WCLASS_WEIGHT = (0.2, 0.6, 1.0)  # judgment: (light, repair, heavy). Heavy = excavation and reconstruction (jackhammer,
                               # saw, excavator, milling), repair = small openings and sidewalk or curb work, light = test
                               # pits, tree pits, fences. Order of loudness follows FHWA RCNM equipment levels.
ACTIVE_NOW_YEARS = 0.25        # judgment: a permit active on the build date counts as if it ran another 3 months
OVERLAP_DISCOUNT = 0.6         # judgment: street work also draws 311 complaints that today already counts. At today's
                               # ceiling the street lift shrinks to 40% of its size, at the base it counts in full
CAP_DAY_DB = 9.0               # judgment: street work can lift the day level at most 3 doublings (9 dB)
SAMPLE_STEP_M = 25.0           # judgment: a permit on a block is spread along it, one distance sample per 25 m
MAX_SAMPLES = 16               # judgment: at most 16 distance samples per block, to keep a request under a millisecond

# --- after-hours work (night and early)
NIGHT_START_H, NIGHT_END_H = 22.0, 5.0   # sourced: today's model, night = 22:00 to 05:00 (config.WINDOWS)
NIGHT_HOURS = 7.0              # sourced: today's model, length of the night slot (config.WINDOW_HOURS)
EARLY_START_H, EARLY_END_H = 5.0, 7.0    # sourced: today's early slot is 05:00 to 08:00, but 07:00 to 08:00 is legal weekday
                               # work already inside today's -3 offset, so only 05:00 to 07:00 counts as after-hours
EARLY_HOURS = EARLY_END_H - EARLY_START_H
P_MAX = 0.8                    # judgment: a permit is permission, not use; at most 80% of nights count as work nights
REASON_WEIGHT = {              # judgment: how loud the variance work tends to be, from DOB's own reason for the variance
    "City Construction Project": 1.0,
    "Emergency Work": 1.0,
    "Undue Hardship": 0.8,
    "Public Safety": 0.8,
    "Construction activities with minimal noise impact": 0.3,
}
REASON_DEFAULT = 0.8           # judgment: reason missing
ENCLOSED_FACTOR = 0.5          # judgment: work flagged enclosed (inside the building) is half as audible outside
MAX_RANGE_H = 14.0             # judgment: a stated work range longer than 14 hours is a typo in the permit text, ignored
WEEKNIGHT_FACTOR = 5.0 / 7.0   # judgment: "weeknights only" or "Monday to Friday" in a permit text means 5 nights in 7
AHV_STATUS_OK = ("AHV Permit Issued", "Approved")   # sourced: statuses that are an issued variance

# --- the snapshot
STALE_DAYS = 90                # judgment: after 90 days the active-now flags are dropped and the board says rebuild

MAX_SPAN_M = 700.0             # judgment: "from X to Y" farther apart than this is read as the first cross street only
NODE_GAP_M = 40.0              # judgment: two streets whose centreline ends do not meet are taken to cross if within 40 m
ADDRESS_SLACK_M = 60.0         # judgment: a house number is placed on a segment within half a block plus 60 m of its block

KIND_NAMES = ("street opening", "sidewalk", "paving or milling", "crane or shovel")
OWNER_NAMES = ("Con Ed", "city", "utility or contractor")

SOCRATA = "https://data.cityofnewyork.us/resource/{}.json"
DS_PERMITS, DS_AHV, DS_CENTERLINE = "tqtj-sjs8", "g76y-dcqj", "inkn-q76z"


# ------------------------------------------------------------------------------------------------ small maths
def _w_dist(d):
    """Distance weight: 1 within NEAR_M, falling in a straight line to 0 at RADIUS_M."""
    if d <= NEAR_M:
        return 1.0
    if d >= RADIUS_M:
        return 0.0
    return (RADIUS_M - d) / (RADIUS_M - NEAR_M)


def _db_mix(p, work, quiet):
    """Energy average of a work night (level `work`) and a quiet night (level `quiet`), p = share of work nights."""
    return 10.0 * math.log10(p * 10 ** (work / 10.0) + (1.0 - p) * 10 ** (quiet / 10.0))


def _headroom_used(day_level):
    """How near today's day level is to the ceiling its permits and complaints can reach: 0 at the base, 1 at the top."""
    return min(1.0, max(0.0, day_level - BASE_DB) / MAX_BUMP_DB)


def _day_correction(day_level, intensity):
    """3 dB per doubling of street-work intensity (the model's own rule for permits), shrunk where today's level is
    already near its ceiling because street work also reaches today's estimate through 311 complaints; capped."""
    lift = DB_PER_DOUBLING * math.log2(1.0 + intensity)
    return min(CAP_DAY_DB, lift * (1.0 - OVERLAP_DISCOUNT * _headroom_used(day_level)))


def _now():
    return dt.date.today()


# ------------------------------------------------------------------------------------------------ the loaded index
_IDX = None
_TRIED = False


class _Index:
    def __init__(self, doc):
        self.doc = doc
        self.built = dt.date.fromisoformat(doc["built"])
        self.street = GridIndex()
        self.ahv = GridIndex()
        loc = doc["street"]["loc"]
        recs = defaultdict(list)
        for r in doc["street"]["rec"]:
            recs[r[0]].append(r[1:])
        for i, (a, b, c, d) in enumerate(loc):
            payload = [(a, b, c, d), recs.get(i, [])]
            if (a, b) == (c, d):
                self.street.add_point(a, b, payload)
            else:
                self.street.add_segment(a, b, c, d, payload)
        for s in doc["ahv"]:
            self.ahv.add_point(s[0], s[1], s)


def _index():
    global _IDX, _TRIED
    if _IDX is None and not _TRIED:
        _TRIED = True
        try:
            doc = load(NAME)
            if doc:
                _IDX = _Index(doc)
        except Exception:
            _IDX = None
    return _IDX


def _use(doc):
    """Install an artifact in memory (tests, or a fresh build). None clears it."""
    global _IDX, _TRIED
    _TRIED = True
    _IDX = _Index(doc) if doc else None


def _reset():
    global _IDX, _TRIED
    _IDX, _TRIED = None, False


# ------------------------------------------------------------------------------------------------ request time
def _mean_weight(lat, lng, geom):
    """Average distance weight along a segment (or at a point), because the work sits somewhere on the block."""
    a, b, c, d = geom
    if (a, b) == (c, d):
        return _w_dist(dist_m(lat, lng, a, b)), dist_m(lat, lng, a, b)
    length = dist_m(a, b, c, d)
    n = max(1, min(MAX_SAMPLES, int(length / SAMPLE_STEP_M) + 1))
    tot, dmin = 0.0, 1e9
    for i in range(n):
        t = (i + 0.5) / n
        dd = dist_m(lat, lng, a + (c - a) * t, b + (d - b) * t)
        dmin = min(dmin, dd)
        tot += _w_dist(dd)
    return tot / n, dmin


def _street_summary(idx, lat, lng, today_ord):
    """Everything the board needs from the street permits near a point."""
    out = {"sites": 0, "active": 0, "night_sites": 0, "intensity": 0.0, "p_night_keep": 1.0, "p_early_keep": 1.0,
           "nearest_active": None, "reach": 0}
    fresh = today_ord - (idx.built.toordinal()) <= STALE_DAYS
    for _d, payload in idx.street.near(lat, lng, RADIUS_M):
        geom, recs = payload
        wbar, dmin = _mean_weight(lat, lng, geom)
        if wbar <= 0.0:
            continue
        for kind, wc, owner, n, days, act_n, act_end, nhd, ehd in recs:
            wcw = WCLASS_WEIGHT[wc]
            active = bool(act_n) and fresh and idx.built.toordinal() + act_end >= today_ord
            out["sites"] += 1
            out["intensity"] += wcw * wbar * (days / float(WINDOW_DAYS) + (ACTIVE_NOW_YEARS if active else 0.0))
            if active:
                out["active"] += 1
                if out["nearest_active"] is None or dmin < out["nearest_active"][0]:
                    out["nearest_active"] = (dmin, kind, owner, geom[:2] != geom[2:])
            if nhd > 0:
                out["night_sites"] += 1
                out["p_night_keep"] *= 1.0 - min(1.0, wcw * wbar * nhd / (NIGHT_HOURS * WINDOW_DAYS))
            if ehd > 0:
                out["p_early_keep"] *= 1.0 - min(1.0, wcw * wbar * ehd / (EARLY_HOURS * WINDOW_DAYS))
    out["reach"] = out["sites"]
    return out


def _ahv_summary(idx, lat, lng):
    out = {"sites": 0, "nights": 0, "nearest": None, "p_night_keep": 1.0, "p_early_keep": 1.0, "ahead": 0}
    for d, s in idx.ahv.near(lat, lng, RADIUS_M):
        w = _w_dist(d)
        if w <= 0.0:
            continue
        _la, _ln, nights, nh, mornings, eh, last, ahead = s
        out["sites"] += 1
        out["nights"] += nights
        out["ahead"] += ahead
        if nights and (out["nearest"] is None or w * nights > out["nearest"][4]):
            out["nearest"] = (d, nights, last, ahead, w * nights)   # the site that matters most, not merely the nearest
        out["p_night_keep"] *= 1.0 - min(1.0, w * nh / (NIGHT_HOURS * WINDOW_DAYS))
        out["p_early_keep"] *= 1.0 - min(1.0, w * eh / (EARLY_HOURS * WINDOW_DAYS))
    return out


def _away(d):
    return "within 10 m" if d < 10 else f"{int(round(d, -1))} m away"


def _evidence(street, ahv, built, window_note):
    ev = []
    na = street["nearest_active"]
    if na:
        d, kind, owner, block = na
        where = f"on a block {_away(d)}" if block else _away(d)
        ev.append(f"A {OWNER_NAMES[owner]} {KIND_NAMES[kind]} permit is active {where}.")
    if street["sites"]:
        s = f"{street['sites']} street-work sites within {int(RADIUS_M)} m in the past year"
        if street["night_sites"]:
            s += f", {street['night_sites']} with night hours in the permit"
        ev.append(s + ".")
    if ahv["nearest"]:
        d, nights, last, ahead, _score = ahv["nearest"]
        s = f"An after-hours variance {_away(d)} allowed night work on {nights} nights in the past year"
        if ahead:
            s += f", with {ahead} more scheduled"
        ev.append(s + ".")
    if not ev:
        ev.append(f"No DOT street-work permits or after-hours variances within {int(RADIUS_M)} m in the {window_note}.")
    return ev[:3]


def upgrade(lat, lng, today, facts):
    try:
        return _upgrade(lat, lng, today, facts)
    except Exception:   # an upgrade must never take the score down
        try:
            return passthrough(NAME, {s: float(today.get(s, 0.0)) for s in SLOTS})
        except Exception:
            return passthrough(NAME, {s: 0.0 for s in SLOTS})


def _upgrade(lat, lng, today, facts):
    t = {s: float(today[s]) for s in SLOTS}
    idx = _index()
    if idx is None:
        return passthrough(NAME, t)
    now = _now()
    today_ord = now.toordinal()
    age = today_ord - idx.built.toordinal()
    street = _street_summary(idx, float(lat), float(lng), today_ord)
    ahv = _ahv_summary(idx, float(lat), float(lng))

    used = _headroom_used(t["day"])
    corr = _day_correction(t["day"], street["intensity"])
    day_up = t["day"] + corr

    p_night = min(P_MAX, 1.0 - street["p_night_keep"] * ahv["p_night_keep"])
    p_early = min(P_MAX, 1.0 - street["p_early_keep"] * ahv["p_early_keep"])
    night_up = _db_mix(p_night, day_up, t["night"]) if p_night > 0 else t["night"]
    early_up = _db_mix(p_early, day_up, t["early"]) if p_early > 0 else t["early"]
    levels = {"night": round(night_up, 3), "early": round(early_up, 3), "day": round(day_up, 3)}

    built = idx.built.isoformat()
    stale = age > STALE_DAYS
    snap = f"{built}, {max(age, 0)} days old" + (", stale: active-now flags dropped, rebuild" if stale else "")
    r = lambda x, n=2: round(x, n)
    steps = [
        Step("construction.today", "Today's construction level", "today_input", {s: r(t[s], 1) for s in SLOTS}, "index",
             "today's model", "DOB building permits of loud work types and 311 construction complaints, then a blanket "
             "night and early offset", ["construction.headroom_used", "construction.day_level", "construction.night_mix",
                                        "construction.early_mix"], "live"),
        Step("construction.blanket_offset", "Today's night and early offsets", "today_input",
             {"night": r(t["night"] - t["day"], 1), "early": r(t["early"] - t["day"], 1)}, "index", "today's model",
             "night = day - 15 and early = day - 3 everywhere; replaced in proportion to the nights with work below",
             ["construction.night_mix", "construction.early_mix"], "live"),
        Step("construction.snapshot", "Permit snapshot", "new_input", snap, "", "NYC DOT Street Construction Permits "
             f"(tqtj-sjs8) and DOB After Hour Variance Permits (g76y-dcqj), Manhattan, {WINDOW_DAYS} days to the build date",
             "Permits are a snapshot: they expire as work ends. An active-now flag lapses at the permit end date and "
             f"after {STALE_DAYS} days the board asks for a rebuild.", ["construction.street_intensity", "construction.night_share"],
             "new"),
        Step("construction.street_sites", "Street-work sites within 100 m", "new_input", street["sites"], "count",
             "NYC DOT Street Construction Permits (tqtj-sjs8)",
             "distinct place, weight class and permittee combinations with a permit in the past 12 months; permits of "
             "several kinds for one job at one place are merged", ["construction.street_intensity"], "new"),
        Step("construction.street_active", "Of those, active now", "new_input", street["active"], "count",
             "NYC DOT Street Construction Permits (tqtj-sjs8)", "a permit running on the build date whose end date has "
             "not passed", ["construction.street_intensity"], "new"),
        Step("construction.street_night_sites", "Of those, with night hours in the permit text", "new_input",
             street["night_sites"], "count", "NYC DOT Street Construction Permits (tqtj-sjs8), stipulation text",
             "permit text such as 'work 11pm-7am nightly'", ["construction.night_share", "construction.early_share"],
             "new"),
        Step("construction.ahv_sites", "After-hours variance sites within 100 m", "new_input", ahv["sites"], "count",
             "DOB After Hour Variance Permits (g76y-dcqj)", "sites with an issued variance in the past 12 months",
             ["construction.night_share", "construction.early_share"], "new"),
        Step("construction.ahv_nights", "Variance nights in the past year", "new_input", ahv["nights"], "count",
             "DOB After Hour Variance Permits (g76y-dcqj)", "nights with variance hours between 10 pm and 5 am, summed "
             "over the sites above", ["construction.night_share"], "new"),
        Step("construction.class_weights", "Weight by kind of street work", "new_input",
             {"heavy": WCLASS_WEIGHT[2], "repair": WCLASS_WEIGHT[1], "light": WCLASS_WEIGHT[0]}, "", "judgment",
             "heavy 1.0 (reconstruction, major installs, milling, paving), repair 0.6, light 0.2 (test pits, tree pits)",
             ["construction.street_intensity", "construction.night_share"], "judgment"),
        Step("construction.distance_weight", "Distance weight", "new_input", f"1 within {int(NEAR_M)} m, 0 at "
             f"{int(RADIUS_M)} m", "", "judgment", f"1 up to {int(NEAR_M)} m, then a straight line down to 0 at "
             f"{int(RADIUS_M)} m; a permit on a block is averaged along the block",
             ["construction.street_intensity", "construction.night_share"], "judgment"),
        Step("construction.active_bonus", "Bonus for work running now", "new_input", ACTIVE_NOW_YEARS, "site-years",
             "judgment", "a permit active on the build date counts as if it ran 3 more months",
             ["construction.street_intensity"], "judgment"),
        Step("construction.street_intensity", "Street-work intensity", "rule", r(street["intensity"], 3), "site-years",
             "NYC DOT Street Construction Permits (tqtj-sjs8)", "sum over sites of kind weight x distance weight x "
             "(days with a permit / 365 + bonus if active now)", ["construction.day_correction"], "new"),
        Step("construction.headroom_used", "How near today's level is to its ceiling", "rule", r(used, 3), "share",
             "today's model", "(today's day level - 40) / 25: the model's base and the most its permits and complaints "
             "can add", ["construction.day_correction"], "new"),
        Step("construction.overlap_discount", "Overlap with 311 complaints", "new_input", OVERLAP_DISCOUNT, "share",
             "judgment", "street work also draws 311 complaints that today already counts, so at today's ceiling the "
             "street lift shrinks by this share", ["construction.day_correction"], "judgment"),
        Step("construction.cap_day", "Cap on the street-work lift", "new_input", CAP_DAY_DB, "index", "judgment",
             "three doublings", ["construction.day_correction"], "judgment"),
        Step("construction.day_correction", "Day correction from street work", "rule", r(corr, 2), "index",
             "today's model (3 dB per doubling) and judgment",
             "3 x log2(1 + street intensity) x (1 - overlap share x how near today is to its ceiling), at most the cap", ["construction.day_level"], "new"),
        Step("construction.day_level", "Day level, working", "rule", r(day_up, 2), "index", "judgment",
             "today's day level + day correction; also the level of a work night",
             ["construction.night_mix", "construction.early_mix", "construction.level"], "new"),
        Step("construction.reason_weights", "Weight by reason for the variance", "new_input", dict(REASON_WEIGHT),
             "", "judgment", f"city or emergency 1.0, hardship or public safety 0.8, minimal noise 0.3, enclosed work x "
             f"{ENCLOSED_FACTOR}; permit text 'weeknights only' x {r(WEEKNIGHT_FACTOR, 2)}",
             ["construction.night_share", "construction.early_share"], "judgment"),
        Step("construction.p_max", "Most nights that can count as work nights", "new_input", P_MAX, "share", "judgment",
             "a permit is permission, not use", ["construction.night_share", "construction.early_share"], "judgment"),
        Step("construction.night_share", "Share of nights with work", "rule", r(p_night, 3), "share",
             "DOB After Hour Variance Permits (g76y-dcqj); DOT permit text",
             "1 - product over sites of (1 - distance weight x kind weight x night hours with a permit / (7 x 365)), "
             f"at most {P_MAX}", ["construction.night_mix"], "new"),
        Step("construction.early_share", "Share of early mornings with work", "rule", r(p_early, 3), "share",
             "DOB After Hour Variance Permits (g76y-dcqj); DOT permit text",
             "the same, for 5 am to 7 am only (7 to 8 am is legal weekday work, already in today's early level)",
             ["construction.early_mix"], "new"),
        Step("construction.night_mix", "Night level", "rule", r(levels["night"], 2), "index", "judgment",
             "energy average: share of work nights at the day level, the rest at today's quiet night level",
             ["construction.level"], "new"),
        Step("construction.early_mix", "Early level", "rule", r(levels["early"], 2), "index", "judgment",
             "energy average: share of work mornings at the day level, the rest at today's early level",
             ["construction.level"], "new"),
        Step("construction.level", "Construction level", "result", {s: r(levels[s], 2) for s in SLOTS}, "index", "",
             "per slot: the day level with street work, night and early mixed with their work-night shares", [], "new"),
    ]
    window_note = f"{WINDOW_DAYS} days to {built}"
    return Upgrade(levels=levels, steps=steps, evidence=_evidence(street, ahv, built, window_note))


# ================================================================================================ build (offline)
_ABBR = {"EAST": "E", "WEST": "W", "NORTH": "N", "SOUTH": "S", "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD",
         "PLACE": "PL", "BOULEVARD": "BLVD", "DRIVE": "DR", "SQUARE": "SQ", "TERRACE": "TER", "PARKWAY": "PKWY",
         "EXPRESSWAY": "EXPY", "COURT": "CT", "LANE": "LN", "ALLEY": "ALY", "PLAZA": "PLZ", "HIGHWAY": "HWY",
         "BRIDGE": "BRG", "FORT": "FT", "SAINT": "ST", "MOUNT": "MT", "HEIGHTS": "HTS", "AVENUES": "AVE", "GARDENS": "GDNS"}
_ALIAS = {"AVE OF THE AMERICAS": "6 AVE", "CENTRAL PARK WEST": "CENTRAL PARK W", "ADAM CLAYTON POWELL JR BLVD": "7 AVE",
          "FREDERICK DOUGLASS BLVD": "8 AVE", "MALCOLM X BLVD": "LENOX AVE", "F D R DR": "FDR DR",
          "JOE DIMAGGIO HWY": "FDR DR", "W 110 ST": "CATHEDRAL PKWY"}


def _norm(name):
    s = re.sub(r"[^A-Z0-9/ ]", " ", (name or "").upper())
    s = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", s)
    toks = [_ABBR.get(t, t) for t in s.split()]
    s = " ".join(toks)
    return _ALIAS.get(s, s)


def _hn(s):
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else None


def _key(lat, lng):
    return round(lat, 5), round(lng, 5)


class _Centerline:
    """NYC street centreline (inkn-q76z): intersections by shared segment ends, house numbers by address range."""

    def __init__(self, rows):
        self.segs = defaultdict(list)     # name -> [(lat1, lng1, lat2, lng2, ranges)]
        self.nodes = defaultdict(dict)    # name -> {node key: (lat, lng)}
        self.cache = {}
        for r in rows:
            g = (r.get("the_geom") or {}).get("coordinates") or []
            if not g or not g[0]:
                continue
            name = _norm(r.get("full_street_name"))
            if not name:
                continue
            (x1, y1), (x2, y2) = g[0][0], g[-1][-1]
            rng = [(_hn(r.get("l_low_hn")), _hn(r.get("l_high_hn"))), (_hn(r.get("r_low_hn")), _hn(r.get("r_high_hn")))]
            self.segs[name].append((y1, x1, y2, x2, rng))
            self.nodes[name][_key(y1, x1)] = (y1, x1)
            self.nodes[name][_key(y2, x2)] = (y2, x2)

    def crossings(self, a, b):
        k = (a, b) if a < b else (b, a)
        if k in self.cache:
            return self.cache[k]
        na, nb = self.nodes.get(a, {}), self.nodes.get(b, {})
        out = [na[x] for x in na if x in nb]
        if not out and na and nb:   # ends that do not quite meet: the closest pair within 40 m
            best = min(((dist_m(*p, *q), p) for p in na.values() for q in nb.values()), key=lambda x: x[0])
            if best[0] <= NODE_GAP_M:
                out = [best[1]]
        self.cache[k] = out
        return out

    def by_address(self, name, hn, near, max_m):
        """The point for a house number on `name` closest to `near` (lat, lng), by interpolating the address range."""
        best = None
        for (y1, x1, y2, x2, rng) in self.segs.get(name, []):
            for lo, hi in rng:
                if lo is None or hi is None or hi < lo or not (lo <= hn <= hi) or (hn - lo) % 2:
                    continue
                t = 0.5 if hi == lo else (hn - lo) / float(hi - lo)
                p = (y1 + (y2 - y1) * t, x1 + (x2 - x1) * t)
                d = dist_m(near[0], near[1], *p)
                if d <= max_m and (best is None or d < best[0]):
                    best = (d, p)
        return best[1] if best else None


def _place(cl, on, frm, to, hn):
    """(lat1, lng1, lat2, lng2) for a permit, or None. A point when the end is unknown."""
    a = _norm(on)
    if a not in cl.segs:
        return None
    f = cl.crossings(a, _norm(frm)) if frm else []
    t = cl.crossings(a, _norm(to)) if to else []
    if f and t:
        d, p, q = min(((dist_m(*p, *q), p, q) for p in f for q in t), key=lambda x: x[0])
        geom = (p[0], p[1], q[0], q[1]) if 0 < d <= MAX_SPAN_M else (p[0], p[1], p[0], p[1])
    elif f or t:
        p = (f or t)[0]
        geom = (p[0], p[1], p[0], p[1])
    else:
        return None
    n = _hn(hn)
    if n is not None:
        mid = ((geom[0] + geom[2]) / 2, (geom[1] + geom[3]) / 2)
        reach = dist_m(geom[0], geom[1], geom[2], geom[3]) / 2 + ADDRESS_SLACK_M
        p = cl.by_address(a, n, mid, reach)
        if p:
            geom = (p[0], p[1], p[0], p[1])
    return geom


# --- permit text: hours of work stated in the DOT stipulation
_T = r"(\d{1,2})(?::?(\d\d))?\s*:?\s*([AP])\.?\s*M"
_RANGE = re.compile(r"(?<!NO )(?<!NO\s)\bWORK(?:ING)?(?:\s+HOURS?)?(?:\s+MAY\s+OCCUR)?(?:\s+FROM)?[:\s]*" + _T
                    + r"\s*(?:-|TO|THROUGH|UNTIL|\u2013)\s*" + _T, re.I)


def _hr(h, m, ap):
    h = int(h) % 12 + (12 if ap.upper() == "P" else 0)
    return h + (int(m) / 60.0 if m else 0.0)


def _overlap(a, b, lo, hi):
    return max(0.0, min(b, hi) - max(a, lo))


def _permit_hours(text):
    """(night hours, early hours) per night that the permit text allows, after-hours only. Night = 22:00 to 05:00 and
    early = 05:00 to 07:00. Several ranges are merged on a half-hour grid; 'weeknights' or Monday to Friday x 5/7."""
    if not text or not re.search(r"\d\s*[AP]\.?\s*M", text, re.I):
        return 0.0, 0.0
    t = text.upper()
    grid = [False] * 48
    for m in _RANGE.finditer(t):
        if re.search(r"SHUT|EMERGENC", t[m.end():m.end() + 45]):   # "may work 8PM-6AM for water shut downs": occasional
            continue
        a = _hr(m.group(1), m.group(2), m.group(3))
        b = _hr(m.group(4), m.group(5), m.group(6))
        if b <= a:
            b += 24.0
        if b - a > MAX_RANGE_H:
            continue
        for s in range(48):
            lo = s / 2.0
            if _overlap(a, b, lo, lo + 0.5) > 0 or _overlap(a, b, lo + 24, lo + 24.5) > 0:
                grid[s] = True
    night = sum(0.5 for s in range(48) if grid[s] and (s / 2.0 >= NIGHT_START_H or s / 2.0 < NIGHT_END_H))
    early = sum(0.5 for s in range(48) if grid[s] and EARLY_START_H <= s / 2.0 < EARLY_END_H)
    f = WEEKNIGHT_FACTOR if re.search(r"WEEK\s*NIGHTS?|MONDAY\s*(?:-|TO|THROUGH)\s*FRIDAY|MON\s*-\s*FRI|SUN\w*\s*(?:-|TO|THROUGH)\s*THU", t) else 1.0
    return night * f, early * f


def _series_kind(series, typedesc):
    t = (typedesc or "").upper()
    if "CRANE OR SHOVEL" in t:
        return 3
    if "MILL" in t or "PAVE" in t or "PAVING" in t or (series or "").startswith("DOT IN-HOUSE"):
        return 2
    if (series or "").startswith("SIDEWALK"):
        return 1
    return 0


_HEAVY = ("MAJOR", "RECONSTRUCTION", "CONDUIT", "RAPID TRANSIT", "MILL", "PAV", "FOUNDATION", "VAULT",
          "ROADWAY CLOSURE", "BRIDGE")
_LIGHT = ("TEST PIT", "CORES", "BORING", "FENCE", "TREE PIT", "STREET LIGHT", "STORM WATER")


def _wclass(typedesc):
    t = (typedesc or "").upper()
    if any(k in t for k in _LIGHT):
        return 0
    if any(k in t for k in _HEAVY):
        return 2
    return 1


def _owner(permittee, typedesc):
    p, t = (permittee or "").upper(), (typedesc or "").upper()
    if "CONSOLIDATED EDISON" in p:
        return 0
    if (p.startswith("NYC ") or p.startswith("NEW YORK CITY") or "D.D.C" in t or t.startswith("DDC") or "DEP CONTRACTOR" in t
            or t.startswith("E.D.C") or t.startswith("NYCDOT") or t.startswith("DOT ") or "DEPT OF" in p):
        return 1
    return 2


def _get(dataset, params, tries=4):
    url = SOCRATA.format(dataset) + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hush-iq-build/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def _pull(dataset, name, select, where, cache, page=50000):
    f = Path(cache) / f"{name}.json" if cache else None
    if f and f.exists():
        return json.loads(f.read_text())
    rows, off = [], 0
    while True:
        chunk = _get(dataset, {"$select": select, "$where": where, "$order": ":id", "$limit": page, "$offset": off})
        rows += chunk
        if len(chunk) < page:
            break
        off += page
        time.sleep(1.0)   # polite paging
    if f:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rows))
    return rows


def _day(s):
    return dt.date.fromisoformat(s[:10]).toordinal()


def build(out_dir=None, as_of=None, cache_dir=None):
    """Pull the public data and write construction.json.gz (Manhattan, under 8 MB). Standard library only.
    as_of: the build date (default today). cache_dir: keep the raw pulls here so a rerun does not pull again."""
    out_dir = Path(out_dir) if out_dir else DATA
    built = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    b0 = built.toordinal()
    lo_ord = b0 - WINDOW_DAYS + 1
    lo = (built - dt.timedelta(days=WINDOW_DAYS - 1)).isoformat()
    hi = built.isoformat()
    fut = (built + dt.timedelta(days=FUTURE_DAYS)).isoformat()

    cl = _Centerline(_pull(DS_CENTERLINE, "centerline",
                           "the_geom,full_street_name,l_low_hn,l_high_hn,r_low_hn,r_high_hn", "boroughcode='1'",
                           cache_dir, page=20000))
    permits = _pull(DS_PERMITS, "permits",
                    "permitnumber,permitstatusshortdesc,permitseriesshortdesc,permittypedesc,issuedworkstartdate,"
                    "issuedworkenddate,permithousenumber,onstreetname,fromstreetname,tostreetname,permitteename,"
                    "specificstipulations",
                    f"boroughname='MANHATTAN' and issuedworkenddate >= '{lo}T00:00:00' and issuedworkstartdate <= "
                    f"'{hi}T23:59:59' and (permitseriesshortdesc in ('STREET OPENING PERMIT','SIDEWALK CONSTRUCTION PERMIT',"
                    "'DOT IN-HOUSE PAVING AND MILLING') or permittypedesc = 'PLACE CRANE OR SHOVEL ON STREET')", cache_dir)
    ahv = _pull(DS_AHV, "ahv",
                "bin,ahvpermitstatus,reasonforvariance,variance_start_date_time,variance_end_date_time,enclosed_work,"
                "latitude,longitude",
                f"upper(borough)='MANHATTAN' and variance_end_date_time >= '{lo}T00:00:00' and variance_start_date_time "
                f"<= '{fut}T23:59:59'", cache_dir)

    # ---- street permits: place, classify, union the days
    sites = {}    # (geom, kind, wclass, owner) -> record
    total = placed = 0
    for r in permits:
        if r.get("permitstatusshortdesc") in ("VOIDED AFTER ISSUE", "SUBMITTED", "PERMIT HELD FOR EXTERNAL REVIEW",
                                              "SIM SUBMITTED"):
            continue
        total += 1
        geom = _place(cl, r.get("onstreetname"), r.get("fromstreetname"), r.get("tostreetname"), r.get("permithousenumber"))
        if not geom:
            continue
        placed += 1
        typ = r.get("permittypedesc")
        k = (tuple(round(x, 5) for x in geom), _wclass(typ), _owner(r.get("permitteename"), typ))
        s = sites.setdefault(k, {"n": 0, "days": set(), "act": 0, "act_end": 0, "night": {}, "early": {}, "kinds": {}})
        s["n"] += 1
        kind = _series_kind(r.get("permitseriesshortdesc"), typ)
        s["kinds"][kind] = s["kinds"].get(kind, 0) + 1
        a, e = _day(r["issuedworkstartdate"]), _day(r["issuedworkenddate"])
        days = range(max(a, lo_ord), min(e, b0) + 1)
        s["days"].update(days)
        if a <= b0 <= e:
            s["act"] += 1
            s["act_end"] = max(s["act_end"], e - b0)
        nh, eh = _permit_hours(r.get("specificstipulations"))
        for d in days:
            if nh > s["night"].get(d, 0.0):
                s["night"][d] = nh
            if eh > s["early"].get(d, 0.0):
                s["early"][d] = eh
    locs, loc_id, recs = [], {}, []
    for (geom, wc, owner), s in sites.items():
        if not s["days"]:
            continue
        kind = max(s["kinds"].items(), key=lambda kv: (kv[1], -kv[0]))[0]
        if geom not in loc_id:
            loc_id[geom] = len(locs)
            locs.append(list(geom))
        recs.append([loc_id[geom], kind, wc, owner, s["n"], len(s["days"]), s["act"], s["act_end"],
                     round(sum(s["night"].values()), 1), round(sum(s["early"].values()), 1)])

    # ---- after-hours variances: per site, per night, merged hours
    bysite = defaultdict(lambda: defaultdict(list))
    meta = {}
    missing = 0
    for r in ahv:
        if r.get("ahvpermitstatus") not in AHV_STATUS_OK or not r.get("variance_start_date_time"):
            continue
        try:
            la, ln = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            missing += 1
            continue
        w = REASON_WEIGHT.get(r.get("reasonforvariance"), REASON_DEFAULT) * (ENCLOSED_FACTOR if r.get("enclosed_work") in (True, "true") else 1.0)
        s0 = dt.datetime.fromisoformat(r["variance_start_date_time"])
        e0 = dt.datetime.fromisoformat(r["variance_end_date_time"])
        site = _key(la, ln)
        meta[site] = (la, ln)
        d0 = s0.date().toordinal()
        for d in range(d0 - 1, e0.date().toordinal() + 1):
            base = dt.datetime.combine(dt.date.fromordinal(d), dt.time())
            for kind, a, b in (("n", NIGHT_START_H, 24.0 + NIGHT_END_H), ("e", EARLY_START_H, EARLY_END_H)):
                wa, wb = base + dt.timedelta(hours=a), base + dt.timedelta(hours=b)
                x, y = max(s0, wa), min(e0, wb)
                if y > x:
                    bysite[site][(kind, d)].append((x, y, w))
    ahv_rows = []
    for site, nights in bysite.items():
        n_n = n_e = ahead = 0
        h_n = h_e = 0.0
        last = None
        for (kind, d), ivs in nights.items():
            ivs.sort()
            cur, tot = None, 0.0
            for x, y, w in ivs:
                if cur and x <= cur[1]:
                    cur = (cur[0], max(cur[1], y), max(cur[2], w))
                else:
                    if cur:
                        tot += (cur[1] - cur[0]).total_seconds() / 3600.0 * cur[2]
                    cur = (x, y, w)
            if cur:
                tot += (cur[1] - cur[0]).total_seconds() / 3600.0 * cur[2]
            if d > b0:
                if kind == "n" and d <= b0 + FUTURE_DAYS:
                    ahead += 1
                continue
            if d < lo_ord:
                continue
            if kind == "n":
                n_n += 1
                h_n += tot
                last = d if last is None else max(last, d)
            else:
                n_e += 1
                h_e += tot
        if n_n or n_e or ahead:
            la, ln = meta[site]
            ahv_rows.append([round(la, 5), round(ln, 5), n_n, round(h_n, 1), n_e, round(h_e, 1),
                             (b0 - last) if last else -1, ahead])

    doc = {"built": built.isoformat(), "window_days": WINDOW_DAYS, "radius_m": RADIUS_M,
           "note": ("Snapshot of the 12 months to the build date. Permits expire as work ends: rebuild monthly. "
                    "Street rec = [loc, kind, class, owner, permits, days with a permit, active on build date, days until "
                    "the last active permit ends, night hour-days, early hour-days]; ahv = [lat, lng, nights, night "
                    "weighted hours, early mornings, early weighted hours, days since last night, nights scheduled ahead]."),
           "sources": {"street_permits": {"id": DS_PERMITS, "rows_used": total, "placed": placed,
                                          "placed_share": round(placed / max(1, total), 4)},
                       "after_hours_variances": {"id": DS_AHV, "rows": len(ahv), "no_coordinates": missing},
                       "centerline": {"id": DS_CENTERLINE}},
           "street": {"loc": locs, "rec": recs}, "ahv": ahv_rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / f"{NAME}.json.gz", "wt") as f:
        json.dump(doc, f, separators=(",", ":"))
    return doc
