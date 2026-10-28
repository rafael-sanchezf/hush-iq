"""The score. Pure functions over the raw pulls: no network, so it is testable and replayable.

Pipeline, per time window (night, early, day):
  1. each ingredient -> a pseudo-dB exposure (street, nightlife, building, sirens, construction)
  2. position adjusts the outdoor ingredients (floor, front/rear) and the building one (top floor, first floor)
  3. the renter's profile adds dB to the ingredients they named and weights the windows
  4. ingredients combine by energy sum within a window; windows average by weight
  5. score = 100 - 2 * (L - 30), higher is quieter
"""
import datetime as dt
import math
from dataclasses import dataclass, field

from . import config as C
from .geo import haversine_m, point_to_multiline_m

WINDOWS = list(C.WINDOWS)  # night, early, day


# ---------------------------------------------------------------- inputs the renter supplies
@dataclass
class Unit:
    floor: int | None = None          # 1 = ground floor
    position: str = "unknown"         # front | rear | unknown


@dataclass
class Profile:
    sleep: str = "normal"             # light | normal | heavy
    wfh: bool = False
    bothers: list = field(default_factory=list)   # traffic | people | neighbors | sirens | construction


# ---------------------------------------------------------------- helpers
def energy_sum(levels):
    levels = [l for l in levels if l is not None]
    if not levels:
        return None
    return 10 * math.log10(sum(10 ** (l / 10) for l in levels))


def to_score(level):
    return int(round(max(0.0, min(100.0, 100 - C.SCALE_SLOPE * (level - C.SCALE_QUIET_DB)))))


def window_of(hour):
    for name, (a, b) in C.WINDOWS.items():
        if a < b and a <= hour < b:
            return name
        if a > b and (hour >= a or hour < b):
            return name
    return "day"


def _hour(created):
    try:
        return dt.datetime.fromisoformat(created[:19]).hour
    except (ValueError, TypeError):
        return None


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def floor_attenuation(unit):
    if not unit.floor or unit.floor <= 1:
        return 0.0
    return max(C.FLOOR_MAX_ATTENUATION_DB, C.FLOOR_DB_PER_FLOOR * (unit.floor - 1))


def log_bump(n_per_year, ref, per_doubling=3.0, cap=None):
    """0 at n=0, `per_doubling` at n=ref, grows by per_doubling per doubling of (1 + n/ref)."""
    v = per_doubling * math.log2(1 + n_per_year / ref)
    return min(cap, v) if cap is not None else v


def _window_counts(rows, years):
    counts = {w: 0.0 for w in WINDOWS}
    for r in rows:
        h = _hour(r.get("created_date"))
        if h is not None:
            counts[window_of(h)] += 1
    return {w: counts[w] / years for w in WINDOWS}, sum(counts.values())


