"""Engine v2 recalibration [V10]: the five sources recomputed on the same pulls with the research numbers of
2026-10-29 (HIQ-71). (Hackathon work, Oct 29.)

model.py stays frozen. This module repeats its math at the facade-neutral unit (no floor, front) and swaps in only
the numbers that move a rank (config_v2.py, [V10]). Given config.py's numbers it returns model.py's levels exactly,
which the tests and the sample build check. Floor and side are not here: they are v2.position_db.

The Manhattan sample is recomputed the same way from the pulls the frozen baseline was built from
(build_sample), so the renter and the sample stay on one scale.
"""
import datetime as dt
import hashlib
import json
import math

from . import config as C
from . import config_v2 as V
from . import model
from .geo import haversine_m, point_to_multiline_m
from .upgrades import DATA, Step

SOURCES = ("street", "nightlife", "building", "sirens", "construction")
SAMPLE = DATA / "recal_sample.json"

# Today's numbers, as model.py uses them.
TODAY = {
    "road_speed_db_per_5mph": C.ROAD_SPEED_DB_PER_5MPH_OVER_25, "road_speed_classes": None,
    "road_two_way_db": C.ROAD_TWO_WAY_DB, "street_311_max_db": C.STREET_311_MAX_DB, "street_none_db": C.STREET_NONE_DB,
    "venue_base_db": dict(C.VENUE_BASE_DB), "nightlife_311_max_db": C.NIGHTLIFE_311_MAX_DB,
    "nightlife_311_slots": tuple(model.WINDOWS), "midcentury_db": ((2000, C.MIDCENTURY_DB),),
    "sirens_db_per_doubling": C.SIRENS_DB_PER_DOUBLING,
    "construction_311_db_per_doubling": C.CONSTRUCTION_311_DB_PER_DOUBLING,
}
# The research numbers [V10].
NUMBERS = {
    "road_speed_db_per_5mph": V.ROAD_SPEED_DB_PER_5MPH, "road_speed_classes": tuple(V.ROAD_SPEED_CLASSES),
    "road_two_way_db": V.ROAD_TWO_WAY_DB, "street_311_max_db": V.STREET_311_MAX_DB, "street_none_db": V.STREET_NONE_DB,
    "venue_base_db": dict(V.VENUE_BASE_DB), "nightlife_311_max_db": V.NIGHTLIFE_311_MAX_DB,
    "nightlife_311_slots": tuple(V.NIGHTLIFE_311_SLOTS), "midcentury_db": tuple(V.MIDCENTURY_DB),
    "sirens_db_per_doubling": V.SIRENS_DB_PER_DOUBLING,
    "construction_311_db_per_doubling": V.CONSTRUCTION_311_DB_PER_DOUBLING,
}

# What changed, per source, in plain words for the math board.
CHANGES = {
    "street": (f"speed adds {V.ROAD_SPEED_DB_PER_5MPH:g} per 5 mph over 25 on highways and ramps only "
               f"(was {C.ROAD_SPEED_DB_PER_5MPH_OVER_25:g} on every road); two-way adds {V.ROAD_TWO_WAY_DB:g} "
               f"(was {C.ROAD_TWO_WAY_DB:g}); the 311 add stops at {V.STREET_311_MAX_DB:g} (was {C.STREET_311_MAX_DB:g}); "
               f"no road within {C.RADIUS_ROADS_M} m is {V.STREET_NONE_DB:g} (was {C.STREET_NONE_DB:g})"),
    "nightlife": (f"hotels, theatres and other venues {V.VENUE_BASE_DB['venue']:g} at 10 m (was {C.VENUE_BASE_DB['venue']:g}); "
                  f"restaurants {V.VENUE_BASE_DB['restaurant']:g} (was {C.VENUE_BASE_DB['restaurant']:g}); "
                  f"the 311 add as today, up to {V.NIGHTLIFE_311_MAX_DB:g} in every slot (decision U6)"),
    "building": ("built 1940 to 1967 adds 2, 1968 to 1976 adds 1, 1977 to 1999 adds 0 "
                 f"(was {C.MIDCENTURY_DB:g} for all three)"),
    "sirens": (f"each station loses {V.SIRENS_DB_PER_DOUBLING:g} per doubling of distance beyond "
               f"{C.SIRENS_REF_DISTANCE_M:g} m (was {C.SIRENS_DB_PER_DOUBLING:g})"),
    "construction": (f"each doubling of construction complaints adds {V.CONSTRUCTION_311_DB_PER_DOUBLING:g} "
                     f"(was {C.CONSTRUCTION_311_DB_PER_DOUBLING:g})"),
}


