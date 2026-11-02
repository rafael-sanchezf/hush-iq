"""Sirens upgrade: routes of fire engines and ambulances averaged with today's distance-to-station estimate.
No network: a small synthetic artifact for the rules, the built artifact (when present) for the real thing."""
import copy
import json
import math

import pytest

from noise_score.upgrades import SLOTS, Step, load, sirens

TODAY = {"night": 50.0, "early": 51.0, "day": 53.0}
STREET = (40.752, -73.98)          # on the synthetic street
RIVER = (40.76, -74.03)            # in the Hudson River, 2 km from the synthetic street
FAR = (40.2, -74.9)


def make_doc(per_year=3650, fire=None, ambulance=None, transport=None):
    """A north-south street of three 220 m segments; `per_year` trips per slot per category on each."""
    counts = [fire if fire is not None else per_year] * 3 + \
             [ambulance if ambulance is not None else per_year] * 3 + \
             [transport if transport is not None else per_year] * 3
    segs = [[40.75 + k * 0.002, -73.98, 40.752 + k * 0.002, -73.98, 0, list(counts)] for k in range(3)]
    return {
        "name": "sirens", "days": 365, "slot_hours": {"night": 7, "early": 3, "day": 14},
        "cats": ["fire", "ambulance", "transport"], "names": ["Test Avenue"], "segments": segs,
        "facilities": {"hospital": [[40.7510, -73.9805, "H"]], "fire": [[40.7520, -73.9790, "F"]],
                       "police": [[40.7530, -73.9810, "P"]]},
        "params": {"radius_m": 300, "ref_m": 30, "exponent": 1.33, "min_dist_m": 10, "step_m": 25, "street_m": 50,
                   "cover_m": 500, "mix": 0.5, "floor": 35.0, "ceil": 70.0},
        "calibration": {"a": 51.0, "b": 10.0, "eps": 0.01, "target": {"median": 51.7, "iqr": 6.6}},
    }


@pytest.fixture
def synth():
    sirens._set_artifact(make_doc())
    yield
    sirens._set_artifact(None)


def run(pt=STREET, today=TODAY):
    return sirens.upgrade(pt[0], pt[1], dict(today), {"floors": 6, "commercial": False})


def level_step(up, step_id):
    return next(s for s in up.steps if s.id == step_id)


# ---------------------------------------------------------------- the contract
def test_name_and_three_slots(synth):
    assert sirens.NAME == "sirens"
    up = run()
    assert set(up.levels) == set(SLOTS) == {"night", "early", "day"}
    assert all(isinstance(v, float) and math.isfinite(v) for v in up.levels.values())


def test_step_ids_unique_and_feeds_point_at_existing_ids(synth):
    up = run()
    ids = [s.id for s in up.steps]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("sirens.") for i in ids)
    for s in up.steps:
        assert isinstance(s, Step)
        for f in s.feeds:
            assert f in ids, f"{s.id} feeds {f}, which is not a step"
        assert s.kind in ("today_input", "new_input", "rule", "result")
        assert s.status in ("live", "new", "judgment")


def test_last_step_is_the_result_with_per_slot_levels(synth):
    up = run()
    last = up.steps[-1]
    assert last.id == "sirens.level" and last.kind == "result" and last.unit == "index"
    assert set(last.value) == set(SLOTS)
    for s in SLOTS:
        assert abs(last.value[s] - up.levels[s]) < 0.01
    assert [s.id for s in up.steps].count("sirens.level") == 1
    # the board is one tree: the result is the only box that feeds nothing
    assert {s.id for s in up.steps if not s.feeds} == {"sirens.level"}


def test_board_shows_today_new_and_judgment_steps(synth):
    up = run()
    status = {s.id: s.status for s in up.steps}
    for i in ("sirens.hospital_m", "sirens.firehouse_m", "sirens.police_m", "sirens.today_level"):
        assert status[i] == "live"
    for i in ("sirens.street_fire", "sirens.street_ambulance", "sirens.street_transport", "sirens.near_fire",
              "sirens.near_ambulance", "sirens.near_transport", "sirens.route_level"):
        assert status[i] == "new"
    assert "judgment" in status.values()
    assert level_step(up, "sirens.today_level").value == TODAY


def test_result_is_json_serialisable(synth):
    json.dumps(run().as_dict())


