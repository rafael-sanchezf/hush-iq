"""Neighbors upgrade (building): never raises, three slots, valid board, direction and caps. No network."""
import math
import re
from pathlib import Path

import pytest

from noise_score import baseline
from noise_score.upgrades import SLOTS, building as B, load

TODAY = {"night": 44.0, "early": 38.0, "day": 41.0}


def doc(lots, classes=None):
    """A tiny artifact in memory. lots: [(lat, lng, bbl, units, floors, buildings, class_code, short_stays, apts_within_150m)]."""
    classes = classes or {
        "D1": [50000, 800, 500.0, 14.0],     # rentals: 1.6 times the expected complaints
        "D4": [50000, 100, 500.0, 1.0],      # co-ops: 0.2 times
        "C1": [50000, 500, 500.0, 10.0],     # walk-ups: 1.0 times
    }
    codes = sorted(classes) + [c for c in {l[6] for l in lots} if c not in classes]
    cols = {k: [] for k in ("lat", "lng", "bbl", "units", "floors", "nb", "rad", "comm", "str", "u150", "cls")}
    for lat, lng, bbl, units, floors, nb, code, stays, near in lots:
        for k, v in zip(cols, (lat, lng, bbl, units, floors, nb, 15, 0, stays, near, codes.index(code))):
            cols[k].append(v)
    return {"name": "building", "version": 1, "built": "2026-10-28", "typical_upf": 6.8, "manhattan_rate100": 6.3,
            "class_codes": codes, "classes": classes, "lots": cols, "datasets": [], "windows": {}}


# apartments per floor: 2, 7, 14, 40 (all rentals, 6 floors up to 40), far apart on the island
LOTS = [
    (40.7300, -73.9900, 1, 12, 6, 1, "D1", 0, 1500),
    (40.7400, -73.9900, 2, 42, 6, 1, "D1", 0, 1500),
    (40.7500, -73.9900, 3, 84, 6, 1, "D1", 0, 1500),
    (40.7600, -73.9900, 4, 240, 6, 1, "D1", 0, 1500),
    (40.7700, -73.9900, 5, 84, 6, 1, "D4", 0, 1500),     # same size as lot 3, a co-op
    (40.7800, -73.9900, 6, 84, 6, 1, "D1", 40, 1500),    # same as lot 3, many short stays around
    (40.7900, -73.9900, 7, 84, 6, 1, "ZZ", 0, 1500),     # a class that is not in the class table
]


@pytest.fixture(autouse=True)
def synthetic():
    B._reset(doc(LOTS))
    yield
    B._reset()


def up(i, today=TODAY, facts=None):
    lat, lng = LOTS[i][0], LOTS[i][1]
    return B.upgrade(lat, lng, today, facts if facts is not None else {})


def step(u, sid):
    return next(s for s in u.steps if s.id == sid)


def avg(u):
    return sum(u.levels.values()) / 3


def test_never_raises_off_land_and_on_bad_input():
    for lat, lng in ((40.7600, -74.0100),     # Hudson River
                     (40.7829, -73.9654),     # Central Park
                     (0.0, 0.0), (91.0, 400.0), (float("nan"), float("nan")), (None, None)):
        u = B.upgrade(lat, lng, TODAY, {})
        assert u.levels == TODAY and u.steps[-1].id.endswith(".level")
    for today in ({}, None, {"night": "x"}, {"night": 1}, "loud"):
        u = B.upgrade(40.73, -73.99, today, {})
        assert set(u.levels) <= set(SLOTS)
    for facts in (None, 7, {"bbl": "not a number", "floors": "six"}, {"bbl": 999}):
        assert B.upgrade(40.73, -73.99, TODAY, facts).levels


def test_missing_artifact_is_a_passthrough():
    B._reset()
    B._TRIED = True            # nothing built, as on a fresh checkout
    u = B.upgrade(40.73, -73.99, TODAY, {})
    assert u.levels == TODAY and [s.id for s in u.steps] == ["building.today", "building.level"]


def test_three_slots_and_a_valid_board():
    for i in range(len(LOTS)):
        u = up(i)
        assert tuple(u.levels) == SLOTS
        ids = [s.id for s in u.steps]
        assert len(ids) == len(set(ids))
        assert all(f in ids for s in u.steps for f in s.feeds)
        last = u.steps[-1]
        assert last.id == "building.level" and last.kind == "result" and set(last.value) == set(SLOTS)
        assert all("Neighbors" in s.label for s in u.steps)
        assert {s.status for s in u.steps} <= {"live", "new", "judgment"}
        assert {s.kind for s in u.steps} <= {"today_input", "new_input", "rule", "result"}
        for s in u.steps:      # every box reaches the result
            seen, todo = set(), [s.id]
            while todo:
                x = todo.pop()
                if x in seen:
                    continue
                seen.add(x)
                todo += next(t.feeds for t in u.steps if t.id == x)
            assert "building.level" in seen


def test_the_adjustment_is_the_same_in_every_slot_and_today_is_kept():
    u = up(1)
    delta = {s: u.levels[s] - TODAY[s] for s in SLOTS}
    assert max(delta.values()) - min(delta.values()) < 1e-9
    assert abs(delta["night"] - step(u, "building.adjust").value) < 0.01


def test_more_apartments_per_floor_give_a_higher_level(monkeypatch):
    """The rule is off by decision U1; this checks it still works if switched back on."""
    monkeypatch.setattr(B, "HALLWAY_PER_DOUBLING", 0.5)
    levels = [avg(up(i)) for i in range(4)]       # 2, 7, 14, 40 per floor
    assert levels[0] < levels[1] < levels[2] < levels[3]
    assert step(up(0), "building.rule_hall").value == 0.0      # below typical: nothing