# ---------------------------------------------------------------- 1. street
def street(inputs, unit):
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    ev = []
    by_street = {}
    for r in inputs.get("roads") or []:
        rw = str(r.get("rw_type", ""))
        if rw in C.ROAD_IGNORE_RW_TYPES:
            continue
        travel = int(_f(r.get("number_travel_lanes"), 1) or 1)
        if rw == "2":
            cls = "highway"
        elif rw == "9":
            cls = "ramp"
        elif rw == "3":
            cls = "bridge"
        elif travel >= 3:
            cls = "arterial"
        elif travel == 2:
            cls = "two_lane"
        else:
            cls = "one_lane"
        base = C.ROAD_BASE_DB[cls]
        critical = r.get("snow_priority") == "C" and rw == "1"
        if critical:
            base += C.ROAD_SNOW_CRITICAL_DB
        speed = _f(r.get("posted_speed"), 25) or 25
        base += max(0.0, (speed - 25) / 5) * C.ROAD_SPEED_DB_PER_5MPH_OVER_25
        if r.get("trafdir") == "TW":
            base += C.ROAD_TWO_WAY_DB
        d = point_to_multiline_m(lat, lng, r.get("the_geom"))
        if d is None or d > C.RADIUS_ROADS_M:
            continue
        d = max(d, C.ROAD_REF_DISTANCE_M)
        level = base - C.ROAD_DB_PER_DOUBLING * math.log2(d / C.ROAD_REF_DISTANCE_M)
        name = (r.get("full_street_name") or "unnamed").strip()
        cur = by_street.get(name)
        if cur is None or level > cur["level"]:
            by_street[name] = {"level": level, "cls": cls, "d": d, "lanes": travel, "speed": speed, "critical": critical}
    levels = []
    for name, s in sorted(by_street.items(), key=lambda kv: -kv[1]["level"]):
        levels.append(s["level"])
        ev.append(f"{name}: {s['cls'].replace('_', ' ')}, {s['lanes']} travel lane{'s' if s['lanes'] != 1 else ''}, {int(s['speed'])} mph"
                  + (", bus or truck route" if s["critical"] else "") + f", {int(s['d'])} m away")
    # elevated rail (station structure as a proxy for the line)
    for st in inputs.get("stations") or []:
        if st.get("structure") in C.RAIL_LOUD_STRUCTURES:
            d = haversine_m(lat, lng, _f(st["gtfs_latitude"]), _f(st["gtfs_longitude"]))
            d = max(d, C.RAIL_REF_DISTANCE_M)
            level = C.RAIL_BASE_DB - C.RAIL_DB_PER_DOUBLING * math.log2(d / C.RAIL_REF_DISTANCE_M)
            levels.append(level)
            ev.append(f"{st.get('structure')} subway ({st.get('daytime_routes')}) at {st.get('stop_name')}, {int(d)} m away")
    base = energy_sum(levels)
    if base is None:
        base = C.STREET_NONE_DB
        ev.append("no road segment within radius")
    # 311 pressure: street/sidewalk and vehicle complaints within the block radius
    rows = [r for r in inputs.get("complaints") or []
            if (r.get("complaint_type") == "Noise - Vehicle"
                or (r.get("complaint_type") == "Noise - Street/Sidewalk" and r.get("descriptor") not in C.PARTY_DESCRIPTORS))
            and _within(r, lat, lng, C.RADIUS_BLOCK_M)]
    per_year, n = _window_counts(rows, years)
    if n:
        ev.append(f"{int(n)} vehicle noise complaints to 311 within {C.RADIUS_BLOCK_M} m in {inputs['lookback_months']} months"
                  + _top_descriptors(rows))
    att = floor_attenuation(unit) + C.POSITION_DB.get(unit.position, C.POSITION_DB["unknown"])
    out = {}
    for w in WINDOWS:
        bump = log_bump(per_year[w], C.STREET_311_REF_PER_YEAR, cap=C.STREET_311_MAX_DB)
        out[w] = base + C.STREET_WINDOW_OFFSET[w] + bump + att
    return {"name": "street", "label": "Street", "levels": out, "raw_level": base,
            "evidence": ev, "position_db": att, "temporary": False}


def _within(row, lat, lng, radius_m):
    la, ln = _f(row.get("latitude")), _f(row.get("longitude"))
    if la is None or ln is None:
        return False
    return haversine_m(lat, lng, la, ln) <= radius_m


def _top_descriptors(rows, k=2):
    counts = {}
    for r in rows:
        d = r.get("descriptor") or "?"
        counts[d] = counts.get(d, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:k]
    return " (" + ", ".join(f"{d.lower()} {n}" for d, n in top) + ")" if top else ""


