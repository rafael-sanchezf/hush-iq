"""Engine v2: each noise source ranked against a fixed Manhattan, the ranks averaged with the renter's weights.
(Hackathon work, Oct 28.)

Rules V1 to V10 in ENGINE_V2.md. Reads the frozen ingredients (model.py) and the frozen Manhattan sample
(baseline.py, manhattan_baseline.json) and changes neither.

Pipeline:
  1. each source -> its slot levels from the same pulls with the research numbers (recal.py), upgraded with
     what actually passes (upgrades/), after floor and side                         [V1, V9, V10]
  2. slot levels -> one number per source, weighted by the renter's hours            [V2]
  3. that number -> "quieter than X% of Manhattan", against every sample building
     at a typical apartment                                                          [V4]
  4. the five ranks -> a weighted average [V3], re-ranked against the sample's own averages [V5]
  5. caps: one terrible source cannot be outvoted                                    [V6]

Decibels stay inside each source: they build its number, which becomes a rank. Sources are never added in
decibels, and no decibel leaves this module [V8].
"""
import bisect
import functools
from dataclasses import dataclass, field

from . import baseline, model, recal
from . import config as C
from . import config_v2 as V
from . import upgrades
from .upgrades import apply as upgrades_apply

SOURCES = baseline.INGREDIENTS


def upgrades_ready():
    """[V9] The upgraded Manhattan sample, when it matches the upgrade modules on disk and upgrades are on."""
    return upgrades_apply.ready() if V.USE_UPGRADES else None
VERDICTS = baseline.VERDICTS
EPS = 1e-6


# What a renter reads where it differs from the frozen ingredient's label: nightlife covers restaurants, theatres and
# other busy spots, not only bars (Rafa, 2026-10-29). The API key stays `nightlife`.
LABEL_OVERRIDES = {"nightlife": "Local businesses"}


# ---------------------------------------------------------------- the renter's three taps
@dataclass
class Answers:
    sleep: tuple = V.DEFAULT_SLEEP     # (from hour, until hour), 0..23
    day_bothers: bool = True           # "does noise during the day bother you"
    ticks: list = field(default_factory=list)   # traffic | people | neighbors | sirens | construction


def _asleep(hour, start, end):
    if start == end:
        return False
    return (hour >= start or hour < end) if start > end else (start <= hour < end)


def slot_weights(answers):
    """[V2] Each hour weighs by what the renter is doing then; a slot's share is the sum of its hours."""
    awake = V.AWAKE_HOUR_WEIGHT if answers.day_bothers else V.AWAKE_HOUR_WEIGHT_NOT_BOTHERED
    w = {s: 0.0 for s in model.WINDOWS}
    for h in range(24):
        w[model.window_of(h)] += V.ASLEEP_HOUR_WEIGHT if _asleep(h, *answers.sleep) else awake
    total = sum(w.values())
    return {s: v / total for s, v in w.items()}


def uniform_slots():
    """[V11] Every hour of the day weighs the same: each slot's share is its hours over 24."""
    w = {s: 0.0 for s in model.WINDOWS}
    for h in range(24):
        w[model.window_of(h)] += 1.0
    return {s: v / 24 for s, v in w.items()}


def source_weights(answers):
    """[V3] Default weights, a ticked source counts TICKED_MULTIPLIER times, rescaled to 1."""
    ticked = {V.TICK_TO_SOURCE[t] for t in answers.ticks if t in V.TICK_TO_SOURCE}
    w = {n: V.SOURCE_WEIGHTS[n] * (V.TICKED_MULTIPLIER if n in ticked else 1.0) for n in SOURCES}
    total = sum(w.values())
    return {n: v / total for n, v in w.items()}, ticked


# ---------------------------------------------------------------- floor and side [V7]
def residential_floors(facts):
    floors = facts.get("floors")
    if not floors:
        return None, None
    low = 2 if facts.get("commercial") and floors >= 2 else 1
    return low, floors


def expected_floor(facts):
    """The middle residential floor, rounded up. None when the building's height is unknown."""
    low, top = residential_floors(facts)
    return None if low is None else int((low + top) / 2 + 0.5)


def typical_unit(facts):
    return model.Unit(floor=expected_floor(facts), position="unknown")


