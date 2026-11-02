"""Neighbors upgrade (internal name "building"): what kind of building you share walls with, on top of today's
complaint count. (Hackathon work, Oct 28.) Plain-words write-up: packages/model/upgrades/building.md.

Today's estimate counts 311 residential noise complaints per apartment at the building (24 months, shrunk toward
the Manhattan rate). This module keeps that level and adds a capped correction, the same for every time slot:

  type     what kind of building it is (condominium, co-op, rental, walk-up, shops below), from the PLUTO building
           class. Measured, not assumed: for each class, the 311 residential noise complaints of the latest 12
           months against what today's formula (fed with the 12 months before) expected. Half of the gap is added.
  hallway  apartments per floor above the Manhattan typical (the owner's idea). Small judgment weight: the 311
           check does not support it (building.md, limit 1).
  stays    whole-apartment short-term rentals (under 30 nights) listed within 150 m, per 1,000 apartments there.
           Small judgment weight. Inside Airbnb blurs every location by up to 150 m, so this is an area signal.

Runtime is pure standard library. Build time (build()) is also standard library only and needs the network.
"""
import csv
import datetime as dt
import gzip
import io
import json
import math
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from . import SLOTS, Step, Upgrade, load, passthrough
from ._geo import GridIndex

NAME = "building"

# ---------------------------------------------------------------- constants (sourced or judgment)
MATCH_BASE_M = 30.0        # judgment, from the brief: a point belongs to a tax lot if it is within about 30 m of the lot's centre
MATCH_MAX_M = 150.0        # judgment: big lots (a campus of towers) count up to their own radius, never beyond this
LOT_RADIUS_FACTOR = 1.5    # judgment: a long lot's centre sits farther from its door than a round lot's would (tested on 120 geocoded addresses)
FLOORS_BONUS = 0.35        # judgment: a lot with the same floor count as the facts passed in beats a slightly nearer one
COMMERCIAL_BONUS = 0.10    # judgment: same for the shops-on-the-ground-floor flag

CLASS_PRIOR_COMPLAINTS = 25.0   # judgment: a building class with fewer expected complaints than this is pulled toward "no correction"
CLASS_SHARE = 0.5          # judgment: half of a class's gap is how likely people are to call 311, not how loud the building is
CLASS_CAP = 6.0            # judgment: no class moves the level more than this (today's spread across Manhattan is 7)

HALLWAY_PER_DOUBLING = 0.0  # off (decision U1, upgrades/DECISIONS.md): held-out 311 runs the other way. Was 0.5 per doubling above typical
HALLWAY_CAP = 1.5          # judgment

STR_RADIUS_M = 150.0       # sourced: Inside Airbnb moves each listing up to 150 m from the real address (insideairbnb.com/data-assumptions)
STR_MAX_MIN_NIGHTS = 29    # sourced: NYC's short-term rental law (Local Law 18, in force since Sept 2023) is about stays under 30 nights
STR_PER_1000 = 0.5         # judgment: index per listing per 1,000 apartments within the radius
STR_CAP = 1.0              # judgment

TOTAL_CAP = 7.0            # judgment: the three corrections together never move the level more than this
LEVEL_MIN, LEVEL_MAX = 30.0, 80.0   # judgment: keeps the level on the engine's usual range (today is clamped 40 to 72)

LOOKBACK_DAYS = 365        # sourced: the 311 windows used to measure classes are two 12-month blocks
PLUTO_ID, C311_ID = "64uk-42ks", "erm2-nwe9"
SOCRATA = "https://data.cityofnewyork.us/resource"
IAB_PAGE = "https://insideairbnb.com/get-the-data/"
IAB_FALLBACK_DATE = "2026-09-14"
IAB_URL = "https://data.insideairbnb.com/united-states/ny/new-york-city/{date}/visualisations/listings.csv"

CLASS_LABEL_BY_CODE = {"D0": "elevator co-ops", "D4": "elevator co-ops", "C6": "walk-up co-ops", "RR": "condominium rentals"}
CLASS_LABEL_BY_LETTER = {"R": "condominiums", "D": "elevator apartment buildings", "C": "walk-up apartment buildings",
                         "S": "apartment buildings with shops below", "K": "apartment buildings with shops below",
                         "A": "small houses", "B": "small houses"}