def test_apartments_per_floor_is_off_by_default():
    assert B.HALLWAY_PER_DOUBLING == 0.0
    assert step(up(3), "building.rule_hall").value == 0.0


def test_caps_hold():
    d = up(3)
    assert 0 <= step(d, "building.rule_hall").value <= B.HALLWAY_CAP
    s = up(5)
    assert 0 < step(s, "building.rule_str").value <= B.STR_CAP
    for i in range(len(LOTS)):
        u = up(i)
        assert abs(step(u, "building.rule_type").value) <= B.CLASS_CAP + 1e-9
        assert abs(step(u, "building.adjust").value) <= B.TOTAL_CAP + 1e-9
    # an extreme class and an extreme lot still stop at the caps
    B._reset(doc(LOTS, {"D1": [50000, 50000, 500.0, 90.0], "D4": [50000, 0, 5000.0, 0.0], "C1": [50000, 500, 500.0, 10.0]}))
    assert abs(step(up(3), "building.rule_type").value - B.CLASS_CAP) < 1e-6
    assert abs(step(up(4), "building.rule_type").value + B.CLASS_CAP) < 1e-6
    assert step(up(3), "building.adjust").value <= B.TOTAL_CAP + 1e-9


def test_a_coop_reads_quieter_than_a_rental_of_the_same_size():
    assert avg(up(4)) < avg(up(2))
    assert step(up(4), "building.rule_type").value < 0 < step(up(2), "building.rule_type").value


def test_short_stays_raise_the_level_a_little():
    assert avg(up(5)) > avg(up(2))
    assert avg(up(5)) - avg(up(2)) <= B.STR_CAP + 1e-9


def test_unknown_class_means_no_type_adjustment():
    assert step(up(6), "building.rule_type").value == 0.0


def test_the_bbl_in_the_facts_wins_over_position():
    u = B.upgrade(40.7300, -73.9900, TODAY, {"bbl": "4"})       # lot 4's number at lot 1's place
    assert step(u, "building.units").value == 240


def test_evidence_is_counts_for_a_renter():
    for i in range(len(LOTS)):
        ev = up(i).evidence
        assert 1 <= len(ev) <= 3
        for e in ev:
            assert not re.search(r"\bdB\b|decibel|index", e, re.I) and e.endswith(".")
    assert up(2).evidence[0] == "About 14 apartments share each floor."
    assert any("short-term rental" in e for e in up(5).evidence)
    assert not any("short-term" in e for e in up(2).evidence)


def test_a_wide_class_difference_is_not_a_double_count():
    """The same building with no adjustment sits at today's level: a typical class gives a small move."""
    B._reset(doc(LOTS, {"D1": [50000, 500, 500.0, 6.3], "D4": [50000, 500, 500.0, 6.3], "C1": [50000, 500, 500.0, 6.3]}))
    assert abs(step(up(2), "building.rule_type").value) < 1e-6


# ---------------------------------------------------------------- the built artifact, when it is on disk
REAL = load(B.NAME)
real = pytest.mark.skipif(REAL is None, reason="data/upgrades/building.json.gz not built")


@real
def test_built_artifact_is_manhattan_only_and_small():
    p = Path(__file__).resolve().parent.parent / "noise_score" / "data" / "upgrades" / "building.json.gz"
    assert p.stat().st_size < 8_000_000
    lots = REAL["lots"]
    assert 25_000 < len(lots["lat"]) < 40_000
    assert all(40.6 < x < 40.95 for x in lots["lat"]) and all(-74.05 < x < -73.7 for x in lots["lng"])
    assert REAL["datasets"] and all(d["id"] for d in REAL["datasets"])


@real
def test_every_baseline_building_is_matched_and_valid():
    B._reset(REAL)
    samples = baseline.load()["samples"]
    moved = 0
    for s in samples:
        u = B.upgrade(s["lat"], s["lng"], s["levels"]["building"], s)
        ids = [x.id for x in u.steps]
        assert tuple(u.levels) == SLOTS and len(ids) == len(set(ids)) and ids[-1] == "building.level"
        assert "building.adjust" in ids, s["address"]
        assert all(f in ids for x in u.steps for f in x.feeds)
        moved += u.levels != s["levels"]["building"]
    assert moved > len(samples) * 0.9
    B._reset()


@real
def test_matching_by_position_alone_finds_the_same_lot():
    B._reset(REAL)
    idx = B._index()
    for s in baseline.load()["samples"][:60]:
        i = idx.find(s["lat"], s["lng"], {"floors": s["floors"], "commercial": s["commercial"]})
        assert i is not None and idx.c["bbl"][i] == int(s["bbl"])
    B._reset()


@real
def test_runtime_is_fast_once_loaded():
    import time
    B._reset(REAL)
    t = time.perf_counter()
    for s in baseline.load()["samples"][:100]:
        B.upgrade(s["lat"], s["lng"], s["levels"]["building"], {"floors": s["floors"], "commercial": s["commercial"]})
    assert (time.perf_counter() - t) / 100 < 0.05
    B._reset()


def test_write_up_exists_and_is_short_and_plain():
    p = Path(__file__).resolve().parent.parent / "upgrades" / "building.md"
    if not p.exists():
        pytest.skip("write-up not there yet")
    text = p.read_text()
    assert len(text.splitlines()) < 80 and chr(0x2014) not in text