def resolve(unit, facts):
    """The unit the score uses: the listing's floor and side where known, else the building's typical apartment."""
    floor, floor_from = unit.floor, "listing"
    if floor is None:
        floor, floor_from = expected_floor(facts), "expected"
    elif facts.get("floors"):
        floor = min(floor, facts["floors"])
    side_from = "listing" if unit.position in ("front", "rear") else "unknown"
    return model.Unit(floor=floor, position=unit.position if side_from == "listing" else "unknown"), floor_from, side_from


def story_height(floors):
    """[V10] Metres per floor: Manhattan's median, banded by the building's height when it is known."""
    if not floors:
        return V.STORY_HEIGHT_M
    return next(h for top, h in V.STORY_HEIGHT_BY_FLOORS if top is None or floors <= top)


def position_db(facts, unit):
    """[V7, V10] What floor and side add to each source, by the research rules (v1's are baseline.position_db).
    Traffic, elevated rail and sirens barely fall below about the fifth floor; nearby venues and sites do."""
    floors = facts.get("floors") or 0
    commercial = bool(facts.get("commercial"))
    f, side = unit.floor, unit.position
    up_m = (f - 1) * story_height(floors) if f and f > 1 else 0.0
    line = max(V.LINE_MAX_DB, V.LINE_DB_PER_M * max(0.0, up_m - V.LINE_FLAT_M))
    point = max(V.POINT_MAX_DB, V.POINT_DB_PER_FLOOR * (f - 1)) if f and f > 1 else 0.0
    adj = {}
    for n in SOURCES:
        if n == "building":
            continue
        s = 0.0 if side == "front" else V.REAR_DB[n] if side == "rear" else V.UNKNOWN_SIDE_DB
        adj[n] = (line if n in V.LINE_SOURCES else point) + s
    adj["building"] = 0.0
    if commercial and f and f <= 2:
        adj["nightlife"] += C.GROUND_FLOOR_COMMERCIAL_DB
    if f:
        if floors and f >= floors:
            adj["building"] += V.TOP_FLOOR_DB
        if f == 1:
            adj["building"] += V.FIRST_FLOOR_DB
        if f == 2 and commercial:
            adj["building"] += V.ABOVE_COMMERCIAL_DB
    return adj


# ---------------------------------------------------------------- one number per source, then a rank
def source_levels(neutral, facts, unit, slots):
    """[V1, V2] Internal only: each source's slot levels after floor and side, averaged by the renter's hours."""
    adj = position_db(facts, unit)
    return {n: sum(slots[s] * (neutral[n][s] + adj[n]) for s in slots) for n in SOURCES}


class _Ranker:
    """Weighted "quieter than X%" against a fixed list of values. Ties count half."""

    def __init__(self, pairs):
        pairs = sorted(pairs)
        self.values = [v for v, _ in pairs]
        self.cum = [0.0]
        for _, w in pairs:
            self.cum.append(self.cum[-1] + w)
        self.total = self.cum[-1]

    def _split(self, value):
        lo = bisect.bisect_left(self.values, value - EPS)
        hi = bisect.bisect_right(self.values, value + EPS)
        return self.cum[lo], self.cum[hi] - self.cum[lo], self.total - self.cum[hi]

    def quieter_than_level(self, level):
        """Higher level is louder: the share of Manhattan louder than this one."""
        _, ties, louder = self._split(level)
        return 100 * (louder + ties / 2) / self.total

    def quieter_than_rank(self, avg):
        """Higher average rank is quieter: the share of Manhattan whose average is lower."""
        lower, ties, _ = self._split(avg)
        return 100 * (lower + ties / 2) / self.total


class Reference:
    """[V4, V5] The fixed Manhattan for one set of answers: every sample building at a typical apartment."""

    def __init__(self, slots, weights, b=None):
        upgraded = upgrades_ready() if b is None else None
        b = b or baseline.load()
        self.slots, self.weights = slots, weights
        sample_levels = [u["levels"] for u in upgraded["samples"]] if upgraded else [s["levels"] for s in b["samples"]]
        self.rows = [(source_levels(lv, s, typical_unit(s), slots), s.get("weight", 1))
                     for lv, s in zip(sample_levels, b["samples"])]
        self.per_source = {n: _Ranker((r[n], w) for r, w in self.rows) for n in SOURCES}
        self.average_ranker = _Ranker((self.average(self.ranks(r)), w) for r, w in self.rows)
        self.meta = {"buildings": len(b["samples"]), "apartments": b["universe"]["units"], "as_of": b["as_of"]}
        self.upgraded = sorted(n for n in upgraded["fingerprint"] if n in SOURCES) if upgraded else []
        self.recalibrated = bool(upgraded and "recal" in upgraded["fingerprint"])   # [V10]

    def ranks(self, levels):
        return {n: self.per_source[n].quieter_than_level(levels[n]) for n in SOURCES}

    def average(self, ranks):
        return sum(self.weights[n] * ranks[n] for n in SOURCES)


