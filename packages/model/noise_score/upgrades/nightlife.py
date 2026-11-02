"""Nightlife upgrade: people outside, nights not complaints, and what each liquor licence class really is.
(Hackathon work, Oct 28.) Plain-words write-up: packages/model/upgrades/nightlife.md.

Today's nightlife level, with the research numbers of 2026-10-29 (recal.py, [V10]), is a licence-energy base
within 150 m (bars 66, other venues 59, restaurants 47 at 10 m), a slot offset, and a 311 bump that counts
complaints and stops at 12 (decision U6 kept it). This module keeps that level and adds two corrections, each a fraction
of the difference between today's estimate and a second estimate of the same sound, so nothing is counted twice,
and one sound source today's model leaves out:

  class    venues graded by NYS licence class code instead of by licence description (saloon-type liquor
           licences are bars; beer-and-wine restaurants and hotels are quieter), same distance law as today
  nights   the 311 bump counted in distinct nights with a complaint, with no 12 dB ceiling (nights have a
           natural maximum: every night), against today's bump counted in complaints
  terrace  licensed sidewalk and roadway cafes (Dining Out NYC) within 150 m, each a point source of 24 seated
           people talking (46 + 10 log10(24 / 2) at 10 m), added as energy in the hours tables are busy,
           7 pm to 11 pm (they close at 11 by law)

  level    today + class + nights (held to 6 either way), then the terraces, per slot.

Runtime is pure standard library. build() needs the network (urllib only) and writes the artifact.
"""
import datetime as dt
import gzip
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import DATA, SLOTS, Step, Upgrade, passthrough
from ._geo import GridIndex
from .. import config as C
from .. import config_v2 as V

NAME = "nightlife"

# ---------------------------------------------------------------- constants
# today's numbers, read from config.py so the two estimates stay on one scale (sourced: today's model)
RADIUS_M = C.RADIUS_NIGHTLIFE_M                  # 150 m, today's nightlife radius
YEARS = C.LOOKBACK_MONTHS / 12                   # 2 years, today's 311 lookback
REF_M = C.VENUE_REF_DISTANCE_M                   # 10 m
DB_PER_DOUBLING_DIST = C.VENUE_DB_PER_DOUBLING   # 6 dB per doubling of distance (point source)
VENUE_SUM_CAP_DB = C.VENUE_SUM_CAP_DB            # 75
NONE_DB = C.NIGHTLIFE_NONE_DB                    # 40, no licensed venue within the radius
BUMP_DB_PER_DOUBLING = 3.0                       # today's 311 bump: 3 dB per doubling of (1 + per year / ref), model.log_bump
BUMP_REF_PER_YEAR = C.NIGHTLIFE_311_REF_PER_YEAR # 3 per year
TODAY_BUMP_CAP_DB = V.NIGHTLIFE_311_MAX_DB       # 12, today's ceiling (the research's 6 not taken, decision U6)
BUMP_SLOTS = V.NIGHTLIFE_311_SLOTS               # every slot, as today (decision U6)

# NYS class codes, read off the licence holders in each class (saloons and pubs in 0370, taquerias and coffee
# shops in 0240); the dataset has no legend. Grades are dB at 10 m, each a step from its description's grade.
# The steps are judgment, ordered by how strongly each class tracks night-time 311 complaint nights in a
# community-district fit (nightlife.md); the description grades they step from are the research numbers [V10].
_BAR, _VENUE, _REST = (V.VENUE_BASE_DB[k] for k in ("bar", "venue", "restaurant"))
FB_LIQUOR_CODE, FB_LIQUOR_DB = "0370", _BAR              # Food & Beverage Business with liquor: bar grade (description: venue)
FB_OTHER_DB = _VENUE - 4.0                               # other Food & Beverage classes: wine, beer, delis
REST_LIQUOR_CODE, REST_LIQUOR_DB = "0340", _REST + 2.0   # restaurant with liquor
REST_BEER_WINE_CODE, REST_BEER_WINE_DB = "0240", _REST - 2.0   # restaurant with beer and wine only
HOTEL_CATERING_DB = _VENUE - 6.0                         # hotel, catering: fewest complaint nights of any class
ADDITIONAL_BAR_DB = _BAR - 4.0                           # extra bar inside a restaurant, hotel or theatre
CLASS_MIX = 0.5                                          # judgment: description grades and class-code grades are equally good