def numbers_sha(K=None):
    """Which numbers a sample was built with, so a stale one is caught."""
    raw = json.dumps(K or NUMBERS, sort_keys=True, default=list)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- the five sources, facade-neutral
def _road_class(rw, travel):
    if rw == "2":
        return "highway"
    if rw == "9":
        return "ramp"
    if rw == "3":
        return "bridge"
    if travel >= 3:
        return "arterial"
    return "two_lane" if travel == 2 else "one_lane"


def street(inputs, K):
    """model.street at the facade-neutral unit, with K's numbers."""
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    by_street = {}
    for r in inputs.get("roads") or []:
        rw = str(r.get("rw_type", ""))
        if rw in C.ROAD_IGNORE_RW_TYPES:
            continue
        travel = int(model._f(r.get("number_travel_lanes"), 1) or 1)
        cls = _road_class(rw, travel)
        base = C.ROAD_BASE_DB[cls]
        if r.get("snow_priority") == "C" and rw == "1":
            base += C.ROAD_SNOW_CRITICAL_DB
        speed = model._f(r.get("posted_speed"), 25) or 25
        if K["road_speed_classes"] is None or cls in K["road_speed_classes"]:
            base += max(0.0, (speed - 25) / 5) * K["road_speed_db_per_5mph"]
        if r.get("trafdir") == "TW":
            base += K["road_two_way_db"]
        d = point_to_multiline_m(lat, lng, r.get("the_geom"))
        if d is None or d > C.RADIUS_ROADS_M:
            continue
        d = max(d, C.ROAD_REF_DISTANCE_M)
        level = base - C.ROAD_DB_PER_DOUBLING * math.log2(d / C.ROAD_REF_DISTANCE_M)
        name = (r.get("full_street_name") or "unnamed").strip()
        if name not in by_street or level > by_street[name]:
            by_street[name] = level
    levels = list(by_street.values())
    for st in inputs.get("stations") or []:
        if st.get("structure") in C.RAIL_LOUD_STRUCTURES:
            d = max(haversine_m(lat, lng, model._f(st["gtfs_latitude"]), model._f(st["gtfs_longitude"])), C.RAIL_REF_DISTANCE_M)
            levels.append(C.RAIL_BASE_DB - C.RAIL_DB_PER_DOUBLING * math.log2(d / C.RAIL_REF_DISTANCE_M))
    base = model.energy_sum(levels)
    if base is None:
        base = K["street_none_db"]
    rows = [r for r in inputs.get("complaints") or []
            if (r.get("complaint_type") == "Noise - Vehicle"
                or (r.get("complaint_type") == "Noise - Street/Sidewalk" and r.get("descriptor") not in C.PARTY_DESCRIPTORS))
            and model._within(r, lat, lng, C.RADIUS_BLOCK_M)]
    per_year, _ = model._window_counts(rows, years)
    return {w: base + C.STREET_WINDOW_OFFSET[w]
            + model.log_bump(per_year[w], C.STREET_311_REF_PER_YEAR, cap=K["street_311_max_db"]) for w in model.WINDOWS}