@functools.lru_cache(maxsize=64)
def _reference(slot_key, weight_key):
    return Reference(dict(slot_key), dict(weight_key))


def reference_for(slots, weights, b=None):
    if b is not None:
        return Reference(slots, weights, b)
    return _reference(tuple(sorted(slots.items())), tuple(sorted(weights.items())))


# ---------------------------------------------------------------- the verdict
def block_ranks(neutral, facts, b=None):
    """[V11] Each source for the block, display only: the building's typical apartment (middle floor, side unknown,
    as the sample is ranked) over all 24 hours equally, against the same Manhattan. The same for every renter and
    every apartment in the building, so a bar shows the street, not the apartment; the score, verdict and caps never
    read it (Rafa, 2026-10-29: "the bars by definition are not impacted by an apartment's floor")."""
    slots = uniform_slots()
    ref = reference_for(slots, source_weights(Answers())[0], b)
    return ref.ranks(source_levels(neutral, facts, typical_unit(facts), slots))


def _verdict(neutral, facts, unit, ref, ticked):
    ranks = ref.ranks(source_levels(neutral, facts, unit, ref.slots))
    quieter_than = ref.average_ranker.quieter_than_rank(ref.average(ranks))
    uncapped = baseline.verdict(quieter_than)
    caps = []
    for n in SOURCES:   # [V6]
        if ranks[n] <= V.ANY_SOURCE_CAP_PCT:
            caps.append({"source": n, "cap": V.ANY_SOURCE_CAP_VERDICT,
                         "why": f"in Manhattan's loudest {V.ANY_SOURCE_CAP_PCT:g}%"})
        if n in ticked and ranks[n] <= V.TICKED_SOURCE_CAP_PCT:
            caps.append({"source": n, "cap": V.TICKED_SOURCE_CAP_VERDICT,
                         "why": f"you said it bothers you, and it is in Manhattan's loudest {V.TICKED_SOURCE_CAP_PCT:g}%"})
    i = min([VERDICTS.index(uncapped)] + [VERDICTS.index(c["cap"]) for c in caps])
    for c in caps:
        c["applied"] = VERDICTS.index(c["cap"]) < VERDICTS.index(uncapped)
    return {"verdict": VERDICTS[i], "uncapped_verdict": uncapped, "quieter_than": round(quieter_than, 1),
            "caps": caps, "ranks": {n: round(r, 1) for n, r in ranks.items()}}


def _case(neutral, facts, unit, ref, ticked):
    v = _verdict(neutral, facts, unit, ref, ticked)
    return {"verdict": v["verdict"], "quieter_than": v["quieter_than"], "floor": unit.floor, "side": unit.position}


def score_levels(neutral, facts, unit=None, answers=None, b=None):
    """The v2 score from the decomposition alone (no network): neutral levels per source and window, building facts."""
    unit, answers = unit or model.Unit(), answers or Answers()
    slots = slot_weights(answers)
    weights, ticked = source_weights(answers)
    ref = reference_for(slots, weights, b)
    used, floor_from, side_from = resolve(unit, facts)
    main = _verdict(neutral, facts, used, ref, ticked)

    rng = None   # [V7] a listing silent on floor or side gets its loudest and quietest cases
    if floor_from != "listing" or side_from != "listing":
        low, top = residential_floors(facts)
        known_floor = used.floor if floor_from == "listing" else None
        known_side = used.position if side_from == "listing" else None
        loud = model.Unit(floor=known_floor or low, position=known_side or "front")
        quiet = model.Unit(floor=known_floor or top, position=known_side or "rear")
        rng = {"loudest_case": _case(neutral, facts, loud, ref, ticked),
               "quietest_case": _case(neutral, facts, quiet, ref, ticked)}

    return {
        "verdict": main["verdict"],
        "quieter_than": main["quieter_than"],
        "uncapped_verdict": main["uncapped_verdict"],
        "caps": main["caps"],
        "range": rng,
        "ranks": main["ranks"],
        "block_ranks": {n: round(r, 1) for n, r in block_ranks(neutral, facts, b).items()},
        "weights": {n: round(100 * w, 1) for n, w in weights.items()},
        "ticked": sorted(ticked),
        "slot_weights": {s: round(100 * w, 1) for s, w in slots.items()},
        "unit": {"floor": used.floor, "floor_from": floor_from if used.floor is not None else None,
                 "side": used.position, "side_from": side_from,
                 "building_floors": facts.get("floors"), "ground_floor_commercial": bool(facts.get("commercial"))},
        "manhattan": ref.meta,
    }