# ---------------------------------------------------------------- 2. nightlife
def nightlife(inputs, unit, pl):
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    ev = []
    venues = []
    for r in inputs.get("liquor") or []:
        cls = C.VENUE_CLASSES.get(r.get("description"))
        if not cls:
            continue
        g = r.get("georeference") or {}
        coords = g.get("coordinates") or [None, None]
        if coords[0] is None:
            continue
        d = max(haversine_m(lat, lng, coords[1], coords[0]), C.VENUE_REF_DISTANCE_M)
        level = C.VENUE_BASE_DB[cls] - C.VENUE_DB_PER_DOUBLING * math.log2(d / C.VENUE_REF_DISTANCE_M)
        venues.append((level, cls, r.get("legalname"), r.get("actualaddressofpremises"), d))
    venues.sort(key=lambda v: -v[0])
    base = energy_sum([v[0] for v in venues])
    if base is None:
        base = C.NIGHTLIFE_NONE_DB
        ev.append(f"no licensed bar or restaurant within {C.RADIUS_NIGHTLIFE_M} m")
    else:
        base = min(base, C.VENUE_SUM_CAP_DB)
        kinds = {}
        for v in venues:
            kinds[v[1]] = kinds.get(v[1], 0) + 1
        ev.append(f"{len(venues)} licensed venues within {C.RADIUS_NIGHTLIFE_M} m: "
                  + ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in sorted(kinds.items())))
        for v in venues[:3]:
            ev.append(f"nearest loud: {v[2]} ({v[1]}), {v[3]}, {int(v[4])} m")
    rows = [r for r in inputs.get("complaints") or []
            if r.get("complaint_type") in ("Noise - Commercial", "Noise - Street/Sidewalk", "Noise - Park")
            and r.get("descriptor") in C.PARTY_DESCRIPTORS
            and _within(r, lat, lng, C.RADIUS_NIGHTLIFE_M)]
    per_year, n = _window_counts(rows, years)
    if n:
        ev.append(f"{int(n)} party, music or loud-talking complaints within {C.RADIUS_NIGHTLIFE_M} m in {inputs['lookback_months']} months; "
                  f"{int(per_year['night'] * years)} of them 10 pm to 5 am")
    att = floor_attenuation(unit) + C.POSITION_DB.get(unit.position, C.POSITION_DB["unknown"])
    commercial = _has_commercial(pl)
    if commercial and unit.floor and unit.floor <= 2:
        att += C.GROUND_FLOOR_COMMERCIAL_DB
        ev.append("commercial space on the ground floor of this building")
    out = {}
    for w in WINDOWS:
        bump = log_bump(per_year[w], C.NIGHTLIFE_311_REF_PER_YEAR, cap=C.NIGHTLIFE_311_MAX_DB)
        out[w] = base + C.NIGHTLIFE_WINDOW_OFFSET[w] + bump + att
    return {"name": "nightlife", "label": "Nightlife", "levels": out, "raw_level": base,
            "evidence": ev, "position_db": att, "temporary": False}


def _has_commercial(pl):
    if not pl:
        return False
    tot, res = _f(pl.get("unitstotal"), 0) or 0, _f(pl.get("unitsres"), 0) or 0
    return tot > res or str(pl.get("landuse", "")) in ("4", "5")