# ================================================================ BUILD (offline, network)
def _fetch(url, params=None, retries=4, timeout=180):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    from .. import config as C
    req = urllib.request.Request(url, headers={"User-Agent": C.USER_AGENT})
    token = os.environ.get("NOISE_SCORE_SOCRATA_TOKEN")
    if token and "cityofnewyork.us" in url:
        req.add_header("X-App-Token", token)
    err = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # network hiccup: try again
            err = e
    raise RuntimeError(f"fetch failed: {url}: {err}")


def _socrata(ds, params, page=50000):
    rows, off = [], 0
    while True:
        part = json.loads(_fetch(f"{SOCRATA}/{ds}.json", {**params, "$limit": page, "$offset": off}))
        rows += part
        if len(part) < page:
            return rows
        off += page


def _cached(cache, key, fn):
    """Raw pulls are kept in a cache folder so a rebuild does not hit the network twice."""
    p = cache / key
    if p.exists():
        return p.read_text()
    text = fn()
    p.write_text(text)
    return text


def _num(x, default=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _frozen_neutral_level(n, units, years, year_built, bldgclass):
    """Today's building level at a facade-neutral unit, without the time-of-day offset: model.building() minus its
    complaint-hour and floor parts. Same constants (config.py), same arithmetic."""
    from .. import config as C
    base = C.BOROUGH_BASELINE_PER_UNIT_YEAR["Manhattan"]
    rate = (n + C.BUILDING_SHRINK_K_UNIT_YEARS * base) / (units * years + C.BUILDING_SHRINK_K_UNIT_YEARS)
    level = C.BUILDING_BASELINE_DB + C.BUILDING_DB_PER_DOUBLING_OF_RATE * math.log2(rate / base)
    level = max(C.BUILDING_MIN_DB, min(C.BUILDING_MAX_DB, level))
    walkup = bldgclass[:1] in ("A", "B", "C")
    era = 0.0
    if 0 < year_built < 1940 and walkup:
        era = C.PREWAR_DB
    elif 0 < year_built < 1940:
        era = C.PREWAR_ELEVATOR_DB
    elif 1940 <= year_built < 2000:
        era = C.MIDCENTURY_DB
    if walkup:
        era += C.WALKUP_DB
    return level + era


def _pluto(cache):
    sel = ("bbl,cd,address,latitude,longitude,unitsres,unitstotal,numfloors,numbldgs,yearbuilt,bldgclass,landuse,"
           "lotarea,version")
    text = _cached(cache, "pluto_mn.json", lambda: json.dumps(_socrata(PLUTO_ID, {
        "$select": sel, "$where": "borough='MN' AND unitsres > 0 AND latitude IS NOT NULL", "$order": "bbl"})))
    return json.loads(text)


def _complaints(cache, start, end):
    key = f"c311_{start[:10]}_{end[:10]}.json"
    text = _cached(cache, key, lambda: json.dumps(_socrata(C311_ID, {
        "$select": "bbl,count(*) as n",
        "$where": f"complaint_type='Noise - Residential' AND borough='MANHATTAN' AND created_date>='{start}' AND created_date<'{end}'",
        "$group": "bbl"})))
    return {str(int(float(r["bbl"]))): int(r["n"]) for r in json.loads(text) if r.get("bbl")}


def _airbnb(cache):
    """The newest New York City scrape of Inside Airbnb: (date, [row]) of Manhattan entire-home listings."""
    try:
        page = _cached(cache, "iab_page.html", lambda: _fetch(IAB_PAGE).decode("utf-8", "ignore"))
        dates = re.findall(r"data\.insideairbnb\.com/united-states/ny/new-york-city/(\d{4}-\d{2}-\d{2})/", page)
        date = max(dates) if dates else IAB_FALLBACK_DATE
    except Exception:
        date = IAB_FALLBACK_DATE
    text = _cached(cache, f"iab_{date}.csv", lambda: _fetch(IAB_URL.format(date=date)).decode("utf-8", "ignore"))
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("neighbourhood_group") != "Manhattan" or r.get("room_type") != "Entire home/apt":
            continue
        rows.append({"lat": _num(r.get("latitude")), "lng": _num(r.get("longitude")),
                     "min": _num(r.get("minimum_nights"), 999), "ltm": _num(r.get("number_of_reviews_ltm"))})
    return date, rows


def _within(points, cell, radius, qx, qy):
    """Indices of the (x, y) points within radius metres of (qx, qy); points are bucketed in square cells."""
    out = []
    ci, cj = int(qx // cell), int(qy // cell)
    for i in (ci - 1, ci, ci + 1):
        for j in (cj - 1, cj, cj + 1):
            for k, x, y in points.get((i, j), ()):
                if (x - qx) ** 2 + (y - qy) ** 2 <= radius * radius:
                    out.append(k)
    return out


def build(out_dir, cache=None):
    """Pull PLUTO, 311 and Inside Airbnb; write <out_dir>/building.json.gz. Standard library only."""
    from .. import config as C
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache or os.environ.get("HUSHIQ_BUILD_CACHE") or Path(os.environ.get("TMPDIR", "/tmp")) / "hushiq_building_cache")
    cache.mkdir(parents=True, exist_ok=True)

    today = dt.date.today()
    t_end = today.isoformat() + "T00:00:00"
    t_mid = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat() + "T00:00:00"
    t_start = (today - dt.timedelta(days=2 * LOOKBACK_DAYS)).isoformat() + "T00:00:00"
    pluto = _pluto(cache)
    older = _complaints(cache, t_start, t_mid)     # month -24 to -12: what today's formula is fed with
    newer = _complaints(cache, t_mid, t_end)       # month -12 to now: what it should have predicted
    iab_date, iab_rows = _airbnb(cache)

    # lots
    lots = []
    for r in pluto:
        units = int(_num(r.get("unitsres")))
        lat, lng = _num(r.get("latitude")), _num(r.get("longitude"))
        if units <= 0 or not lat or not lng:
            continue
        bbl = str(int(_num(r.get("bbl"))))
        floors = int(_num(r.get("numfloors")))
        total = _num(r.get("unitstotal"))
        lots.append({
            "bbl": int(bbl), "lat": round(lat, 6), "lng": round(lng, 6), "units": units, "floors": floors,
            "nb": max(1, int(_num(r.get("numbldgs"), 1))), "cls": (r.get("bldgclass") or "")[:2],
            "yb": int(_num(r.get("yearbuilt"))),
            "rad": int(round(math.sqrt(_num(r.get("lotarea")) * 0.092903 / math.pi))),
            "comm": 1 if (total > units or str(r.get("landuse", "")) in ("4", "5")) else 0,
            "n_old": older.get(bbl, 0), "n_new": newer.get(bbl, 0),
        })

    # classes: complaints of the newer year against what today's formula expected from the older year
    base = C.BOROUGH_BASELINE_PER_UNIT_YEAR["Manhattan"]
    for l in lots:
        lvl = _frozen_neutral_level(l["n_old"], l["units"], 1.0, l["yb"], l["cls"] or "")
        l["exp"] = l["units"] * base * 2 ** ((lvl - C.BUILDING_BASELINE_DB) / C.BUILDING_DB_PER_DOUBLING_OF_RATE)
    scale = sum(l["n_new"] for l in lots) / sum(l["exp"] for l in lots)
    classes = {}
    for l in lots:
        c = classes.setdefault(l["cls"], [0, 0.0, 0.0, 0])
        c[0] += l["units"]
        c[1] += l["n_new"]
        c[2] += l["exp"] * scale
        c[3] += l["n_old"] + l["n_new"]
    classes = {k: [v[0], v[1], round(v[2], 2), round(100.0 * v[3] / (2.0 * v[0]), 3)] for k, v in classes.items()}
    total_units = sum(l["units"] for l in lots)
    manhattan_rate100 = round(100.0 * sum(l["n_old"] + l["n_new"] for l in lots) / (2.0 * total_units), 3)

    # typical apartments per floor: the apartment-weighted median over Manhattan
    upf = sorted((l["units"] / (l["floors"] * l["nb"]), l["units"]) for l in lots if l["floors"] > 0)
    half, acc, typical = sum(w for _, w in upf) / 2.0, 0.0, 0.0
    for v, w in upf:
        acc += w
        if acc >= half:
            typical = v
            break

    # short-stay listings and apartments within the blur radius of each lot
    mlat, mlng = 111_000.0, 84_300.0
    cell = STR_RADIUS_M
    lot_pts, str_pts = {}, {}
    for k, l in enumerate(lots):
        x, y = l["lng"] * mlng, l["lat"] * mlat
        l["_xy"] = (x, y)
        lot_pts.setdefault((int(x // cell), int(y // cell)), []).append((k, x, y))
    short = [r for r in iab_rows if r["min"] <= STR_MAX_MIN_NIGHTS and r["ltm"] >= 1]
    for k, r in enumerate(short):
        x, y = r["lng"] * mlng, r["lat"] * mlat
        str_pts.setdefault((int(x // cell), int(y // cell)), []).append((k, x, y))
    for l in lots:
        x, y = l["_xy"]
        l["u150"] = sum(lots[k]["units"] for k in _within(lot_pts, cell, STR_RADIUS_M, x, y))
        l["str"] = len(_within(str_pts, cell, STR_RADIUS_M, x, y))

    codes = sorted(classes)
    code_ix = {c: i for i, c in enumerate(codes)}
    cols = {k: [l[k] for l in lots] for k in ("lat", "lng", "bbl", "units", "floors", "nb", "rad", "comm", "str", "u150")}
    cols["cls"] = [code_ix[l["cls"]] for l in lots]
    version = pluto[0].get("version") if pluto else None
    doc = {
        "name": NAME, "version": 1, "built": today.isoformat(),
        "windows": {"older": [t_start[:10], t_mid[:10]], "newer": [t_mid[:10], t_end[:10]], "airbnb_scrape": iab_date},
        "datasets": [
            {"name": "NYC PLUTO, Primary Land Use Tax Lot Output", "id": PLUTO_ID, "rows": len(lots),
             "url": "https://data.cityofnewyork.us/resource/64uk-42ks", "window": f"version {version}, Manhattan lots with a residential unit"},
            {"name": "311 Service Requests, Noise - Residential", "id": C311_ID, "rows": sum(l["n_old"] + l["n_new"] for l in lots),
             "url": "https://data.cityofnewyork.us/resource/erm2-nwe9", "window": f"{t_start[:10]} to {t_end[:10]}"},
            {"name": "Inside Airbnb, New York City listings (CC BY 4.0)", "id": f"new-york-city/{iab_date}", "rows": len(iab_rows),
             "url": "https://insideairbnb.com/get-the-data/", "window": f"scrape of {iab_date}; {len(short)} short-stay entire-home listings in use"},
        ],
        "typical_upf": round(typical, 3), "manhattan_rate100": manhattan_rate100,
        "class_codes": codes, "classes": classes, "lots": cols,
    }
    with gzip.open(out_dir / f"{NAME}.json.gz", "wt") as f:
        json.dump(doc, f, separators=(",", ":"))
    return doc


# ================================================================ RUNTIME (pure standard library)
class _Index:
    """The built artifact, indexed once: a grid over lot centres, a bbl table and the per-class corrections."""

    def __init__(self, doc):
        self.doc = doc
        c = doc["lots"]
        self.c = c
        self.n = len(c["lat"])
        self.grid = GridIndex()
        self.by_bbl = {}
        for i in range(self.n):
            self.grid.add_point(c["lat"][i], c["lng"][i], i)
            self.by_bbl[c["bbl"][i]] = i
        self.codes = doc["class_codes"]
        self.typical_upf = float(doc["typical_upf"])
        self.rate100 = float(doc["manhattan_rate100"])
        # class ratio: next year's complaints over what today's formula expected, thin classes pulled toward 1
        self.rho, weights = {}, {}
        for code, (units, obs, exp, _) in doc["classes"].items():
            self.rho[code] = (obs + CLASS_PRIOR_COMPLAINTS) / (exp + CLASS_PRIOR_COMPLAINTS)
            weights[code] = units
        tot = float(sum(weights.values())) or 1.0
        self.center_log2 = sum(weights[k] * math.log2(self.rho[k]) for k in self.rho) / tot

    def class_delta(self, code):
        rho = self.rho.get(code)
        if rho is None:
            return None, 0.0
        raw = CLASS_SHARE * 10.0 * (math.log2(rho) - self.center_log2)
        return rho, max(-CLASS_CAP, min(CLASS_CAP, raw))

    def find(self, lat, lng, facts):
        """The tax lot this point belongs to: by bbl when the facts carry one, else the best lot near the point."""
        f = facts if isinstance(facts, dict) else {}
        try:
            b = int(float(f.get("bbl")))
            if b in self.by_bbl:
                return self.by_bbl[b]
        except (TypeError, ValueError):
            pass
        want_floors = f.get("floors")
        want_comm = f.get("commercial")
        c, best, best_score = self.c, None, None
        for d, i in self.grid.near(lat, lng, MATCH_MAX_M):
            allow = max(MATCH_BASE_M, min(LOT_RADIUS_FACTOR * c["rad"][i], MATCH_MAX_M))
            if d > allow:
                continue
            score = d / allow
            if want_floors and c["floors"][i] == want_floors:
                score -= FLOORS_BONUS
            if want_comm is not None and bool(c["comm"][i]) == bool(want_comm):
                score -= COMMERCIAL_BONUS
            if best_score is None or score < best_score:
                best, best_score = i, score
        return best


_INDEX = None
_TRIED = False


def _index():
    global _INDEX, _TRIED
    if not _TRIED:
        _TRIED = True
        doc = load(NAME)
        _INDEX = _Index(doc) if doc else None
    return _INDEX


def _reset(doc=None):
    """For tests: forget the cached artifact, or install one built in memory."""
    global _INDEX, _TRIED
    _INDEX, _TRIED = (_Index(doc) if doc else None), doc is not None


def class_label(code):
    return CLASS_LABEL_BY_CODE.get(code) or CLASS_LABEL_BY_LETTER.get(code[:1]) or "buildings of this type"


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _count_text(x, short=False):
    """'2 noise complaints' (or just '6' after the first mention), counts only."""
    v = float(x)
    if v < 0.5:
        return "fewer than 1" if short else "fewer than 1 noise complaint"
    n = int(round(v))
    return str(n) if short else f"{n} noise complaint" + ("" if n == 1 else "s")


def upgrade(lat, lng, today, facts):
    """Neighbors level per slot, the math-board steps and the renter-facing sentences. Never raises."""
    try:
        slots_today = {s: float((today or {})[s]) for s in SLOTS}
    except Exception:
        slots_today = {s: 0.0 for s in SLOTS}
    try:
        idx = _index()
        if idx is None or lat is None or lng is None or not (math.isfinite(float(lat)) and math.isfinite(float(lng))):
            return passthrough(NAME, slots_today)
        return _upgrade(idx, float(lat), float(lng), slots_today, facts)
    except Exception:
        return passthrough(NAME, slots_today)


def _unmatched(today):
    return Upgrade(levels=dict(today), steps=[
        Step(id="building.today", label="Neighbors: today's estimate", kind="today_input", value=dict(today), unit="index",
             source="today's model", feeds=["building.level"], status="live"),
        Step(id="building.level", label="Neighbors level", kind="result", value=dict(today), unit="index", source="",
             formula=f"no Manhattan apartment building within {MATCH_BASE_M:g} m of this point, so today's estimate is unchanged",
             status="live")])


def _upgrade(idx, lat, lng, today, facts):
    i = idx.find(lat, lng, facts)
    if i is None:
        return _unmatched(today)
    c = idx.c
    units, floors, nb = c["units"][i], c["floors"][i], c["nb"][i]
    code = idx.codes[c["cls"][i]]
    cls_units, cls_obs, cls_exp, cls_rate100 = idx.doc["classes"].get(code) or (0, 0, 0, None)
    rho, d_type = idx.class_delta(code)
    upf = units / (floors * nb) if floors > 0 else None
    if upf is not None:
        d_hall = max(0.0, min(HALLWAY_CAP, HALLWAY_PER_DOUBLING * math.log2(upf / idx.typical_upf))) if upf > idx.typical_upf else 0.0
    else:
        d_hall = 0.0
    n_str, u150 = c["str"][i], c["u150"][i]
    share = 1000.0 * n_str / u150 if u150 > 0 else 0.0
    d_str = min(STR_CAP, STR_PER_1000 * share)
    total = max(-TOTAL_CAP, min(TOTAL_CAP, d_type + d_hall + d_str))
    levels = {s: max(LEVEL_MIN, min(LEVEL_MAX, today[s] + total)) for s in SLOTS}

    steps = []
    add = steps.append
    pl = "NYC PLUTO (64uk-42ks)"
    # ---- today's inputs (live)
    add(Step(id="building.units", label="Neighbors: apartments in the building", kind="today_input", value=units,
             unit="apartments", source=pl, formula="residential units on the tax lot",
             feeds=["building.today", "building.upf"], status="live"))
    add(Step(id="building.floors", label="Neighbors: floors in the building", kind="today_input", value=floors or None,
             unit="floors", source=pl, formula="floors of the tallest building on the lot",
             feeds=["building.upf"], status="live"))
    add(Step(id="building.today", label="Neighbors: today's estimate", kind="today_input", value={s: _r(today[s]) for s in SLOTS}, unit="index",
             source="today's model; 311 Noise - Residential (erm2-nwe9)",
             formula="residential noise complaints per apartment over 24 months, pulled toward the Manhattan rate; "
                     "46 at that rate, +10 per doubling; pre-war and walk-up buildings add 1 to 5",
             feeds=["building.level"], status="live"))
    # ---- new inputs: building type
    add(Step(id="building.class_code", label="Neighbors: building class", kind="new_input", value=code or None, unit="",
             source=pl, formula=f"city building class code ({class_label(code)})", feeds=["building.class_ratio"], status="new"))
    add(Step(id="building.class_ratio", label="Neighbors: complaints vs expected, this type of building", kind="new_input",
             value=_r(rho), unit="x", source="311 Noise - Residential (erm2-nwe9) with PLUTO building class, two 12-month blocks",
             formula="for buildings of this class: noise complaints in the latest 12 months divided by what today's formula "
                     f"expected from the 12 months before ({int(cls_obs)} against {int(round(cls_exp))}, {int(cls_units)} apartments)",
             feeds=["building.rule_type"], status="new"))
    add(Step(id="building.class_typical", label="Neighbors: the same ratio for a typical Manhattan apartment", kind="new_input",
             value=_r(2 ** idx.center_log2), unit="x", source="311 Noise - Residential (erm2-nwe9) with PLUTO building class",
             formula="average of the class ratios over every Manhattan apartment, weighted by apartments",
             feeds=["building.rule_type"], status="new"))
    for sid, label, val, f in (
            ("building.j_type_share", "Neighbors: share of the type gap we add", CLASS_SHARE, "half the gap is how likely people are to call 311"),
            ("building.j_type_cap", "Neighbors: biggest building-type move", CLASS_CAP, "no class moves the level more than this")):
        add(Step(id=sid, label=label, kind="new_input", value=val, unit="" if sid.endswith("share") else "index",
                 source="judgment", formula=f, feeds=["building.rule_type"], status="judgment"))
    add(Step(id="building.rule_type", label="Neighbors: building type adjustment", kind="rule", value=_r(d_type), unit="index",
             source="", formula="0.5 x 10 x log2(this type's ratio / the typical ratio), kept within the type cap",
             feeds=["building.adjust"], status="new"))
    # ---- new inputs: hallway
    add(Step(id="building.upf", label="Neighbors: apartments per floor", kind="new_input", value=_r(upf, 1), unit="apartments",
             source=pl, formula="apartments on the lot / (floors x buildings on the lot)", feeds=["building.rule_hall"], status="new"))
    add(Step(id="building.upf_typical", label="Neighbors: typical apartments per floor in Manhattan", kind="new_input",
             value=_r(idx.typical_upf, 1), unit="apartments", source=pl,
             formula="the middle value over every Manhattan apartment", feeds=["building.rule_hall"], status="new"))
    for sid, label, val, f in (
            ("building.j_hall_rate", "Neighbors: index per doubling of apartments per floor", HALLWAY_PER_DOUBLING,
             "more doors on the hallway, more chatter; the 311 check does not support it"),
            ("building.j_hall_cap", "Neighbors: biggest hallway move", HALLWAY_CAP, "a tie-breaker, never a driver")):
        add(Step(id=sid, label=label, kind="new_input", value=val, unit="index", source="judgment", formula=f,
                 feeds=["building.rule_hall"], status="judgment"))
    add(Step(id="building.rule_hall", label="Neighbors: shared hallway adjustment", kind="rule", value=_r(d_hall), unit="index",
             source="", formula="0.5 x log2(apartments per floor / typical), nothing below typical, kept within the hallway cap",
             feeds=["building.adjust"], status="new"))
    # ---- new inputs: short stays
    add(Step(id="building.str_n", label="Neighbors: short-stay whole-apartment listings within 150 m", kind="new_input",
             value=n_str, unit="listings", source="Inside Airbnb, New York City (CC BY 4.0)",
             formula="entire-home listings with a minimum stay under 30 nights and a review in the last year; "
                     "locations are blurred by up to 150 m", feeds=["building.rule_str"], status="new"))
    add(Step(id="building.u150", label="Neighbors: apartments within 150 m", kind="new_input", value=u150, unit="apartments",
             source=pl, formula="residential units on every tax lot whose centre is within 150 m", feeds=["building.rule_str"], status="new"))
    for sid, label, val, f in (
            ("building.j_str_rate", "Neighbors: index per listing per 1,000 apartments", STR_PER_1000, "transient neighbors party more"),
            ("building.j_str_cap", "Neighbors: biggest short-stay move", STR_CAP, "the signal is faint, so the move is small")):
        add(Step(id=sid, label=label, kind="new_input", value=val, unit="index", source="judgment", formula=f,
                 feeds=["building.rule_str"], status="judgment"))
    add(Step(id="building.rule_str", label="Neighbors: short-stay adjustment", kind="rule", value=_r(d_str), unit="index",
             source="", formula="0.5 x listings per 1,000 apartments within 150 m, kept within the short-stay cap",
             feeds=["building.adjust"], status="new"))
    # ---- sum and result
    add(Step(id="building.j_total_cap", label="Neighbors: biggest total move", kind="new_input", value=TOTAL_CAP, unit="index",
             source="judgment", formula="the three adjustments together never move the level more than this",
             feeds=["building.adjust"], status="judgment"))
    add(Step(id="building.adjust", label="Neighbors adjustment", kind="rule", value=_r(total), unit="index", source="",
             formula="building type + shared hallway + short stays, kept within the total cap",
             feeds=["building.level"], status="new"))
    add(Step(id="building.level", label="Neighbors level", kind="result", value={s: _r(levels[s]) for s in SLOTS}, unit="index",
             source="", formula="today's estimate + the adjustment, the same for night, early morning and day", status="new"))

    evidence = []
    if upf is not None:
        evidence.append("About one apartment per floor." if upf < 1.5 else f"About {int(round(upf))} apartments share each floor.")
    evidence.append(f"Buildings of this type ({class_label(code)}) average {_count_text(cls_rate100)} per 100 apartments a year; "
                    f"the Manhattan average is {_count_text(idx.rate100, short=True)}." if code and cls_rate100 is not None else "")
    evidence = [e for e in evidence if e]
    if n_str >= 1:
        evidence.append(f"{n_str} whole-apartment short-term rental{'' if n_str == 1 else 's'} (under 30 nights) "
                        f"listed within about 150 m.")
    return Upgrade(levels=levels, steps=steps, evidence=evidence[:3])