def _neutral(inputs):
    pl = inputs.get("pluto") or {}
    u0 = model.Unit(floor=None, position="front")   # facade-neutral, as baseline.neutral_levels
    ings = [model.street(inputs, u0), model.nightlife(inputs, u0, pl), model.building(inputs, u0, pl),
            model.sirens(inputs, u0), model.construction(inputs, u0)]
    return ings, {i["name"]: {w: i["levels"][w] for w in model.WINDOWS} for i in ings}


def _upgraded(inputs, neutral, facts):
    """[V9, V10] The research numbers on the same pulls, then the upgrades, with each source's Upgrade, when the
    upgraded sample was built the same way; else today's levels for the renter and the sample alike."""
    if not upgrades_ready():
        return neutral, {}
    a = inputs["address"]
    recalibrated = recal.levels(inputs)
    levels, ups = upgrades_apply.apply(a["lat"], a["lng"], recalibrated, facts)
    for n, up in ups.items():   # the board: today's model as built -> research numbers -> the module's first step
        first = next((s for s in up.steps if s.id in (f"{n}.today", f"{n}.today_level")), up.steps[0])
        first.label += ", research numbers"
        if first.kind == "today_input":   # it is now computed from the two boxes, so it sits after them
            first.kind = "rule"
        up.steps[:0] = recal.steps(n, neutral[n], recalibrated[n], [first.id])
    return levels, ups


def numbers_of(up):
    """[V12] An upgrade's numeric inputs and rules, for a renter's hover: counts, distances, rates and shares, keyed
    by step. Internal levels (unit "index") never leave the engine [V8]."""
    out = {}
    for s in (up.steps if up else []):
        v = s.value
        numeric = isinstance(v, (int, float)) and not isinstance(v, bool) or (
            isinstance(v, dict) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values()))
        if s.unit != "index" and numeric:
            out[s.id.split(".", 1)[1]] = {"label": s.label, "value": v, "unit": s.unit, "kind": s.kind}
    return out


def score(inputs, unit=None, answers=None):
    """The v2 score for an address's pulls. Same inputs as model.score; the frozen ingredients supply the evidence."""
    answers = answers or Answers()
    pl = inputs.get("pluto") or {}
    ings, neutral = _neutral(inputs)
    facts = baseline.building_facts(pl)
    levels, ups = _upgraded(inputs, neutral, facts)
    core = score_levels(levels, facts, unit, answers)
    ingredients = [{
        "name": i["name"], "label": LABEL_OVERRIDES.get(i["name"], i["label"]),
        "quieter_than": core["ranks"][i["name"]],
        "block_quieter_than": core["block_ranks"][i["name"]],
        "verdict": baseline.verdict(core["ranks"][i["name"]]),
        "weight": core["weights"][i["name"]],
        "ticked": i["name"] in core["ticked"],
        "temporary": i["temporary"],
        "evidence": i["evidence"] + (ups[i["name"]].evidence if i["name"] in ups else []),
        "numbers": numbers_of(ups.get(i["name"])),
    } for i in ings]
    # [V12] the routes behind the sirens rank, display only; null when the upgrades are not in use
    sirens = upgrades_apply.module("sirens") if ups else None
    next(i for i in ingredients if i["name"] == "sirens")["routes"] = (
        sirens.routes(inputs["address"]["lat"], inputs["address"]["lng"]) if sirens else None)
    coverage = coverage_of(inputs["address"])
    return {
        "engine": "v2",
        "verdict": core["verdict"],
        "quieter_than": core["quieter_than"],
        "uncapped_verdict": core["uncapped_verdict"],
        "caps": core["caps"],
        "range": core["range"],
        "ingredients": ingredients,
        "answers": {"sleep": {"from": answers.sleep[0], "until": answers.sleep[1]},
                    "day_bothers": answers.day_bothers, "ticks": list(answers.ticks)},
        "slot_weights": core["slot_weights"],
        "unit": core["unit"],
        "address": inputs["address"],
        "building_facts": {k: pl.get(k) for k in ("address", "yearbuilt", "numfloors", "bldgclass", "unitsres", "unitstotal")} if pl else None,
        "manhattan": core["manhattan"],
        "as_of": inputs.get("as_of"),
        "lookback_months": inputs.get("lookback_months"),
        "sources": inputs.get("sources", []),
        "caveats": [
            "Every number here is a rank against Manhattan, not a sound measurement.",
            "Each source is compared only with the same source elsewhere; the weights say which matters more.",
            "311 counts measure who complains, not how loud it is.",
            "Construction is temporary; permits expire.",
        ] + ([OUTSIDE_MANHATTAN] if coverage["outside_manhattan"] else []),
        "coverage": coverage,
    }


