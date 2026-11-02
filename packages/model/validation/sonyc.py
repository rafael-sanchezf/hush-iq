"""SONYC-UST-V2 validation harness for Hush IQ.

Question: across the Manhattan blocks where the SONYC network put microphones, does Hush IQ's level for a
source rank the blocks the way volunteers' sound tags for that kind of sound do?

Run from packages/model (stdlib plus httpx, which the model already needs):

    NOISE_SCORE_CACHE=<dir> python -m validation.sonyc               # pull, score, report
    python -m validation.sonyc --reuse-today                         # no network: reuse today's levels from the
                                                                     # last sonyc_results.json, re-apply upgrades

Network, first run only: Zenodo for annotations.csv (14 MB, md5-checked; the audio archives are never fetched)
and the public city data through noise_score.sources. Writes sonyc_results.json and SONYC.md next to this file.

Re-runnable: every run re-checks which upgrade modules and built artifacts exist (noise_score.upgrades.<source>
plus data/upgrades/<source>.json.gz) and reports "upgraded" for each source that has both, "today" always.
"""
import argparse
import csv
import datetime as dt
import hashlib
import importlib
import json
import math
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_ROOT = HERE.parent
if str(MODEL_ROOT) not in sys.path:
    sys.path.insert(0, str(MODEL_ROOT))

from noise_score import baseline, cache, config, geo, model, recal, sources  # noqa: E402

try:
    from noise_score import upgrades  # noqa: E402
except ImportError:  # the upgrade package is optional for this harness
    upgrades = None

# ---------------------------------------------------------------- the dataset
ZENODO_RECORD = "3966543"
ZENODO_FILE_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/{{name}}/content"
# Only these three files are ever downloaded. md5 from the Zenodo record, version 2.3.0.
FILES = {
    "annotations.csv": "70b507b15bb4cfcce4870925302f276b",
    "dcase-ust-taxonomy.yaml": "6c1cca1c4c383a6ebb0cb71cb74fe3a9",
    "README.md": "bdfa3a4c0d90053f622b52afa0fc86f7",
}
MANHATTAN = 1                     # the dataset's borough code
SLOTS = tuple(model.WINDOWS)      # night 22-5, early 5-8, day 8-22
# Hush IQ source -> SONYC columns. A clip has the source's tag when any of its columns is present.
TAGS = {
    "street": ("1_engine_presence",),
    "construction": ("2_machinery-impact_presence", "4_powered-saw_presence"),
    "nightlife": ("6_music_presence", "7_human-voice_presence"),
    "sirens": ("5-3_siren_presence",),          # fine tag under alert-signal, not the coarse class
}
TESTED = tuple(TAGS)
SKIPPED = {"building": "neighbors have no outdoor sound tag, so there is no proxy to test against"}
WASHINGTON_SQUARE = (40.7308, -73.9973)       # centre of the park at the heart of NYU's campus
BANDS_KM = (0.5, 1.0, 2.0, 99.0)
LOT_SELECT = ("bbl,block,lot,address,latitude,longitude,borough,yearbuilt,yearalter1,yearalter2,numfloors,"
              "bldgclass,unitsres,unitstotal,landuse,lotfront,bldgdepth,zonedist1")


# ---------------------------------------------------------------- 0. get the files
def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_data(data_dir, download=True):
    """The three annotation and metadata files, md5-verified. Never touches the audio archives."""
    import httpx
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, md5 in FILES.items():
        p = data_dir / name
        if p.exists() and _md5(p) == md5:
            continue
        if not download:
            raise SystemExit(f"{p} is missing or does not match Zenodo's md5; drop --no-download to fetch it")
        print(f"downloading {name} from Zenodo record {ZENODO_RECORD}", file=sys.stderr)
        with httpx.stream("GET", ZENODO_FILE_URL.format(name=name), follow_redirects=True, timeout=120,
                          headers={"User-Agent": "hush-iq/0.1 (validation harness)"}) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        if _md5(p) != md5:
            raise SystemExit(f"{name}: md5 differs from the one recorded for Zenodo version 2.3.0")
    return data_dir