NIGHTS_MIX = 0.5                                         # judgment: complaints and nights are equally good counts
NIGHTS_CAP_DB = BUMP_DB_PER_DOUBLING * math.log2(1 + 365 / BUMP_REF_PER_YEAR)   # 20.9: a complaint on every night of the year

TERRACE_DB = V.TERRACE_DB_AT_10M + 10 * math.log10(V.TERRACE_SEATS / 2)   # sourced: 56.8 at 10 m, 24 seats talking [V10]
OUTDOOR_CLOSE_HOUR = V.TERRACE_HOURS[1]   # sourced: Dining Out NYC, all cafes close at 11 pm since the City Council's Aug 2026 change


def _terrace_share():
    """Share of each slot's hours with tables busy (7 pm to 11 pm): night 1 of 7, early none, day 3 of 14."""
    out = {}
    for s, (a, b) in C.WINDOWS.items():
        hours = [h % 24 for h in range(a, b if b > a else b + 24)]
        out[s] = sum(1 for h in hours if V.TERRACE_HOURS[0] <= h < V.TERRACE_HOURS[1]) / len(hours)
    return out


TERRACE_SLOT_SHARE = _terrace_share()
TOTAL_CAP_DB = 6.0     # judgment: the two corrections together move today's level at most this far, a sixth of the 40 to 80 range

# ---------------------------------------------------------------- build constants
GRID = 1e-4            # 311 is stored on a 4-decimal grid (11 m by 8 m), as the server groups it
X0, Y0 = -74.10, 40.60 # grid origin
PAGE = 50_000
SLEEP_S = 1.0
SOCRATA_NYC = "https://data.cityofnewyork.us/resource"
SOCRATA_NYS = "https://data.ny.gov/resource"
SRC_SLA = ("NYS Liquor Authority, Current Active Licenses", "9s3h-dpkz", "https://data.ny.gov/resource/9s3h-dpkz")
SRC_DINING = ("NYC DOT, Dining Out NYC Locations", "fpeh-f7ci", "https://data.cityofnewyork.us/resource/fpeh-f7ci")
SRC_311 = ("311 Service Requests from 2010 to Present", "erm2-nwe9", "https://data.cityofnewyork.us/resource/erm2-nwe9")
COMPLAINT_TYPES = ("Noise - Commercial", "Noise - Street/Sidewalk", "Noise - Park")
DESCRIPTORS = tuple(sorted(C.PARTY_DESCRIPTORS))

_MX = GRID * 84300.0   # metres per grid step, east-west at Manhattan's latitude (_geo.M_PER_DEG_LNG)
_MY = GRID * 111000.0  # metres per grid step, north-south

# ---------------------------------------------------------------- artifact
_ART = None
_LOADED = False


def _prepare(doc):
    """The artifact turned into lookups: venue and cafe indexes, 311 cells per slot."""
    descs = doc["descs"]
    vidx = GridIndex()
    for lat, lng, di, code in doc["venues"]:
        d = descs[di]
        vidx.add_point(lat, lng, (_grade_today(d), _grade_new(d, code), _is_bar(d, code)))
    cidx = GridIndex()
    for lat, lng, kind in doc["cafes"]:
        cidx.add_point(lat, lng, [kind])   # a fresh object each: GridIndex dedupes on id(payload)
    cells = {}
    for s in SLOTS:
        a = doc["inc"][s]
        c = {}
        for x, y, n, k in zip(a["x"], a["y"], a["n"], a["c"]):
            c.setdefault((x, y), []).extend((n, k))
        cells[s] = c
    return {"venues": vidx, "cafes": cidx, "cells": cells, "days": doc["window"]["days"], "meta": doc}


def _artifact():
    """Loaded once; None when the file has not been built."""
    global _ART, _LOADED
    if not _LOADED:
        _LOADED = True
        try:
            p = DATA / f"{NAME}.json.gz"
            if p.exists():
                with gzip.open(p, "rt") as f:
                    _ART = _prepare(json.load(f))
        except Exception:
            _ART = None
    return _ART


def _install(doc):
    """Tests: use this document instead of the built file (None clears it)."""
    global _ART, _LOADED
    _ART = _prepare(doc) if doc is not None else None
    _LOADED = True