# ---------------------------------------------------------------- 3. building (neighbors)
def building(inputs, unit, pl):
    a = inputs["address"]
    years = inputs["lookback_months"] / 12
    ev = []
    rows = [r for r in inputs.get("complaints") or []
            if r.get("complaint_type") == "Noise - Residential" and a.get("bbl") and r.get("bbl") == a["bbl"]]
    n = len(rows)
    units = _f((pl or {}).get("unitsres"), 0) or 0
    if units <= 0:
        units = 1.0
        ev.append("residential unit count unknown; treated as one unit")
    baseline = C.BOROUGH_BASELINE_PER_UNIT_YEAR.get(a.get("borough"), C.CITY_BASELINE_PER_UNIT_YEAR)
    raw_rate = n / (units * years)
    rate = (n + C.BUILDING_SHRINK_K_UNIT_YEARS * baseline) / (units * years + C.BUILDING_SHRINK_K_UNIT_YEARS)
    level = C.BUILDING_BASELINE_DB + C.BUILDING_DB_PER_DOUBLING_OF_RATE * math.log2(rate / baseline)
    level = max(C.BUILDING_MIN_DB, min(C.BUILDING_MAX_DB, level))
    ev.append(f"{n} residential noise complaints to 311 at this building in {inputs['lookback_months']} months, "
              f"{int(units)} units: {raw_rate:.2f} per unit-year vs {baseline:.2f} for {a.get('borough')} "
              f"({rate / baseline:.1f}x after shrinkage)" + _top_descriptors(rows))
    # construction era and type
    yb = int(_f((pl or {}).get("yearbuilt"), 0) or 0)
    bc = str((pl or {}).get("bldgclass") or "")
    floors = int(_f((pl or {}).get("numfloors"), 0) or 0)
    era = 0.0
    walkup = bc[:1] in ("A", "B", "C")
    if 0 < yb < 1940 and walkup:
        era = C.PREWAR_DB
        ev.append(f"built {yb}: pre-war walk-up, wood joists and plaster carry footsteps")
    elif 0 < yb < 1940:
        era = C.PREWAR_ELEVATOR_DB
        ev.append(f"built {yb}: pre-war elevator building, masonry and plaster")
    elif 1940 <= yb < 2000:
        era = C.MIDCENTURY_DB
        ev.append(f"built {yb}")
    elif yb >= 2000:
        ev.append(f"built {yb}: post-2000, likely concrete slab")
    if walkup:
        era += C.WALKUP_DB
        ev.append(f"class {bc}: walk-up, stairs pass every door")
    elif bc[:1] == "D":
        ev.append(f"class {bc}: elevator building")
    # per-window timing: empirical if enough complaints, else the citywide prior
    offsets = dict(C.BUILDING_WINDOW_PRIOR_OFFSET)
    if n >= C.BUILDING_MIN_COMPLAINTS_FOR_EMPIRICAL_HOURS:
        per_year, _ = _window_counts(rows, years)
        total = sum(per_year.values()) or 1
        for w in WINDOWS:
            share_per_hour = (per_year[w] / total) / C.WINDOW_HOURS[w]
            o = 10 * math.log10(max(share_per_hour, 1e-6) / (1 / 24))
            offsets[w] = max(-C.BUILDING_WINDOW_OFFSET_CLAMP, min(C.BUILDING_WINDOW_OFFSET_CLAMP, o))
        ev.append("complaint hours at this building: " + ", ".join(
            f"{w} {int(round(per_year[w] * years))}" for w in WINDOWS))
    # position inside the building
    pos = 0.0
    if unit.floor:
        if floors and unit.floor >= floors:
            pos += C.TOP_FLOOR_DB
            ev.append(f"floor {unit.floor} of {floors}: top floor, nobody above")
        if unit.floor == 1:
            pos += C.FIRST_FLOOR_DB
            ev.append("first floor: lobby, buzzer and front door")
        if unit.floor == 2 and _has_commercial(pl):
            pos += C.ABOVE_COMMERCIAL_DB
            ev.append("second floor above a commercial space")
    out = {w: level + era + offsets[w] + pos for w in WINDOWS}
    return {"name": "building", "label": "Building", "levels": out, "raw_level": level + era,
            "evidence": ev, "position_db": pos, "temporary": False,
            "complaints": n, "units": int(units), "rate_vs_borough": round(rate / baseline, 2)}