# ---------------------------------------------------------------- 1. clips, labels, tag shares
def load_clips(path):
    """Manhattan clips only. One dict per 10-second clip with the verified row (annotator 0) and the volunteers'
    rows (annotator id above 0). SONYC team rows (below 0) label one class group at a time and are not needed."""
    cols = sorted({c for cs in TAGS.values() for c in cs})
    clips, rows = {}, 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if int(r["borough"]) != MANHATTAN:
                continue
            rows += 1
            aid = int(r["annotator_id"])
            if aid < 0:
                continue
            c = clips.get(r["audio_filename"])
            if c is None:
                c = clips[r["audio_filename"]] = {
                    "loc": (int(r["block"]), float(r["latitude"]), float(r["longitude"])),
                    "sensor": int(r["sensor_id"]), "hour": int(r["hour"]), "year": int(r["year"]),
                    "split": r["split"], "gt": None, "vol": []}
            vals = {k: int(r[k]) for k in cols}
            if aid == 0:
                c["gt"] = vals
            else:
                c["vol"].append(vals)
    return clips, rows


def present(clip, col, rule):
    """Is this column's tag present in this clip. Verified label when the clip has one; else the volunteers:
    'majority' = more than half of the volunteers (2 of 3), 'any' = at least one."""
    gt = clip["gt"]
    if gt is not None and gt[col] >= 0:
        return gt[col] == 1
    v = [r[col] for r in clip["vol"] if r[col] >= 0]
    if not v:
        return False
    hits = sum(1 for x in v if x == 1)
    return hits >= 1 if rule == "any" else 2 * hits > len(v)


def source_present(clip, source, rule):
    return any(present(clip, col, rule) for col in TAGS[source])


def aggregate(clips, rules=("majority", "any")):
    """Per sensor location (block plus block-level coordinates) and slot: clip count and tagged clips per source."""
    locs = {}
    for c in clips.values():
        L = locs.get(c["loc"])
        if L is None:
            L = locs[c["loc"]] = {
                "block": c["loc"][0], "lat": c["loc"][1], "lng": c["loc"][2], "sensors": set(), "verified": 0,
                "clips": {s: 0 for s in SLOTS},
                "tagged": {r: {src: {s: 0 for s in SLOTS} for src in TAGS} for r in rules}}
        slot = model.window_of(c["hour"])
        L["clips"][slot] += 1
        L["sensors"].add(c["sensor"])
        L["verified"] += c["gt"] is not None
        for rule in rules:
            for src in TAGS:
                if source_present(c, src, rule):
                    L["tagged"][rule][src][slot] += 1
    out = []
    for key in sorted(locs):
        L = locs[key]
        L["id"] = f"{L['block']}:{L['lat']:.5f},{L['lng']:.5f}"
        L["sensors"] = sorted(L["sensors"])
        L["shares"] = {r: {src: {s: (L["tagged"][r][src][s] / L["clips"][s] if L["clips"][s] else None)
                                 for s in SLOTS} for src in TAGS} for r in rules}
        del L["tagged"]
        L["clips_total"] = sum(L["clips"].values())
        out.append(L)
    return out


def overview(clips, annotation_rows, locs, min_clips):
    d_wsp = [geo.haversine_m(L["lat"], L["lng"], *WASHINGTON_SQUARE) / 1000 for L in locs]
    bands, lo = [], 0.0
    for hi in BANDS_KM:
        idx = [i for i, d in enumerate(d_wsp) if lo <= d < hi]
        bands.append({"from_km": lo, "to_km": hi if hi < 99 else None, "locations": len(idx),
                      "clips": sum(locs[i]["clips_total"] for i in idx)})
        lo = hi
    total = sum(L["clips_total"] for L in locs)
    years = sorted({c["year"] for c in clips.values()})
    return {
        "annotation_rows": annotation_rows, "clips": len(clips), "sensors": len({c["sensor"] for c in clips.values()}),
        "tax_blocks": len({L["block"] for L in locs}), "locations": len(locs),
        "verified_clips": sum(L["verified"] for L in locs), "years": [years[0], years[-1]],
        "clips_by_slot": {s: sum(L["clips"][s] for L in locs) for s in SLOTS},
        "locations_with_min_clips": {s: sum(1 for L in locs if L["clips"][s] >= min_clips) for s in SLOTS},
        "distance_from_washington_square_km": bands,
        "share_of_clips_within_1km": round(sum(b["clips"] for b in bands[:2]) / total, 3),
        "locations_beyond_2km": [{"id": L["id"], "lat": L["lat"], "km": round(d, 1), "clips": L["clips_total"]}
                                 for L, d in zip(locs, d_wsp) if d >= 2.0],
    }