# ---------------------------------------------------------------- grades
def _grade_today(desc):
    cls = C.VENUE_CLASSES.get(desc)
    return V.VENUE_BASE_DB.get(cls) if cls else None


def _grade_new(desc, code):
    """dB at 10 m by licence description and class code; today's grade for anything not named here."""
    if desc == "Food & Beverage Business":
        return FB_LIQUOR_DB if code == FB_LIQUOR_CODE else FB_OTHER_DB
    if desc == "Restaurant":
        if code == REST_LIQUOR_CODE:
            return REST_LIQUOR_DB
        if code == REST_BEER_WINE_CODE:
            return REST_BEER_WINE_DB
    if desc in ("Hotel", "Catering Establishment", "Summer Catering Establishment"):
        return HOTEL_CATERING_DB
    if desc == "Additional Bar":
        return ADDITIONAL_BAR_DB
    return _grade_today(desc)


def _is_bar(desc, code):
    """Bar-style licence, for the evidence line: liquor Food & Beverage, club, cabaret. Not an extra bar inside another venue."""
    if desc == "Food & Beverage Business":
        return code == FB_LIQUOR_CODE
    return C.VENUE_CLASSES.get(desc) == "bar" and not desc.lower().startswith("additional")


# ---------------------------------------------------------------- the math
def _energy(levels):
    if not levels:
        return None
    return 10 * math.log10(sum(10 ** (v / 10) for v in levels))


def _base(levels):
    e = _energy(levels)
    return NONE_DB if e is None else min(e, VENUE_SUM_CAP_DB)


def _bump(per_year, cap):
    return min(cap, BUMP_DB_PER_DOUBLING * math.log2(1 + per_year / BUMP_REF_PER_YEAR))


def _lookup(art, lat, lng):
    """Everything the three rules need around one point."""
    near = art["venues"].near(lat, lng, RADIUS_M)
    old_lv, new_lv, w_venue, bars = [], [], 0.0, 0
    for d, (g_old, g_new, bar) in near:
        dd = max(d, REF_M)
        drop = DB_PER_DOUBLING_DIST * math.log2(dd / REF_M)
        old_lv.append(g_old - drop)
        new_lv.append(g_new - drop)
        w_venue += (REF_M / dd) ** 2
        bars += 1 if bar else 0
    cafes = sorted(art["cafes"].near(lat, lng, RADIUS_M), key=lambda c: c[0])
    terrace = _energy([TERRACE_DB - DB_PER_DOUBLING_DIST * math.log2(max(d, REF_M) / REF_M) for d, _ in cafes])
    kinds = [0, 0]
    for _, k in cafes:
        kinds[k[0]] += 1
    fx, fy = (lng - X0) / GRID, (lat - Y0) / GRID
    cx, cy = int(round(fx)), int(round(fy))
    nx, ny = int(RADIUS_M / _MX) + 2, int(RADIUS_M / _MY) + 2
    r2 = RADIUS_M * RADIUS_M
    raw = {s: 0 for s in SLOTS}
    nights = {s: set() for s in SLOTS}
    for s in SLOTS:
        cells, ns = art["cells"][s], nights[s]
        for ix in range(cx - nx, cx + nx + 1):
            dx = (ix - fx) * _MX
            if abs(dx) > RADIUS_M:
                continue
            for iy in range(cy - ny, cy + ny + 1):
                dy = (iy - fy) * _MY
                if dx * dx + dy * dy > r2:
                    continue
                lst = cells.get((ix, iy))
                if lst:
                    for i in range(0, len(lst), 2):
                        ns.add(lst[i])
                        raw[s] += lst[i + 1]
    return {"n_venues": len(near), "bars": bars, "old": old_lv, "new": new_lv, "w_venue": w_venue,
            "terrace": terrace, "cafes": cafes, "kinds": kinds, "raw": raw,
            "nights": {s: len(nights[s]) for s in SLOTS}}


def _corrections(art, lat, lng):
    r = _lookup(art, lat, lng)
    base_old, base_new = _base(r["old"]), _base(r["new"])
    class_fix = CLASS_MIX * (base_new - base_old)
    nights_fix = {}
    for s in SLOTS:
        if s in BUMP_SLOTS:
            bump_raw = _bump(r["raw"][s] / YEARS, TODAY_BUMP_CAP_DB)
            bump_nights = _bump(r["nights"][s] / YEARS, NIGHTS_CAP_DB)
            nights_fix[s] = NIGHTS_MIX * (bump_nights - bump_raw)
        else:
            nights_fix[s] = 0.0
    return r, base_old, base_new, class_fix, nights_fix