# ---------------------------------------------------------------- 4. sirens
def sirens(inputs, unit):
    """Hospitals, firehouses and police stations as point sources whose vehicles leave along the street. [M11]"""
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    ev = []
    facs = []
    for r in inputs.get("facilities") or []:
        kind = r.get("kind")
        la, ln = _f(r.get("latitude")), _f(r.get("longitude"))
        if kind not in C.SIRENS_BASE_DB or la is None or ln is None:
            continue
        d = haversine_m(lat, lng, la, ln)
        if d > C.RADIUS_SIRENS_M:
            continue
        level = C.SIRENS_BASE_DB[kind] - C.SIRENS_DB_PER_DOUBLING * math.log2(max(d, C.SIRENS_REF_DISTANCE_M) / C.SIRENS_REF_DISTANCE_M)
        facs.append((d, level, kind, r.get("name"), r.get("address")))
    facs.sort(key=lambda f: f[0])
    base = energy_sum([f[1] for f in facs])
    if base is None:
        base = C.SIRENS_NONE_DB
        ev.append(f"no hospital, firehouse or police station within {C.RADIUS_SIRENS_M} m")
    else:
        base = min(base, C.SIRENS_SUM_CAP_DB)
        kinds = {}
        for f in facs:
            kinds[f[2]] = kinds.get(f[2], 0) + 1
        ev.append(f"{len(facs)} emergency facilities within {C.RADIUS_SIRENS_M} m: "
                  + ", ".join(f"{kinds[k]} {C.SIRENS_KIND_LABEL[k]}{'s' if kinds[k] != 1 else ''}"
                              for k in C.SIRENS_BASE_DB if k in kinds))
        for d, _, kind, name, address in facs[:3]:
            ev.append(f"{name} ({C.SIRENS_KIND_LABEL[kind]}), " + (f"{address}, " if address else "") + f"{int(d)} m")
    att = floor_attenuation(unit) + C.POSITION_DB.get(unit.position, C.POSITION_DB["unknown"])
    out = {w: base + C.SIRENS_WINDOW_OFFSET[w] + att for w in WINDOWS}
    return {"name": "sirens", "label": "Sirens", "levels": out, "raw_level": base,
            "evidence": ev, "position_db": att, "temporary": False}