# ---------------------------------------------------------------- the rules
def test_weight_halves_at_thirty_metres_and_falls_with_distance():
    assert abs(sirens.weight(30) - 0.5) < 1e-9
    assert sirens.weight(5) == sirens.weight(10)          # nothing counts more than at 10 m
    ws = [sirens.weight(d) for d in (10, 30, 60, 120, 300)]
    assert ws == sorted(ws, reverse=True)


def test_more_passes_give_a_higher_level():
    levels = []
    for per_year in (365, 3650, 36500):
        sirens._set_artifact(make_doc(per_year))
        up = run()
        levels.append((level_step(up, "sirens.route_level").value["day"], up.levels["day"]))
    sirens._set_artifact(None)
    assert levels[0][0] < levels[1][0] < levels[2][0]
    assert levels[0][1] < levels[1][1] < levels[2][1]


def test_each_category_adds_to_the_exposure():
    sirens._set_artifact(make_doc(fire=0, ambulance=0, transport=0))
    base = level_step(run(), "sirens.exposure").value["day"]
    for kw in ("fire", "ambulance", "transport"):
        sirens._set_artifact(make_doc(**{kw: 3650, **{k: 0 for k in ("fire", "ambulance", "transport") if k != kw}}))
        assert level_step(run(), "sirens.exposure").value["day"] > base
    sirens._set_artifact(None)


def test_moving_away_from_the_street_lowers_the_level(synth):
    near = run((40.752, -73.9801)).levels["day"]
    mid = run((40.752, -73.9815)).levels["day"]
    far = run((40.752, -73.9838)).levels["day"]
    assert near > mid > far


def test_combined_level_is_the_average_of_today_and_the_route_level(synth):
    up = run()
    route = level_step(up, "sirens.route_level").value
    for s in SLOTS:
        lo, hi = sorted((TODAY[s], route[s]))
        assert lo - 1e-6 <= up.levels[s] <= hi + 1e-6
        assert abs(up.levels[s] - (0.5 * TODAY[s] + 0.5 * route[s])) < 0.01   # 2-decimal rounding on the board


def test_average_stays_between_today_and_route_whatever_today_is(synth):
    for t in (30.0, 45.0, 60.0, 75.0):
        today = {s: t for s in SLOTS}
        up = run(today=today)
        route = level_step(up, "sirens.route_level").value
        for s in SLOTS:
            lo, hi = sorted((t, route[s]))
            assert lo - 1e-6 <= up.levels[s] <= hi + 1e-6


def test_route_level_stays_inside_todays_range(synth):
    cal, p = sirens._cached["doc"]["calibration"], sirens._cached["doc"]["params"]
    assert sirens.route_level(0.0, cal, p) == 35.0
    assert sirens.route_level(1e9, cal, p) == 70.0


def test_street_counts_per_day_and_the_hospital_sentence():
    # per-slot yearly counts 730, 365, 3650 are 6, 3 and 30 trips a day (three slots, 365 days); hospital 100 m away
    sirens._set_artifact(make_doc(fire=730, ambulance=365, transport=3650))
    up = run((40.7515, -73.9801))
    sirens._set_artifact(None)
    assert level_step(up, "sirens.street_fire").value == 6.0
    assert level_step(up, "sirens.street_ambulance").value == 3.0
    assert level_step(up, "sirens.street_transport").value == 30.0
    text = " ".join(up.evidence)
    assert "About 35 ambulance trips a day pass on this block, most heading to a hospital about 60 m away." in text
    assert "About 6 fire engine runs a day use it too." in text


# ---------------------------------------------------------------- evidence
def test_evidence_is_counts_and_distances_only(synth):
    ev = run().evidence
    assert 1 <= len(ev) <= 3
    for line in ev:
        low = line.lower()
        assert "db" not in low and "decibel" not in low and "index" not in low and "level" not in low
        assert "—" not in line and "–" not in line
        assert line.endswith(".")


def test_quiet_block_says_so(synth):
    ev = run((40.752, -73.9835)).evidence      # 450 m west: inside coverage, outside the 50 m block
    assert ev[0].startswith("Almost no ambulance or fire engine trips")


# ---------------------------------------------------------------- never raises
@pytest.mark.parametrize("pt", [RIVER, FAR, (0.0, 0.0), (float("nan"), 1.0), (None, None), ("x", "y"),
                                (float("inf"), float("inf"))])
@pytest.mark.parametrize("today", [TODAY, {}, None, {"night": "bad"}])
def test_never_raises(pt, today):
    sirens._set_artifact(make_doc())
    try:
        up = sirens.upgrade(pt[0], pt[1], today, None)
    finally:
        sirens._set_artifact(None)
    assert set(up.levels) == set(SLOTS)
    assert up.steps[-1].id == "sirens.level"