def with_terrace(level, terrace, slot):
    """A slot's level with the terraces added as energy for the share of its hours that tables are busy."""
    if terrace is None or TERRACE_SLOT_SHARE[slot] <= 0:
        return level
    return 10 * math.log10(10 ** (level / 10) + TERRACE_SLOT_SHARE[slot] * 10 ** (terrace / 10))


def _clip(x):
    return max(-TOTAL_CAP_DB, min(TOTAL_CAP_DB, x))


def _r(x, n=3):
    return round(float(x), n)


# ---------------------------------------------------------------- the upgrade
def _safe_today(today):
    try:
        out = {}
        for s in SLOTS:
            v = float(today[s])
            if not math.isfinite(v):
                raise ValueError
            out[s] = v
        return out
    except Exception:
        return {s: NONE_DB for s in SLOTS}


def upgrade(lat, lng, today, facts):
    t = _safe_today(today)
    try:
        art = _artifact()
        lat, lng = float(lat), float(lng)
        if art is None or not (math.isfinite(lat) and math.isfinite(lng)):
            return passthrough(NAME, t)
        return _compose(art, lat, lng, t)
    except Exception:   # an upgrade must never take the score down
        return passthrough(NAME, t)


def _compose(art, lat, lng, t):
    r, base_old, base_new, class_fix, nights_fix = _corrections(art, lat, lng)
    mid = {s: t[s] + _clip(class_fix + nights_fix[s]) for s in SLOTS}
    level = {s: with_terrace(mid[s], r["terrace"], s) for s in SLOTS}
    outdoor = {s: level[s] - mid[s] for s in SLOTS}
    days = art["days"]
    per_year = {s: r["nights"][s] / YEARS for s in SLOTS}
    kinds = r["kinds"]
    n_cafes = kinds[0] + kinds[1]
    L = f"{NAME}."

    steps = [
        Step(L + "today", "Today's nightlife level", "today_input", {s: _r(t[s]) for s in SLOTS}, "index",
             "today's model", f"licence energy within 150 m, a slot offset, and a 311 bump that stops at "
             f"{TODAY_BUMP_CAP_DB:g}", [L + "level"], "live"),
        Step(L + "venues", "Licensed venues within 150 m", "today_input", r["n_venues"], "count",
             f"{SRC_SLA[0]} ({SRC_SLA[1]})", "", [L + "class_fix"], "live"),
        Step(L + "complaints", "Party, music and loud-talking complaints within 150 m, 24 months", "today_input",
             dict(r["raw"]), "count", f"{SRC_311[0]} ({SRC_311[1]})",
             "Noise - Commercial, Street/Sidewalk and Park; Loud Music/Party and Loud Talking; per slot",
             [L + "nights_fix"], "live"),
        Step(L + "classes", "Venue sum graded by licence class code", "new_input",
             f"{base_new:.1f} against {base_old:.1f} graded by description", "index",
             f"{SRC_SLA[0]} ({SRC_SLA[1]}), field class", "same 10 m reference and 6 dB per doubling as today",
             [L + "class_fix"], "new"),
        Step(L + "complaint_nights", "Nights with a complaint within 150 m, per year", "new_input",
             {s: _r(per_year[s], 1) for s in SLOTS}, "nights/yr", f"{SRC_311[0]} ({SRC_311[1]})",
             "distinct nights (10 pm to 5 am) or days with at least one complaint, over 24 months, divided by 2",
             [L + "nights_fix"], "new"),
        Step(L + "cafes", "Licensed outdoor dining within 150 m", "new_input",
             {"sidewalk": kinds[0], "roadway": kinds[1]}, "count", f"{SRC_DINING[0]} ({SRC_DINING[1]})",
             "sidewalk and roadway cafe licences issued by DOT", [L + "terrace"], "new"),
        Step(L + "grade_table", "Grade by licence class code", "new_input",
             f"liquor F&B {FB_LIQUOR_DB:g}, other F&B {FB_OTHER_DB:g}, restaurant with liquor {REST_LIQUOR_DB:g}, "
             f"restaurant beer and wine {REST_BEER_WINE_DB:g}, hotel and catering {HOTEL_CATERING_DB:g}, "
             f"additional bar {ADDITIONAL_BAR_DB:g}", "index", "judgment",
             "dB at 10 m; every other class keeps today's grade", [L + "classes"], "judgment"),
        Step(L + "terrace_db", "One terrace at 10 m", "new_input", _r(TERRACE_DB, 1), "index",
             "noise research, 2026-10-29 (Rindel, eating establishments; German federal court 8 C 3.19)",
             f"{V.TERRACE_DB_AT_10M:g} + 10 x log10({V.TERRACE_SEATS} seats / 2), raised voices; the licence does not "
             "give seats", [L + "terrace"], "new"),
        Step(L + "outdoor_hours", "Share of the slot with tables busy", "new_input",
             {s: _r(TERRACE_SLOT_SHARE[s]) for s in SLOTS}, "",
             "noise research, 2026-10-29; closing time from Dining Out NYC (11 pm)",
             "7 pm to 11 pm: night 1 hour of 7, early none, day 3 of 14", [L + "outdoor"], "new"),
        Step(L + "cap", "Largest change from the two corrections", "new_input", TOTAL_CAP_DB, "index", "judgment",
             "venue grade and complaint nights together move today's level at most this far", [L + "level"], "judgment"),
        Step(L + "class_fix", "Venue grade correction", "rule", _r(class_fix), "index", "",
             "half the difference between the venue sum graded by class code and the one graded by description",
             [L + "level"], "new"),
        Step(L + "nights_fix", "Complaint nights correction", "rule", {s: _r(nights_fix[s]) for s in SLOTS}, "index", "",
             f"half the difference between 3 x log2(1 + nights per year / 3), no ceiling, and today's bump counted "
             f"in complaints, {TODAY_BUMP_CAP_DB:g} at most", [L + "level"], "new"),
        Step(L + "terrace", "Terraces within 150 m, together", "rule",
             _r(r["terrace"], 1) if r["terrace"] is not None else None, "index", "",
             "each terrace loses 6 per doubling of distance beyond 10 m; added as energy", [L + "outdoor"], "new"),
        Step(L + "outdoor", "Outdoor dining adds", "rule", {s: _r(outdoor[s]) for s in SLOTS}, "index", "",
             "10 x log10(10^(level / 10) + slot share x 10^(terraces / 10)) - level", [L + "level"], "new"),
        Step(L + "level", "Nightlife level", "result", {s: _r(level[s]) for s in SLOTS}, "index", "",
             "today + venue grade + complaint nights (held to 6 either way), then outdoor dining", [], "new"),
    ]

    ev = []
    if r["nights"]["night"] > 0:
        ev.append(f"Neighbors reported a party, music or loud talking within {int(RADIUS_M)} m on {r['nights']['night']} "
                  f"of the last {days} nights between 10 pm and 5 am.")
    if n_cafes:
        ev.append(f"{n_cafes} licensed sidewalk or roadway dining spot{'s' if n_cafes != 1 else ''} within {int(RADIUS_M)} m "
                  f"(nearest {int(round(r['cafes'][0][0]))} m); outdoor tables close at {OUTDOOR_CLOSE_HOUR - 12} pm.")
    if r["bars"]:
        ev.append(f"{r['bars']} of the {r['n_venues']} licensed venues within {int(RADIUS_M)} m hold a bar-style liquor licence.")
    if not ev:
        ev.append(f"No outdoor dining, bar-style licence or reported late-night noise within {int(RADIUS_M)} m.")
    return Upgrade(levels={s: _r(level[s]) for s in SLOTS}, steps=steps, evidence=ev[:3])


