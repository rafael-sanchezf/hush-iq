"""The Manhattan baseline [M12]: where one apartment's score sits among Manhattan apartments, for the same renter.

The 0 to 100 score is absolute (40 dB facade-equivalent is 100, 80 dB is 0, M1). On its own it cannot say
whether a 60 is good for Manhattan. The baseline answers that by scoring a sample of real Manhattan
apartments with the same model and ranking the renter's apartment among them.

How the sample is drawn (build):
  1. Every Manhattan tax lot in PLUTO with at least one residential unit and coordinates.
  2. Stratified by community district (101 to 112 plus the joint-interest codes), each district's share of the
     sample proportional to its share of Manhattan's residential units.
  3. Within a district, systematic sampling with probability proportional to units, lots in BBL order (which
     runs block by block), from a seeded random start. A building is picked about as often as its share of
     apartments, so each sample point stands for the same number of apartments. A building big enough to be
     hit twice carries weight 2.
  4. Each lot is pulled and scored with the same model at a facade-neutral unit (no floor, front), and the
     per-ingredient, per-window levels are stored with the building's floors and commercial flag.

How a rank is made (rank):
  Each sample is re-scored for the renter: the renter's floor (capped at that building's height) and side,
  the renter's sleep, work-from-home and bothers. That is the renter living at the same height and side in
  each sampled building. The share of samples louder than the renter's own level is "quieter than X%".
  No network: the stored levels are enough, which is why the iOS app can rank on the phone.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import random
import sys
from pathlib import Path

import httpx

from . import config as C, model, sources

DATA = Path(__file__).resolve().parent / "data" / "manhattan_baseline.json"
PLUTO_URL = sources.DATASETS["pluto"]
INGREDIENTS = ("street", "nightlife", "building", "sirens", "construction")
OUTDOOR = ("street", "nightlife", "sirens", "construction")


# ---------------------------------------------------------------- the decomposition the rank relies on
def neutral_levels(inputs):
    """Per-ingredient, per-window levels at a facade-neutral unit: no floor and front, so position adds 0 dB."""
    unit = model.Unit(floor=None, position="front")
    pl = inputs.get("pluto") or {}
    ings = [model.street(inputs, unit), model.nightlife(inputs, unit, pl), model.building(inputs, unit, pl),
            model.sirens(inputs, unit), model.construction(inputs, unit)]
    return {i["name"]: {w: i["levels"][w] for w in model.WINDOWS} for i in ings}


def building_facts(pl):
    floors = int(model._f((pl or {}).get("numfloors"), 0) or 0)
    return {"floors": floors or None, "commercial": bool(model._has_commercial(pl))}


def position_db(facts, unit):
    """dB added to each ingredient for this unit in a building with these facts. Mirrors model.py exactly
    (floor_attenuation, POSITION_DB, ground-floor commercial, top floor, first floor, above commercial)."""
    floors = facts.get("floors") or 0
    commercial = bool(facts.get("commercial"))
    f = unit.floor
    u = model.Unit(floor=f, position=unit.position)
    att = model.floor_attenuation(u) + C.POSITION_DB.get(u.position, C.POSITION_DB["unknown"])
    adj = {n: att for n in OUTDOOR}
    adj["building"] = 0.0
    if commercial and f and f <= 2:
        adj["nightlife"] += C.GROUND_FLOOR_COMMERCIAL_DB
    if f:
        if floors and f >= floors:
            adj["building"] += C.TOP_FLOOR_DB
        if f == 1:
            adj["building"] += C.FIRST_FLOOR_DB
        if f == 2 and commercial:
            adj["building"] += C.ABOVE_COMMERCIAL_DB
    return adj


def level_for(neutral, facts, unit, profile, cap_floor=True):
    """The overall level (model.combine) for this renter in this building."""
    floors = facts.get("floors")
    if cap_floor and unit.floor and floors:
        unit = model.Unit(floor=min(unit.floor, floors), position=unit.position)
    adj = position_db(facts, unit)
    ings = [{"name": n, "levels": {w: neutral[n][w] + adj[n] for w in model.WINDOWS}} for n in INGREDIENTS]
    overall, _, _, _ = model.combine(ings, profile)
    return overall


# ---------------------------------------------------------------- rank
_cache = None


def load(path=DATA):
    global _cache
    if _cache is None or path != DATA:
        doc = json.loads(Path(path).read_text())
        if path != DATA:
            return doc
        _cache = doc
    return _cache


def _weighted_quantile(pairs, q):
    """pairs: (value, weight) sorted by value. The smallest value whose cumulative weight reaches q."""
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total - 1e-9:
            return v
    return pairs[-1][0]


def rank(level, unit=None, profile=None, baseline=None):
    """Rank an overall level (the score's internal_level) among the Manhattan sample for this renter."""
    b = baseline or load()
    unit = unit or model.Unit()
    pairs = sorted((level_for(s["levels"], s, unit, profile), s.get("weight", 1)) for s in b["samples"])
    total = sum(w for _, w in pairs)
    louder = sum(w for l, w in pairs if l > level + 1e-6)
    ties = sum(w for l, w in pairs if abs(l - level) <= 1e-6)
    scores = sorted((model.to_score(l), w) for l, w in pairs)
    return {
        "quieter_than": round(100 * (louder + ties / 2) / total, 1),
        "median_score": _weighted_quantile(scores, 0.5),
        "p25_score": _weighted_quantile(scores, 0.25),
        "p75_score": _weighted_quantile(scores, 0.75),
        "verdict": verdict(100 * (louder + ties / 2) / total),
        "n": int(total),          # sample points; a building hit twice counts twice
        "buildings": len(b["samples"]),
        "apartments": b["universe"]["units"],
        "as_of": b["as_of"],
    }


# ---------------------------------------------------------------- the verdict and the time-of-day ranks
VERDICTS = ("Very loud", "Loud", "Typical", "Quiet", "Very quiet")


def verdict(quieter_than):
    """Five steps, one fifth of Manhattan each: under 20% quieter-than is Very loud, 80% and up Very quiet."""
    return VERDICTS[max(0, min(int(quieter_than // 20), 4))]


def physical_level(result, window):
    """The estimated level at the window for one time slot: the ingredients' levels after floor and side,
    with no answer bumps (those are preferences, not sound). Read from the score's own rounded levels."""
    return model.energy_sum([i["levels"][window] for i in result["ingredients"]])


def window_rank(result, window, unit=None, baseline=None):
    """Rank one time slot's physical level among the sample at the same floor (capped) and side."""
    b = baseline or load()
    unit = unit or model.Unit()
    mine = physical_level(result, window)
    pairs = []
    for s in b["samples"]:
        u = unit
        if unit.floor and s.get("floors"):
            u = model.Unit(floor=min(unit.floor, s["floors"]), position=unit.position)
        adj = position_db(s, u)
        pairs.append((model.energy_sum([s["levels"][n][window] + adj[n] for n in INGREDIENTS]), s.get("weight", 1)))
    pairs.sort()
    total = sum(w for _, w in pairs)
    louder = sum(w for l, w in pairs if l > mine + 1e-6)
    ties = sum(w for l, w in pairs if abs(l - mine) <= 1e-6)
    q = round(100 * (louder + ties / 2) / total, 1)
    return {"window": window, "level_db": round(mine, 1), "quieter_than": q, "verdict": verdict(q),
            "median_db": round(_weighted_quantile(pairs, 0.5), 1), "p25_db": round(_weighted_quantile(pairs, 0.25), 1),
            "p75_db": round(_weighted_quantile(pairs, 0.75), 1)}


# ---------------------------------------------------------------- build
def _lots(client):
    rows, offset = [], 0
    while True:
        r = client.get(PLUTO_URL, params={
            "$select": "bbl,cd,address,latitude,longitude,unitsres,unitstotal,numfloors,yearbuilt,yearalter1,yearalter2,bldgclass,landuse,lotfront,bldgdepth,zonedist1,borough",
            "$where": "borough='MN' AND unitsres > 0 AND latitude IS NOT NULL",
            "$order": "bbl", "$limit": 50000, "$offset": offset})
        r.raise_for_status()
        page = r.json()
        rows += page
        if len(page) < 50000:
            return rows
        offset += 50000


def draw(lots, n, seed):
    """Stratified PPS systematic sample. Returns [(lot, hits)]."""
    rng = random.Random(seed)
    strata = {}
    for lot in lots:
        strata.setdefault(lot["cd"], []).append(lot)
    units = {cd: sum(int(float(l["unitsres"])) for l in ls) for cd, ls in strata.items()}
    total = sum(units.values())
    # largest-remainder allocation
    raw = {cd: n * u / total for cd, u in units.items()}
    alloc = {cd: int(v) for cd, v in raw.items()}
    for cd in sorted(raw, key=lambda c: raw[c] - alloc[c], reverse=True)[: n - sum(alloc.values())]:
        alloc[cd] += 1
    picked = []
    for cd in sorted(strata):
        k = alloc[cd]
        if not k:
            continue
        ls = sorted(strata[cd], key=lambda l: l["bbl"])
        step = units[cd] / k
        start = rng.uniform(0, step)
        targets = [start + i * step for i in range(k)]
        hits = {}
        acc, ti = 0.0, 0
        for lot in ls:
            acc += int(float(lot["unitsres"]))
            while ti < k and targets[ti] < acc:
                hits[lot["bbl"]] = (lot, hits.get(lot["bbl"], (lot, 0))[1] + 1)
                ti += 1
        picked += list(hits.values())
    return picked


def _bbl(x):
    return str(int(float(x)))


def _score_lot(lot, hits, today):
    bbl = _bbl(lot["bbl"])
    a = {"query": lot["address"], "label": lot["address"], "lat": float(lot["latitude"]), "lng": float(lot["longitude"]),
         "bbl": bbl, "bin": None, "borough": "Manhattan"}
    pl = {k: lot.get(k) for k in ("address", "borough", "yearbuilt", "yearalter1", "yearalter2", "numfloors", "bldgclass",
                                  "unitsres", "unitstotal", "landuse", "lotfront", "bldgdepth", "zonedist1")}
    inputs = sources.pull_at(a, today=today, pluto_row=pl)
    lv = neutral_levels(inputs)
    facts = building_facts(pl)
    plain = model.score(inputs, model.Unit(), None)
    return {
        "bbl": bbl, "cd": lot["cd"], "address": lot["address"], "lat": a["lat"], "lng": a["lng"],
        "weight": hits, "units": int(float(lot["unitsres"])), "year_built": int(float(lot.get("yearbuilt") or 0)) or None,
        "floors": facts["floors"], "commercial": facts["commercial"],
        "levels": {n: {w: round(v, 3) for w, v in lv[n].items()} for n in INGREDIENTS},
        "plain_score": plain["score"],
    }


def config_sha():
    return hashlib.sha256((Path(__file__).resolve().parent / "config.py").read_bytes()).hexdigest()[:12]


def build(n=300, seed=20261022, workers=8, out=DATA):
    today = dt.date.today()
    with httpx.Client(headers={"User-Agent": C.USER_AGENT}, timeout=60) as c:
        lots = _lots(c)
    picked = draw(lots, n, seed)
    print(f"{len(lots)} residential lots, {sum(int(float(l['unitsres'])) for l in lots)} units; "
          f"{len(picked)} distinct lots drawn for {n} sample points", file=sys.stderr)
    samples, failed = [], []
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_score_lot, lot, hits, today): (lot, hits) for lot, hits in picked}
        for i, f in enumerate(cf.as_completed(futs), 1):
            lot, hits = futs[f]
            try:
                samples.append(f.result())
            except Exception as e:  # one bad lot never sinks the build; it is listed instead
                failed.append({"bbl": _bbl(lot["bbl"]), "address": lot["address"], "error": str(e)[:200]})
            if i % 25 == 0:
                print(f"  {i}/{len(picked)}", file=sys.stderr)
    samples.sort(key=lambda s: s["bbl"])
    doc = {
        "name": "Manhattan baseline",
        "decision": "M12",
        "as_of": today.isoformat(),
        "method": "Stratified by community district, probability proportional to residential units within each "
                  "district, systematic from a seeded start over lots in BBL order; each lot scored with the same "
                  "model at a facade-neutral unit (no floor, front). A rank re-applies the renter's floor (capped "
                  "at the building's height), side and answers to every sample.",
        "seed": seed,
        "sample_points": n,
        "config_sha": config_sha(),
        "universe": {"lots": len(lots), "units": sum(int(float(l["unitsres"])) for l in lots)},
        "failed": failed,
        "samples": samples,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=1))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="noise-score-baseline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=300)
    b.add_argument("--seed", type=int, default=20261022)
    b.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    doc = build(args.n, args.seed, args.workers)
    plain = sorted(s["plain_score"] for s in doc["samples"])
    print(f"{len(doc['samples'])} scored, {len(doc['failed'])} failed; plain score p25 {plain[len(plain)//4]}, "
          f"median {plain[len(plain)//2]}, p75 {plain[3*len(plain)//4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