# ---------------------------------------------------------------- 2. Hush IQ's levels at each location
def _network_files():
    try:
        return sum(1 for _ in os.scandir(cache.CACHE_DIR))
    except FileNotFoundError:
        return 0


def pull_location(L, today, fresh=False):
    """The frozen model's facade-neutral level per source and slot at one sensor location, plus the building facts
    the upgrades receive. pull_at needs lat, lng, bbl (PLUTO row and the tax block for permits) and borough, so
    the lot is the PLUTO lot on the sensor's own tax block nearest to the coordinate."""
    lots = sources._get("pluto_block", sources.DATASETS["pluto"], {
        "$select": LOT_SELECT, "$where": f"borough='MN' AND block='{L['block']}'", "$limit": 2000}, fresh)
    best, best_d = None, None
    for lot in lots:
        try:
            d = geo.haversine_m(L["lat"], L["lng"], float(lot["latitude"]), float(lot["longitude"]))
        except (KeyError, TypeError, ValueError):
            continue
        if best is None or d < best_d:
            best, best_d = lot, d
    pl = None
    bbl = f"1{L['block']:05d}0000"
    if best is not None:
        bbl = baseline._bbl(best["bbl"])
        pl = {k: best.get(k) for k in ("address", "borough", "yearbuilt", "yearalter1", "yearalter2", "numfloors",
                                       "bldgclass", "unitsres", "unitstotal", "landuse", "lotfront", "bldgdepth",
                                       "zonedist1")}
    a = {"query": f"SONYC block {L['block']}", "label": f"SONYC block {L['block']}", "lat": L["lat"],
         "lng": L["lng"], "bbl": bbl, "bin": None, "borough": "Manhattan"}
    inputs = sources.pull_at(a, fresh=fresh, today=today, pluto_row=pl)
    lv = baseline.neutral_levels(inputs)
    rv = recal.levels(inputs)   # engine v2's starting point: the same pulls with the research numbers [V10]
    return {
        "bbl": bbl, "lot_distance_m": None if best_d is None else round(best_d, 1),
        "facts": baseline.building_facts(pl),
        "today": {n: {s: round(lv[n][s], 3) for s in SLOTS} for n in baseline.INGREDIENTS},
        "recal": {n: {s: round(rv[n][s], 3) for s in SLOTS} for n in baseline.INGREDIENTS},
        "pulled": {k: len(inputs.get(k) or []) for k in ("complaints", "liquor", "roads", "stations", "permits",
                                                         "facilities")},
    }


def score_locations(locs, today, reuse, prev, delay, fresh):
    for i, L in enumerate(locs, 1):
        L["pulled_ok"] = False
        if reuse:
            old = prev.get(L["id"])
            if old and old.get("today"):
                L.update({k: old[k] for k in ("bbl", "lot_distance_m", "facts", "today", "pulled", "recal") if k in old})
                L["pulled_ok"] = True
            else:
                L["error"] = "no stored levels for this location; run without --reuse-today"
            continue
        before = _network_files()
        try:
            L.update(pull_location(L, today, fresh))
            L["pulled_ok"] = True
        except Exception as e:  # one bad block must not lose the other pulls; they are cached
            L["error"] = f"{type(e).__name__}: {e}"[:300]
        print(f"[{i}/{len(locs)}] {L['id']} ok={L['pulled_ok']}", file=sys.stderr)
        if _network_files() != before:      # something came off the network: be polite
            time.sleep(delay)
    return locs