# ---------------------------------------------------------------- build (offline)
def _get(url, params):
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": C.USER_AGENT})
    err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as f:
                return json.load(f)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{url}: {err}")


def _window(today=None):
    """The 24 full months before the first of this month: [start, end)."""
    today = today or dt.date.today()
    end = today.replace(day=1)
    m = end.year * 12 + end.month - 1 - C.LOOKBACK_MONTHS
    return dt.date(m // 12, m % 12 + 1, 1), end


def _pull_sla():
    rows = _get(f"{SOCRATA_NYS}/{SRC_SLA[1]}.json", {
        "$select": "description,class,georeference", "$where": "premisescounty='New York'", "$limit": 50000})
    descs, venues = [], []
    for r in rows:
        d = r.get("description")
        g = (r.get("georeference") or {}).get("coordinates")
        if d not in C.VENUE_CLASSES or not g:
            continue
        if d not in descs:
            descs.append(d)
        venues.append([round(g[1], 5), round(g[0], 5), descs.index(d), str(r.get("class") or "")])
    return descs, venues, len(rows)


def _pull_dining():
    rows = _get(f"{SOCRATA_NYC}/{SRC_DINING[1]}.json", {
        "$select": "license_type,license_status,latitude,longitude", "$where": "borough='Manhattan'", "$limit": 50000})
    cafes = []
    for r in rows:
        if r.get("license_status") != "Issued" or not r.get("latitude"):
            continue
        cafes.append([round(float(r["latitude"]), 5), round(float(r["longitude"]), 5),
                      1 if r.get("license_type") == "Roadway" else 0])
    return cafes, len(rows)


def _pull_311(start, end):
    types = ",".join(f"'{t}'" for t in COMPLAINT_TYPES)
    descs = ",".join(f"'{d}'" for d in DESCRIPTORS)
    where = (f"borough='MANHATTAN' AND complaint_type in ({types}) AND descriptor in ({descs}) "
             f"AND created_date >= '{start}T00:00:00' AND created_date < '{end}T00:00:00' AND latitude IS NOT NULL")
    out, off, total = {s: {} for s in SLOTS}, 0, 0
    while True:
        rows = _get(f"{SOCRATA_NYC}/{SRC_311[1]}.json", {
            "$select": "date_trunc_ymd(created_date) as d, date_extract_hh(created_date) as h, "
                       "round(latitude,4) as la, round(longitude,4) as lo, count(*) as n",
            "$where": where, "$group": "d,h,la,lo", "$order": "d,h,la,lo", "$limit": PAGE, "$offset": off})
        for r in rows:
            day = (dt.date.fromisoformat(r["d"][:10]) - start).days
            h = int(r["h"])
            slot = "night" if (h >= 22 or h < 5) else ("early" if h < 8 else "day")
            night = day - 1 if (slot == "night" and h < 5) else day    # 0 to 5 am belongs to the evening before
            x, y = int(round((float(r["lo"]) - X0) / GRID)), int(round((float(r["la"]) - Y0) / GRID))
            out[slot][(x, y, night)] = out[slot].get((x, y, night), 0) + int(r["n"])
            total += int(r["n"])
        if len(rows) < PAGE:
            return out, total
        off += PAGE
        time.sleep(SLEEP_S)


def build(out_dir=DATA):
    """Pulls the three datasets and writes <out_dir>/nightlife.json.gz (Manhattan, well under 8 MB)."""
    start, end = _window()
    descs, venues, n_sla = _pull_sla()
    cafes, n_din = _pull_dining()
    inc, n_311 = _pull_311(start, end)
    arrays = {}
    for s in SLOTS:
        keys = sorted(inc[s])
        arrays[s] = {"x": [k[0] for k in keys], "y": [k[1] for k in keys], "n": [k[2] for k in keys],
                     "c": [inc[s][k] for k in keys]}
    doc = {
        "name": NAME, "built": dt.date.today().isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days},
        "datasets": {
            "sla": {"id": SRC_SLA[1], "rows": n_sla, "kept": len(venues),
                    "where": "premisescounty = New York, description in today's venue classes"},
            "dining": {"id": SRC_DINING[1], "rows": n_din, "kept": len(cafes), "where": "borough = Manhattan, status Issued"},
            "311": {"id": SRC_311[1], "complaints": n_311, "incidents": sum(len(a["x"]) for a in arrays.values()),
                    "where": "Manhattan; Noise - Commercial, Street/Sidewalk, Park; Loud Music/Party, Loud Talking"}},
        "grid": {"x0": X0, "y0": Y0, "step": GRID},
        "descs": descs, "venues": venues, "cafes": cafes, "inc": arrays,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{NAME}.json.gz"
    with gzip.open(p, "wt") as f:
        json.dump(doc, f, separators=(",", ":"))
    print(f"{NAME}: {len(venues)} venues, {len(cafes)} cafes, {n_311} complaints in {doc['datasets']['311']['incidents']} "
          f"incidents, {p.stat().st_size / 1e6:.2f} MB -> {p}")


if __name__ == "__main__":
    import sys
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA)