# ---------------------------------------------------------------- 5. construction (temporary)
def construction(inputs, unit):
    lat, lng = inputs["address"]["lat"], inputs["address"]["lng"]
    years = inputs["lookback_months"] / 12
    ev = []
    rows = [r for r in inputs.get("complaints") or []
            if r.get("complaint_type") == "Noise"
            and any(k in (r.get("descriptor") or "").lower() for k in C.CONSTRUCTION_DESCRIPTOR_KEYS)
            and _within(r, lat, lng, C.RADIUS_BLOCK_M)]
    n311 = len(rows)
    today = dt.date.fromisoformat(inputs.get("as_of") or dt.date.today().isoformat())
    active = []
    for p in inputs.get("permits") or []:
        if p.get("work_type") not in C.CONSTRUCTION_LOUD_WORK_TYPES:
            continue
        exp = (p.get("expired_date") or "")[:10]
        if exp and dt.date.fromisoformat(exp) < today:
            continue
        active.append(p)
    if n311:
        ev.append(f"{n311} construction noise complaints within {C.RADIUS_BLOCK_M} m in {inputs['lookback_months']} months" + _top_descriptors(rows))
    if active:
        kinds = {}
        for p in active:
            kinds[p["work_type"]] = kinds.get(p["work_type"], 0) + 1
        ev.append(f"{len(active)} unexpired loud-work permits on this tax block: "
                  + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
        for p in active[:2]:
            ev.append(" ".join(f"{p.get('house_no', '')} {p.get('street_name', '')}".split()).title() + f": {p.get('work_type')} to {(p.get('expired_date') or '')[:10]}")
    if not n311 and not active:
        base = C.CONSTRUCTION_NONE_DB
        ev.append("no construction complaints or loud-work permits nearby")
    else:
        bump = (C.CONSTRUCTION_311_DB_PER_DOUBLING * math.log2(1 + n311 / years)
                + C.CONSTRUCTION_PERMIT_DB_PER_DOUBLING * math.log2(1 + len(active)))
        base = C.CONSTRUCTION_BASE_DB + min(C.CONSTRUCTION_MAX_BUMP_DB, bump)
    att = floor_attenuation(unit) + C.POSITION_DB.get(unit.position, C.POSITION_DB["unknown"])
    out = {w: base + C.CONSTRUCTION_WINDOW_OFFSET[w] + att for w in WINDOWS}
    return {"name": "construction", "label": "Construction", "levels": out, "raw_level": base,
            "evidence": ev, "position_db": att, "temporary": True}


# ---------------------------------------------------------------- 6. combine
def window_weights(profile):
    w = dict(C.DEFAULT_WINDOW_WEIGHTS)
    if profile:
        w.update(C.SLEEP_WINDOW_WEIGHTS.get(profile.sleep, {}))
        if profile.wfh:
            w["day"] = C.WFH_DAY_WEIGHT
    return w


def combine(ingredients, profile):
    bothers = {C.BOTHER_TO_INGREDIENT[b] for b in (profile.bothers if profile else []) if b in C.BOTHER_TO_INGREDIENT}
    per_window = {}
    for w in WINDOWS:
        per_window[w] = energy_sum([
            ing["levels"][w] + (C.BOTHER_DB if ing["name"] in bothers else 0.0) for ing in ingredients
        ])
    weights = window_weights(profile)
    overall = sum(per_window[w] * weights[w] for w in WINDOWS) / sum(weights.values())
    return overall, per_window, weights, bothers


def street_only(inputs):
    """A HowLoud-style number: roads, rail and nearby businesses, one value, no floor, no building, no hours, no sirens."""
    ground = Unit(floor=None, position="front")
    s = street(inputs, ground)
    n = nightlife(inputs, ground, None)
    level = energy_sum([s["raw_level"], n["raw_level"] - 4.0])   # businesses by day, HowLoud's "local"
    return to_score(level)


def score(inputs, unit=None, profile=None):
    unit = unit or Unit()
    pl = inputs.get("pluto") or {}
    ings = [street(inputs, unit), nightlife(inputs, unit, pl), building(inputs, unit, pl), sirens(inputs, unit),
            construction(inputs, unit)]
    overall, per_window, weights, bothers = combine(ings, profile)
    for ing in ings:
        ing["scores"] = {w: to_score(ing["levels"][w]) for w in WINDOWS}
        ing["levels"] = {w: round(v, 1) for w, v in ing["levels"].items()}
        ing["raw_level"] = round(ing["raw_level"], 1)
        ing["position_db"] = round(ing["position_db"], 1)
        ing["weighted_up"] = ing["name"] in bothers
    floors = int(_f(pl.get("numfloors"), 0) or 0)
    return {
        "score": to_score(overall),
        "scale": "0 to 100, higher is quieter",
        "street_only_score": street_only(inputs),
        "by_time": {w: to_score(per_window[w]) for w in WINDOWS},
        "address": inputs["address"],
        "unit": {"floor": unit.floor, "position": unit.position, "top_floor": bool(unit.floor and floors and unit.floor >= floors),
                 "building_floors": floors or None, "ground_floor_commercial": _has_commercial(pl)},
        "building_facts": {k: pl.get(k) for k in ("address", "yearbuilt", "numfloors", "bldgclass", "unitsres", "unitstotal")} if pl else None,
        "ingredients": ings,
        "profile": {"sleep": profile.sleep, "wfh": profile.wfh, "bothers": profile.bothers} if profile else None,
        "window_weights": weights,
        "internal_level": round(overall, 1),
        "as_of": inputs.get("as_of"),
        "lookback_months": inputs.get("lookback_months"),
        "sources": inputs.get("sources", []),
        "caveats": [
            "311 counts measure who complains, not decibels; the count is shown so you can judge it.",
            "Street loudness is modelled from road class, lanes and speed, not measured.",
            "Elevated subway proximity uses the nearest station's structure as a proxy for the track.",
            "Construction is temporary; permits expire and the bar may close.",
        ],
    }