# ---------------------------------------------------------------- 3. upgrades, when artifacts exist
def upgrade_modules():
    """Per source: is there a module, is there a built artifact, and the module itself when both are there."""
    status, mods = {}, {}
    for src in TESTED + tuple(SKIPPED):
        mod, err = None, None
        try:
            mod = importlib.import_module(f"noise_score.upgrades.{src}")
        except ModuleNotFoundError as e:
            if e.name != f"noise_score.upgrades.{src}":
                err = repr(e)
        except Exception as e:  # a half-written module from another session
            err = repr(e)
        art = (upgrades.DATA / f"{src}.json.gz") if upgrades is not None else None
        exists = bool(art and art.exists())
        status[src] = {"module": mod is not None, "artifact": exists,
                       "artifact_bytes": art.stat().st_size if exists else None, "error": err,
                       "tested": src in TAGS, "available": src in TAGS and mod is not None and exists}
        if status[src]["available"]:
            mods[src] = mod
    return status, mods


def apply_upgrades(locs, status, mods):
    """Adds L['upgraded'][source] = {slot: level} for each available source, only when it worked at every
    scored location (so the today and upgraded correlations cover the same blocks)."""
    for src, mod in mods.items():
        got, errors, changed = {}, [], 0
        for L in locs:
            if not L["pulled_ok"]:
                continue
            today = {s: float(L.get("recal", L["today"])[src][s]) for s in SLOTS}   # v2 upgrades start here
            try:
                up = mod.upgrade(L["lat"], L["lng"], dict(today), L["facts"])
                lv = {s: float(up.levels[s]) for s in SLOTS}
            except Exception as e:
                errors.append(f"{L['id']}: {type(e).__name__}: {e}"[:200])
                continue
            got[L["id"]] = lv
            changed += any(abs(lv[s] - today[s]) > 1e-9 for s in SLOTS)
        status[src].update({"locations_upgraded": len(got), "locations_changed": changed, "errors": errors[:5]})
        if errors:
            status[src]["available"] = False
            continue
        for L in locs:
            if L["id"] in got:
                L.setdefault("upgraded", {})[src] = {s: round(v, 3) for s, v in got[L["id"]].items()}
    return status


# ---------------------------------------------------------------- 4. statistics (stdlib only)
def _avg_ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r, i = [0.0] * len(v), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    """Spearman rank correlation with average ranks for ties. None when undefined (n < 3 or a constant side)."""
    n = len(x)
    if n < 3:
        return None
    rx, ry = _avg_ranks([round(v, 6) for v in x]), _avg_ranks([round(v, 6) for v in y])
    mx, my = sum(rx) / n, sum(ry) / n
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def _pct(vals, q):
    s = sorted(vals)
    return s[int(round(q * (len(s) - 1)))]


def _interval(vals, alpha=0.10):
    if len(vals) < 50:
        return None
    return [round(_pct(vals, alpha / 2), 3), round(_pct(vals, 1 - alpha / 2), 3)]


def bootstrap(versions, y, clusters, n_boot, rng):
    """Percentile 90% intervals. 'loc' resamples sensor locations; 'block' resamples tax blocks whole, which is the
    honest one when nearby locations share the same streets. With two versions, the interval of upgraded minus
    today comes from the same resamples."""
    n = len(y)
    members = {}
    for i, c in enumerate(clusters):
        members.setdefault(c, []).append(i)
    cids = list(members)
    draws = {kind: {k: [] for k in versions} for kind in ("loc", "block")}
    delta = {"loc": [], "block": []}
    for _ in range(n_boot):
        for kind in ("loc", "block"):
            if kind == "loc":
                idx = [rng.randrange(n) for _ in range(n)]
            else:
                idx = [i for c in [cids[rng.randrange(len(cids))] for _ in cids] for i in members[c]]
            ys = [y[i] for i in idx]
            rs = {k: spearman([x[i] for i in idx], ys) for k, x in versions.items()}
            for k, r in rs.items():
                if r is not None:
                    draws[kind][k].append(r)
            if "upgraded" in rs and rs["upgraded"] is not None and rs["today"] is not None:
                delta[kind].append(rs["upgraded"] - rs["today"])
    return draws, delta