# [HIQ-138, decision D3's default] The sample and the source upgrades are Manhattan's. Another borough still
# scores, against Manhattan, and says so: its upgrades pass through, and its neighbours index is relative to
# that borough's own 311 rate.
OUTSIDE_MANHATTAN = "Ranked against Manhattan; the source upgrades cover Manhattan only."


def coverage_of(address):
    borough = (address or {}).get("borough")
    return {"borough": borough, "outside_manhattan": bool(borough) and borough != "Manhattan",
            "ranked_against": "Manhattan"}


# ---------------------------------------------------------------- the math board
LABELS = {"street": "Street", "nightlife": "Local businesses", "building": "Neighbors", "sirens": "Sirens",
          "construction": "Construction"}


def explain(inputs, unit=None, answers=None, label=None):
    """The math board for one address: each source's steps and every engine number. This is the method view,
    so it carries internal levels; /v2/score never does [V8]."""
    from dataclasses import asdict
    answers, unit = answers or Answers(), unit or model.Unit()
    ings, neutral = _neutral(inputs)
    facts = baseline.building_facts(inputs.get("pluto") or {})
    levels, ups = _upgraded(inputs, neutral, facts)
    core = score_levels(levels, facts, unit, answers)
    slots = slot_weights(answers)
    weights, _ = source_weights(answers)
    ref = reference_for(slots, weights)
    used, _, _ = resolve(unit, facts)
    adj = position_db(facts, used)
    number = source_levels(levels, facts, used, slots)
    awake = V.AWAKE_HOUR_WEIGHT if answers.day_bothers else V.AWAKE_HOUR_WEIGHT_NOT_BOTHERED
    sources = []
    for i in ings:
        n = i["name"]
        up = ups.get(n) or upgrades.passthrough(n, neutral[n])
        sources.append({"name": n, "label": LABELS[n], "weight": core["weights"][n], "rank": core["ranks"][n],
                        "block_rank": core["block_ranks"][n],
                        "slot_levels": {s: round(levels[n][s], 1) for s in model.WINDOWS},
                        "position_adj": round(adj[n], 1), "number": round(number[n], 1),
                        "evidence": i["evidence"] + up.evidence, "steps": [asdict(s) for s in up.steps]})
    example = {
        "label": label or inputs["address"].get("label"), "unit": core["unit"],
        "answers": {"sleep_from": answers.sleep[0], "sleep_until": answers.sleep[1],
                    "day_bothers": answers.day_bothers, "ticks": list(answers.ticks)},
        "hour_weights": [V.ASLEEP_HOUR_WEIGHT if _asleep(h, *answers.sleep) else awake for h in range(24)],
        "slot_weights": core["slot_weights"], "verdict": core["verdict"], "uncapped_verdict": core["uncapped_verdict"],
        "quieter_than": core["quieter_than"], "caps": core["caps"], "range": core["range"], "sources": sources,
        "upgraded_sources": ref.upgraded,
    }
    reference = {"sources": list(SOURCES),
                 "sample_ranks": [[round(ref.ranks(r)[n], 1) for n in SOURCES] for r, _ in ref.rows],
                 "sample_weights": [w for _, w in ref.rows]}
    return example, reference