def test_outside_the_routes_today_is_unchanged(synth):
    for pt in (RIVER, FAR):
        up = run(pt)
        assert up.levels == TODAY
        assert up.steps[-1].id == "sirens.level" and up.steps[-1].kind == "result"
        assert "unchanged" in up.steps[-1].formula


def test_missing_artifact_passes_today_through(monkeypatch):
    sirens._cached.update(doc=None, idx=None, done=False)
    monkeypatch.setattr(sirens, "load", lambda name: None)
    up = run()
    assert up.levels == TODAY
    assert [s.id for s in up.steps] == ["sirens.today", "sirens.level"]
    sirens._set_artifact(None)


def test_unreadable_artifact_passes_today_through(monkeypatch):
    def boom(name):
        raise OSError("disk")
    sirens._cached.update(doc=None, idx=None, done=False)
    monkeypatch.setattr(sirens, "load", boom)
    assert run().levels == TODAY
    sirens._set_artifact(None)


def test_broken_artifact_passes_today_through():
    bad = copy.deepcopy(make_doc())
    bad["segments"] = [[1, 2]]
    sirens._cached.update(doc=None, idx=None, done=True)
    try:
        sirens._set_artifact(bad)
    except Exception:
        sirens._cached.update(doc=None, idx=None, done=True)
    assert run().levels == TODAY
    sirens._set_artifact(None)


# ---------------------------------------------------------------- the built artifact
BUILT = load("sirens")
built = pytest.mark.skipif(BUILT is None, reason="sirens.json.gz not built")


@built
def test_artifact_is_compact_and_complete():
    from noise_score.upgrades import DATA
    assert (DATA / "sirens.json.gz").stat().st_size < 8_000_000
    assert len(BUILT["segments"]) > 3000
    assert all(len(s[5]) == 9 and len(s) == 6 for s in BUILT["segments"])
    assert {d["id"] for d in BUILT["datasets"]} >= {"8m42-w767", "76xm-jjuj", "v57i-gtxb", "bst7-5464", "hc8x-tcnd", "67g2-p84d"}
    assert BUILT["window"] == ["2025-10-01", "2026-10-01"]
    assert BUILT["calibration"]["b"] > 0


@built
def test_built_artifact_gives_levels_for_manhattan_and_is_fast():
    import time
    sirens._set_artifact(None)
    up = sirens.upgrade(40.7484, -73.9857, dict(TODAY), {})           # first call loads the artifact
    t = time.perf_counter()
    for _ in range(20):
        up = sirens.upgrade(40.7484, -73.9857, dict(TODAY), {})
    assert (time.perf_counter() - t) / 20 < 0.05
    assert len(up.steps) > 10 and up.steps[-1].id == "sirens.level"
    for s in SLOTS:
        assert 30 < up.levels[s] < 75


@built
def test_built_artifact_busy_hospital_street_beats_a_quiet_one():
    # East 34th Street leads to the First Avenue hospitals; a side-street block of the Upper East Side does not
    busy = sirens.upgrade(40.7467, -73.9805, {s: 40.0 for s in SLOTS}, {})
    quiet = sirens.upgrade(40.7810, -73.9560, {s: 40.0 for s in SLOTS}, {})
    assert busy.levels["day"] > quiet.levels["day"]


@built
def test_built_artifact_is_calibrated_to_todays_scale_on_the_baseline():
    from noise_score import baseline, recal
    samples = baseline.load()["samples"]
    start = recal.sample() or {s["bbl"]: s["levels"] for s in samples}   # today's scale: the research numbers [V10]
    route, today = [], []
    for s in samples:
        lv = start[s["bbl"]]["sirens"]
        up = sirens.upgrade(s["lat"], s["lng"], lv, s)
        route.append([level_step(up, "sirens.route_level").value[k] for k in SLOTS] if len(up.steps) > 2 else None)
        today.append([lv[k] for k in SLOTS])
    pairs = [(r, t) for r, t in zip(route, today) if r]
    assert len(pairs) > 0.95 * len(samples)
    flat_r = sorted(x for r, _ in pairs for x in r)
    flat_t = sorted(x for _, t in pairs for x in t)
    med = lambda v: v[len(v) // 2]
    iqr = lambda v: v[3 * len(v) // 4] - v[len(v) // 4]
    assert abs(med(flat_r) - med(flat_t)) < 1.0
    assert abs(iqr(flat_r) - iqr(flat_t)) < 1.0