def analyse(locs, min_clips, n_boot, seed):
    out = []
    for src in TESTED:
        for slot in SLOTS:
            use = [L for L in locs if L["pulled_ok"] and L["clips"][slot] >= min_clips]
            y = [L["shares"]["majority"][src][slot] for L in use]
            versions = {"today": [L["today"][src][slot] for L in use]}
            if use and all("recal" in L for L in use):
                versions["recal"] = [L["recal"][src][slot] for L in use]
            if use and all(src in L.get("upgraded", {}) for L in use):
                versions["upgraded"] = [L["upgraded"][src][slot] for L in use]
            row = {"source": src, "slot": slot, "n": len(use), "tags": list(TAGS[src]),
                   "share_mean": round(sum(y) / len(y), 4) if y else None,
                   "share_min": round(min(y), 4) if y else None, "share_max": round(max(y), 4) if y else None,
                   "clips_in_slot": sum(L["clips"][slot] for L in use)}
            if len(use) >= 5:
                rng = random.Random(f"{seed}:{src}:{slot}")
                draws, delta = bootstrap(versions, y, [L["block"] for L in use], n_boot, rng)
                for ver, x in versions.items():
                    row[ver] = {"rho": None if spearman(x, y) is None else round(spearman(x, y), 3),
                                "ci90": _interval(draws["loc"][ver]), "ci90_block": _interval(draws["block"][ver]),
                                "distinct_levels": len({round(v, 6) for v in x})}
                    # sensitivity: the 'any volunteer' label rule
                    ya = [L["shares"]["any"][src][slot] for L in use]
                    ra = spearman(x, ya)
                    row[ver]["rho_any_volunteer"] = None if ra is None else round(ra, 3)
                if "upgraded" in versions:
                    t, u = row["today"]["rho"], row["upgraded"]["rho"]
                    row["upgraded"]["change_vs_today"] = {
                        "rho": None if t is None or u is None else round(u - t, 3),
                        "ci90": _interval(delta["loc"]), "ci90_block": _interval(delta["block"])}
            out.append(row)
    return out


# ---------------------------------------------------------------- 5. the readable report
def _cell(e):
    if not e or e.get("rho") is None:
        return "n/a"
    ci = e.get("ci90")
    return f"{e['rho']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else f"{e['rho']:+.2f}"


def _verdict(e):
    if not e or e.get("rho") is None or not e.get("ci90"):
        return "undefined"
    lo, hi = e["ci90"]
    return "positive" if lo > 0 else "negative" if hi < 0 else "straddles zero"


def _far_text(far):
    """Name the locations beyond 2 km by latitude band (Manhattan runs north to south)."""
    bands = (("Lower Manhattan", lambda y: y < 40.715), ("Midtown", lambda y: 40.74 <= y < 40.765),
             ("the Upper East Side", lambda y: y >= 40.765))
    counts = {name: sum(1 for f in far if test(f["lat"])) for name, test in bands}
    counts["elsewhere"] = len(far) - sum(counts.values())
    return f"{len(far)} locations: " + ", ".join(f"{name} {k}" for name, k in counts.items() if k)