def nightlife(inputs, K):
    """model.nightlife at the facade-neutral unit, with K's numbers."""
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    levels = []
    for r in inputs.get("liquor") or []:
        cls = C.VENUE_CLASSES.get(r.get("description"))
        coords = (r.get("georeference") or {}).get("coordinates") or [None, None]
        if not cls or coords[0] is None:
            continue
        d = max(haversine_m(lat, lng, coords[1], coords[0]), C.VENUE_REF_DISTANCE_M)
        levels.append(K["venue_base_db"][cls] - C.VENUE_DB_PER_DOUBLING * math.log2(d / C.VENUE_REF_DISTANCE_M))
    base = model.energy_sum(levels)
    base = C.NIGHTLIFE_NONE_DB if base is None else min(base, C.VENUE_SUM_CAP_DB)
    rows = [r for r in inputs.get("complaints") or []
            if r.get("complaint_type") in ("Noise - Commercial", "Noise - Street/Sidewalk", "Noise - Park")
            and r.get("descriptor") in C.PARTY_DESCRIPTORS
            and model._within(r, lat, lng, C.RADIUS_NIGHTLIFE_M)]
    per_year, _ = model._window_counts(rows, years)
    out = {}
    for w in model.WINDOWS:
        bump = (model.log_bump(per_year[w], C.NIGHTLIFE_311_REF_PER_YEAR, cap=K["nightlife_311_max_db"])
                if w in K["nightlife_311_slots"] else 0.0)
        out[w] = base + C.NIGHTLIFE_WINDOW_OFFSET[w] + bump
    return out


def _midcentury(pl, K):
    """The era term that changes: 1940 to 1999 buildings. Every other era is as model.building has it."""
    yb = int(model._f((pl or {}).get("yearbuilt"), 0) or 0)
    if not 1940 <= yb < 2000:
        return 0.0
    return next(db for until, db in K["midcentury_db"] if yb < until)


def building(inputs, pl, K):
    """model.building at the facade-neutral unit, with K's era numbers."""
    today = model.building(inputs, model.Unit(floor=None, position="front"), pl)["levels"]
    delta = _midcentury(pl, K) - _midcentury(pl, TODAY)
    return {w: today[w] + delta for w in model.WINDOWS}


def sirens(inputs, K):
    """model.sirens at the facade-neutral unit, with K's distance slope."""
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    levels = []
    for r in inputs.get("facilities") or []:
        kind = r.get("kind")
        la, ln = model._f(r.get("latitude")), model._f(r.get("longitude"))
        if kind not in C.SIRENS_BASE_DB or la is None or ln is None:
            continue
        d = haversine_m(lat, lng, la, ln)
        if d > C.RADIUS_SIRENS_M:
            continue
        levels.append(C.SIRENS_BASE_DB[kind]
                      - K["sirens_db_per_doubling"] * math.log2(max(d, C.SIRENS_REF_DISTANCE_M) / C.SIRENS_REF_DISTANCE_M))
    base = model.energy_sum(levels)
    base = C.SIRENS_NONE_DB if base is None else min(base, C.SIRENS_SUM_CAP_DB)
    return {w: base + C.SIRENS_WINDOW_OFFSET[w] for w in model.WINDOWS}


def construction(inputs, K):
    """model.construction at the facade-neutral unit, with K's complaint slope."""
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    n311 = sum(1 for r in inputs.get("complaints") or []
               if r.get("complaint_type") == "Noise"
               and any(k in (r.get("descriptor") or "").lower() for k in C.CONSTRUCTION_DESCRIPTOR_KEYS)
               and model._within(r, lat, lng, C.RADIUS_BLOCK_M))
    today = dt.date.fromisoformat(inputs.get("as_of") or dt.date.today().isoformat())
    active = 0
    for p in inputs.get("permits") or []:
        if p.get("work_type") not in C.CONSTRUCTION_LOUD_WORK_TYPES:
            continue
        exp = (p.get("expired_date") or "")[:10]
        if exp and dt.date.fromisoformat(exp) < today:
            continue
        active += 1
    if not n311 and not active:
        base = C.CONSTRUCTION_NONE_DB
    else:
        bump = (K["construction_311_db_per_doubling"] * math.log2(1 + n311 / years)
                + C.CONSTRUCTION_PERMIT_DB_PER_DOUBLING * math.log2(1 + active))
        base = C.CONSTRUCTION_BASE_DB + min(C.CONSTRUCTION_MAX_BUMP_DB, bump)
    return {w: base + C.CONSTRUCTION_WINDOW_OFFSET[w] for w in model.WINDOWS}


def levels(inputs, K=None):
    """{source: {slot: level}} at the facade-neutral unit. K=None is the research numbers; recal.TODAY is model.py."""
    K = K or NUMBERS
    pl = inputs.get("pluto") or {}
    return {"street": street(inputs, K), "nightlife": nightlife(inputs, K), "building": building(inputs, pl, K),
            "sirens": sirens(inputs, K), "construction": construction(inputs, K)}


# ---------------------------------------------------------------- the math board
def steps(name, today, recal, feeds):
    """Two boxes that feed a source's first step: today's model as built, and what the research changed."""
    delta = {w: round(recal[w] - today[w], 2) for w in model.WINDOWS}
    return [
        Step(id=f"{name}.as_built", label="Today's model, as built", kind="today_input",
             value={w: round(today[w], 2) for w in model.WINDOWS}, unit="index", source="today's model (config.py)",
             formula="the frozen model's level for this address, before the research numbers", feeds=[f"{name}.recal"],
             status="live"),
        Step(id=f"{name}.recal", label="Research recalibration", kind="rule", value=delta, unit="index",
             source="noise research, 2026-10-29 (report: Noise levels and sound transmission)",
             formula=f"same data, new numbers: {CHANGES[name]}", feeds=feeds, status="new"),
    ]


# ---------------------------------------------------------------- the Manhattan sample (offline)
_sample = None


def sample():
    """{bbl: {source: {slot: level}}} for the Manhattan sample with these numbers, or None when not built or stale."""
    global _sample
    if _sample is None:
        doc = json.loads(SAMPLE.read_text()) if SAMPLE.exists() else None
        ok = doc and doc.get("numbers_sha") == numbers_sha()
        _sample = {r["bbl"]: r["levels"] for r in doc["samples"]} if ok else False
    return _sample or None


def _reset():
    global _sample
    _sample = None


def build_sample(b=None):
    """Recompute every sample building from the pulls the baseline was built from (the pull cache, read past its
    TTL; anything missing is pulled again for the baseline's date). Checks today's numbers reproduce the frozen
    baseline before writing. Needs the network once, for the sample's PLUTO rows."""
    from . import baseline, sources
    b = b or baseline.load()
    as_of = dt.date.fromisoformat(b["as_of"])
    ttl, C.CACHE_TTL_DAYS = C.CACHE_TTL_DAYS, 3650
    try:
        bbls = [baseline._bbl(s["bbl"]) for s in b["samples"]]
        where = "bbl in (" + ",".join(f"'{x}'" for x in bbls) + ")"
        pl_rows = sources._get("pluto_sample", baseline.PLUTO_URL, {
            "$select": "bbl,address,borough,yearbuilt,yearalter1,yearalter2,numfloors,bldgclass,unitsres,unitstotal,"
                       "landuse,lotfront,bldgdepth,zonedist1", "$where": where, "$limit": 1000})
        pluto = {baseline._bbl(r["bbl"]): r for r in pl_rows}
        rows, worst = [], 0.0
        for s in b["samples"]:
            a = {"query": s["address"], "label": s["address"], "lat": s["lat"], "lng": s["lng"], "bbl": s["bbl"],
                 "bin": None, "borough": "Manhattan"}
            inputs = sources.pull_at(a, today=as_of, pluto_row=pluto.get(baseline._bbl(s["bbl"])) or {})
            then = levels(inputs, TODAY)
            worst = max([worst] + [abs(then[n][w] - s["levels"][n][w]) for n in SOURCES for w in model.WINDOWS])
            now = levels(inputs)
            rows.append({"bbl": s["bbl"], "levels": {n: {w: round(v, 3) for w, v in now[n].items()} for n in SOURCES}})
    finally:
        C.CACHE_TTL_DAYS = ttl
    if worst > 0.01:
        raise RuntimeError(f"today's numbers no longer reproduce the frozen baseline (off by {worst:.3f}); not written")
    doc = {"name": "recal_sample", "built": dt.date.today().isoformat(), "as_of": b["as_of"], "numbers_sha": numbers_sha(),
           "numbers": {k: list(v) if isinstance(v, tuple) else v for k, v in NUMBERS.items()},
           "check": {"max_diff_vs_baseline_with_todays_numbers": round(worst, 4)}, "samples": rows}
    DATA.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps(doc, separators=(",", ":")))
    _reset()
    return doc


if __name__ == "__main__":
    d = build_sample()
    print(f"recalibrated sample: {len(d['samples'])} buildings, check {d['check']}")