def write_md(doc, path):
    ov, st, rows = doc["overview"], doc["upgrades"], doc["results"]
    bands = ov["distance_from_washington_square_km"]
    far = ov["locations_beyond_2km"]
    ncomp = [r["n"] for r in rows]
    nmin, nmax = (min(ncomp), max(ncomp)) if ncomp else (0, 0)
    ups = [s for s in TESTED if st[s]["available"]]
    pending = [s for s in TESTED if not st[s]["available"]]
    verdicts = [_verdict(r["today"]) for r in rows if "today" in r]
    pos, neg = verdicts.count("positive"), verdicts.count("negative")
    cells = len(verdicts)
    best = max((r for r in rows if r.get("today", {}).get("rho") is not None), key=lambda r: r["today"]["rho"],
               default=None)
    worst = min((r for r in rows if r.get("today", {}).get("rho") is not None), key=lambda r: r["today"]["rho"],
                default=None)
    L = []
    a = L.append
    a("# SONYC validation")
    a("")
    a(f"Does Hush IQ rank real Manhattan sensor blocks the way volunteers' sound tags do? Run {doc['run_date']}, "
      f"city data as of {doc['as_of']}. Harness: `validation/sonyc.py`. Numbers: `sonyc_results.json`.")
    a("")
    a("## Data")
    a(f"- SONYC-UST-V2 (version 2.3, Zenodo {ZENODO_RECORD}, CC BY 4.0, arXiv 2009.05188): 10-second street-level clips, "
      "tagged by three volunteers each, 1,380 verified by the SONYC team. Only `annotations.csv`, the taxonomy "
      "YAML and the README were downloaded (md5-checked); no audio.")
    a(f"- Manhattan (borough code 1): {ov['clips']:,} clips, {ov['annotation_rows']:,} annotation rows, "
      f"{ov['sensors']} sensors on {ov['tax_blocks']} tax blocks, {ov['locations']} distinct block-level "
      f"locations, recorded {ov['years'][0]} to {ov['years'][1]}. {ov['verified_clips']:,} clips carry a verified label.")
    a(f"- Cluster, by distance from Washington Square Park: " + "; ".join(
        f"{b['locations']} locations ({b['clips']:,} clips) " + (f"under {b['to_km']:g} km" if b['from_km'] == 0
                                                                 else f"{b['from_km']:g} to {b['to_km']:g} km" if b['to_km']
                                                                 else f"beyond {b['from_km']:g} km") for b in bands)
      + f". {100 * ov['share_of_clips_within_1km']:.0f}% of clips sit within 1 km, the Greenwich Village cluster the "
        f"paper describes; the rest is {_far_text(far)}.")
    a(f"- {doc['scored_locations']} of {ov['locations']} locations have {doc['min_clips']} or more clips in some slot; "
      f"the floor is applied per slot, so n is {nmin} to {nmax} locations per cell "
      f"(night {ov['locations_with_min_clips']['night']}, early {ov['locations_with_min_clips']['early']}, "
      f"day {ov['locations_with_min_clips']['day']}).")
    a("")
    a("## Mapping")
    a("| Hush IQ source | SONYC tag | Note |")
    a("|---|---|---|")
    a("| street | engine (coarse class 1) | all engine sizes |")
    a("| construction | machinery-impact (2) or powered-saw (4) | non-machinery-impact left out |")
    a("| nightlife | music (6) or human-voice (7) | talking and crowds count, so it is also street life |")
    a("| sirens | siren (fine tag 5-3 under alert-signal) | horns, alarms and beepers excluded |")
    a(f"| building | none | {SKIPPED['building']}; skipped |")
    a("")
    a("## Method")
    a("- Label: the verified label when the clip has one, else the volunteers' majority (2 of 3; every Manhattan clip "
      "has exactly 3). Sensitivity with 'any volunteer' is in the JSON (`rho_any_volunteer`).")
    a("- Tag share: tagged clips over all clips at a location, per slot (night 22 to 5, early 5 to 8, day 8 to 22, "
      "by the clip's hour). Locations with fewer than the floor in a slot drop out of that slot.")
    a("- Hush IQ level: `sources.pull_at` at the sensor coordinate, with the PLUTO lot on the sensor's own tax block "
      "nearest to it (median gap "
      f"{doc['lot_distance_median_m']} m), scored by the frozen model at a facade-neutral unit (`baseline.neutral_levels`).")
    a("- Research numbers: the same pulls scored with the recalibrated constants of 2026-10-29 (`noise_score.recal`, "
      "engine v2 rule V10). Upgraded: `noise_score.upgrades.<source>.upgrade(lat, lng, level, facts)` on top of the "
      "research numbers, for each source that has a module and a built artifact. " + (f"Used now: {', '.join(s + (' (levels unchanged from today)' if not st[s].get('locations_changed') else '') for s in ups)}." if ups else f"Modules found: {', '.join(m for m in TESTED if st[m]['module']) or 'none'}; built artifacts: "
                        f"{', '.join(m for m in TESTED if st[m]['artifact']) or 'none'}. Upgraded cells stay empty until both exist."))
    a(f"- Statistic: Spearman rank correlation across locations, 90% percentile interval from {doc['bootstrap']} "
      "resamples of locations (resampling whole tax blocks is in the JSON as `ci90_block`).")
    a("")
    a("## Results (Spearman rho across sensor locations, positive means Hush IQ's louder blocks have more of the sound)")
    a("| Source | Slot | n | Mean share | Today rho [90% CI] | Research numbers rho | Upgraded rho [90% CI] |")
    a("|---|---|---|---|---|---|---|")
    for r in rows:
        up = _cell(r.get("upgraded")) if "upgraded" in r else ("no artifact" if r["source"] in pending else "n/a")
        if "upgraded" in r and r["upgraded"].get("change_vs_today", {}).get("rho") is not None:
            up += f", change {r['upgraded']['change_vs_today']['rho']:+.2f}"
        mean = "n/a" if r["share_mean"] is None else f"{100 * r['share_mean']:.0f}%"
        rc = "n/a" if not r.get("recal") or r["recal"].get("rho") is None else f"{r['recal']['rho']:+.2f}"
        a(f"| {r['source']} | {r['slot']} | {r['n']} | {mean} | {_cell(r.get('today'))} | {rc} | {up} |")
    a("")
    a(f"Read: of {cells} cells, {pos} have an interval entirely above zero, {neg} entirely below, "
      f"{cells - pos - neg} straddle zero." + (f" Strongest {best['source']} {best['slot']} ({_cell(best['today'])}), "
                                               f"weakest {worst['source']} {worst['slot']} ({_cell(worst['today'])})."
                                               if best else ""))
    chance = 0.05 * cells
    a(f"With {cells} cells and 90% intervals, chance alone puts about {chance:.1f} above zero. The cells are not "
      "independent: they reuse the same locations, and the frozen sirens ranking is the same in every slot.")
    a("")
    a("## Limits, worst first")
    a(f"1. Tiny, clustered sample: {ov['locations']} locations, {ov['tax_blocks']} blocks, mostly one neighborhood. "
      "No Harlem, Upper West Side, Chelsea or Hudson-side blocks. Intervals are wide; neighbors share streets, and "
      "resampling whole tax blocks (`ci90_block`) gives about the same width.")
    a("2. Clips were not drawn at random: SONYC picked audio near known examples of the target classes, and capped "
      "human voice at one clip per hour per sensor. A share measures how much of the picked audio has the tag, not "
      "how often the sound happens on that block.")
    a("3. Tag presence is not loudness. One horn and one jackhammer count once each; near and far count the same.")
    a("4. Years do not match: audio is 2016 to 2019, Hush IQ's 311, permit and license pulls cover the last 24 months. "
      "Roads and facilities barely change; bars, permits and complaints do.")
    a(f"5. Position: SONYC calls its coordinates block-level, but they land on a tax lot centroid (median "
      f"{doc['lot_distance_median_m']} m); the facade, height and street a sensor faces are unknown. Hush IQ is "
      "scored at a facade-neutral unit with 60 to 150 m radii, so a sensor around the corner can see a different street.")
    a("6. Mapping is coarse: engine includes buses and idling, music and voice include daytime street life, a "
      "siren tag is any emergency vehicle passing, not only those from nearby facilities.")
    a(f"7. Label noise: majority of three volunteers, verified for only {ov['verified_clips']:,} of {ov['clips']:,} clips, "
      f"so the two rules mix. Switching to 'any volunteer' moves rho by up to {doc['label_rule_max_shift']['shift']:.2f} "
      f"({doc['label_rule_max_shift']['cell']}).")
    a("8. Neighbors (building) cannot be tested at all with outdoor audio.")
    a("9. Upgrades: " + (f"tested for {', '.join(ups)}; not yet for {', '.join(pending) or 'none'}." if ups else
                          f"none built yet ({', '.join(pending)}); re-run when artifacts exist."))
    a("")
    a("## Re-run")
    a("`cd packages/model && NOISE_SCORE_CACHE=<cache dir> python -m validation.sonyc` (add `--reuse-today` to "
      "skip the city-data pulls and only re-apply upgrades).")
    text = "\n".join(L) + "\n"
    assert "\u2014" not in text and "\u2013" not in text
    if len(L) >= 80:
        print(f"warning: SONYC.md is {len(L)} lines, the brief says under 80", file=sys.stderr)
    path.write_text(text)
    return len(L)


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=os.environ.get("SONYC_DATA_DIR", str(HERE / "data")))
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--min-clips", type=int, default=20, help="clips a location needs in a slot (default 20)")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261028)
    ap.add_argument("--reuse-today", action="store_true", help="no network: reuse today's levels from sonyc_results.json")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds to wait after each location that hit the network")
    ap.add_argument("--fresh", action="store_true", help="bypass the pull cache")
    ap.add_argument("--limit", type=int, default=0, help="debug: only the first N locations that pass the clip floor")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    json_path, md_path = out_dir / "sonyc_results.json", out_dir / "SONYC.md"
    prev, as_of = {}, dt.date.today()
    if args.reuse_today:
        old = json.loads(json_path.read_text())
        prev = {L["id"]: L for L in old["locations"]}
        as_of = dt.date.fromisoformat(old["as_of"])

    data_dir = ensure_data(Path(args.data_dir), download=not args.no_download)
    clips, annotation_rows = load_clips(data_dir / "annotations.csv")
    locs = aggregate(clips)
    ov = overview(clips, annotation_rows, locs, args.min_clips)
    todo = [L for L in locs if any(L["clips"][s] >= args.min_clips for s in SLOTS)]
    if args.limit:
        todo = todo[: args.limit]
    scored = {L["id"] for L in todo}
    for L in locs:
        if L["id"] not in scored:
            L["pulled_ok"] = False
    score_locations(todo, as_of, args.reuse_today, prev, args.delay, args.fresh)
    status, mods = upgrade_modules()
    apply_upgrades(todo, status, mods)
    results = analyse(locs, args.min_clips, args.boot, args.seed)

    shift = {"shift": 0.0, "cell": "n/a"}
    for r in results:
        t = r.get("today")
        if t and t.get("rho") is not None and t.get("rho_any_volunteer") is not None:
            d = abs(t["rho_any_volunteer"] - t["rho"])
            if d > shift["shift"]:
                shift = {"shift": round(d, 3), "cell": f"{r['source']} {r['slot']}: {t['rho']:+.2f} to {t['rho_any_volunteer']:+.2f}"}
    lot_d = sorted(L["lot_distance_m"] for L in todo if L.get("lot_distance_m") is not None)
    doc = {
        "dataset": {"name": "SONYC-UST-V2", "version": "2.3.0", "zenodo_record": ZENODO_RECORD,
                    "paper": "https://arxiv.org/abs/2009.05188", "license": "CC BY 4.0",
                    "files_used": list(FILES), "audio_downloaded": False},
        "run_date": dt.date.today().isoformat(), "as_of": as_of.isoformat(), "reused_today_levels": args.reuse_today,
        "label_rule": "verified label when the clip has one, else majority of the 3 volunteers (more than half)",
        "mapping": {k: list(v) for k, v in TAGS.items()}, "skipped": SKIPPED,
        "slots": {s: list(config.WINDOWS[s]) for s in SLOTS},
        "min_clips": args.min_clips, "bootstrap": args.boot, "seed": args.seed,
        "lot_distance_median_m": lot_d[len(lot_d) // 2] if lot_d else None,
        "scored_locations": len(todo), "label_rule_max_shift": shift,
        "overview": ov,
        "upgrades": status,
        "results": results,
        "locations": [{k: v for k, v in L.items()} for L in locs],
    }
    json_path.write_text(json.dumps(doc, indent=1))
    n_lines = write_md(doc, md_path)
    print(f"wrote {json_path} and {md_path} ({n_lines} lines)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
