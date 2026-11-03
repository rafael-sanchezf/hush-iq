"""Nightlife upgrade: contract, never raises, monotone in outdoor seating and complaint nights, caps. No network."""
import math
import time

import pytest

from noise_score.upgrades import DATA, SLOTS, nightlife as N

LAT, LNG = 40.7500, -73.9900            # a point on the synthetic map
TODAY = {"night": 55.0, "early": 45.0, "day": 47.0}
FACTS = {"floors": 6, "commercial": True}
REAL = DATA / "nightlife.json.gz"


def doc(venues=(), cafes=(), incidents=None, days=730):
    """A tiny artifact. incidents: {slot: [(lat, lng, night, count), ...]}."""
    descs = ["Restaurant", "Food & Beverage Business", "Hotel"]
    inc = {}
    for s in SLOTS:
        rows = sorted({(round((lng - N.X0) / N.GRID), round((lat - N.Y0) / N.GRID), n): c
                       for lat, lng, n, c in (incidents or {}).get(s, [])}.items())
        inc[s] = {"x": [k[0] for k, _ in rows], "y": [k[1] for k, _ in rows], "n": [k[2] for k, _ in rows], "c": [c for _, c in rows]}
    return {"window": {"start": "2024-10-01", "end": "2026-10-01", "days": days}, "descs": descs,
            "venues": [list(v) for v in venues], "cafes": [list(c) for c in cafes], "inc": inc}


def east(m):
    """Longitude shifted east by m metres."""
    return LNG + m / 84300.0


@pytest.fixture(autouse=True)
def restore_artifact():
    yield
    N._ART, N._LOADED = None, False   # next call reloads the built file


def run(d, lat=LAT, lng=LNG, today=TODAY):
    N._install(d)
    return N.upgrade(lat, lng, today, FACTS)


def step(up, sid):
    return next(s for s in up.steps if s.id == sid)


# ---------------------------------------------------------------- never raises, contract
def test_missing_artifact_is_a_passthrough():
    up = run(None)
    assert up.levels == TODAY
    assert [s.id for s in up.steps][-1] == "nightlife.level"
    assert step(up, "nightlife.level").kind == "result"


@pytest.mark.skipif(not REAL.exists(), reason="artifact not built")
@pytest.mark.parametrize("lat,lng", [
    (40.7300, -74.0180),     # Hudson River
    (41.50, -75.00),         # far outside the city
    (0.0, 0.0),
    (40.7580, -73.9855),     # Times Square
])
def test_real_artifact_never_raises(lat, lng):
    N._ART, N._LOADED = None, False
    up = N.upgrade(lat, lng, TODAY, FACTS)
    assert set(up.levels) == set(SLOTS)
    assert all(math.isfinite(v) for v in up.levels.values())
    assert 1 <= len(up.evidence) <= 3


@pytest.mark.skipif(not REAL.exists(), reason="artifact not built")
def test_river_and_empty_ground_change_nothing():
    N._ART, N._LOADED = None, False
    for lat, lng in [(40.7300, -74.0180), (41.50, -75.00)]:
        up = N.upgrade(lat, lng, TODAY, FACTS)
        assert up.levels == pytest.approx(TODAY, abs=1e-6)
        assert "No outdoor dining" in up.evidence[0]


@pytest.mark.parametrize("lat,lng,today", [
    (None, None, TODAY), ("x", "y", TODAY), (float("nan"), 1.0, TODAY), (LAT, LNG, {}), (LAT, LNG, None),
    (LAT, LNG, {"night": None, "early": 1, "day": 2}), (LAT, LNG, {"night": float("nan"), "early": 1, "day": 2}),
])
def test_garbage_in_never_raises(lat, lng, today):
    up = run(doc(venues=[(LAT, LNG, 0, "0340")]), lat, lng, today)
    assert set(up.levels) == set(SLOTS)
    assert all(math.isfinite(v) for v in up.levels.values())


def test_three_slots_unique_ids_valid_feeds_and_result_last():
    d = doc(venues=[(LAT, east(30), 1, "0370")], cafes=[(LAT, east(20), 0)],
            incidents={"night": [(LAT, east(10), 5, 2)], "day": [(LAT, east(10), 6, 1)]})
    up = run(d)
    ids = [s.id for s in up.steps]
    assert len(ids) == len(set(ids))
    assert ids[-1] == "nightlife.level"
    for s in up.steps:
        assert s.id.startswith("nightlife.")
        assert all(f in ids for f in s.feeds), (s.id, s.feeds)
        assert s.kind in ("today_input", "new_input", "rule", "result")
        assert s.status in ("live", "new", "judgment")
    res = step(up, "nightlife.level")
    assert res.kind == "result" and set(res.value) == set(SLOTS) and res.value == up.levels
    assert set(up.levels) == set(SLOTS)
    assert {s.status for s in up.steps} == {"live", "new", "judgment"}
    assert all(s.unit == "index" for s in up.steps if s.id in ("nightlife.today", "nightlife.level", "nightlife.outdoor"))
    assert 1 <= len(up.evidence) <= 3
    assert not any("dB" in e or "decibel" in e.lower() for e in up.evidence)


def test_today_steps_are_live_and_new_inputs_are_new():
    up = run(doc(venues=[(LAT, LNG, 0, "0340")], cafes=[(LAT, LNG, 0)], incidents={"night": [(LAT, LNG, 1, 1)]}))
    assert step(up, "nightlife.venues").status == "live" and step(up, "nightlife.complaints").status == "live"
    assert step(up, "nightlife.cafes").status == "new" and step(up, "nightlife.complaint_nights").status == "new"
    assert step(up, "nightlife.terrace_db").status == "new" and step(up, "nightlife.cap").status == "judgment"


# ---------------------------------------------------------------- the rules
def test_more_outdoor_seating_gives_a_higher_level_by_day_and_night_and_none_in_the_early_slot():
    venues = [(LAT, east(15 + 6 * i), 0, "0340") for i in range(20)]   # enough venues that the cafe share stays under 1
    prev = None
    for n in (0, 2, 4, 8):
        cafes = [(LAT, east(30 + 6 * i), i % 2) for i in range(n)]
        up = run(doc(venues=venues, cafes=cafes))
        if prev is not None:
            assert up.levels["night"] > prev["night"] and up.levels["day"] > prev["day"]
            assert up.levels["early"] == pytest.approx(prev["early"], abs=1e-6)
        prev = up.levels
    assert prev["day"] - TODAY["day"] > prev["night"] - TODAY["night"] > 0


def test_a_nearer_cafe_counts_more_than_a_farther_one():
    venues = [(LAT, east(15), 0, "0340")]
    near = run(doc(venues=venues, cafes=[(LAT, east(12), 0)])).levels["day"]
    far = run(doc(venues=venues, cafes=[(LAT, east(140), 0)])).levels["day"]
    assert near > far > TODAY["day"] - 1


def test_more_complaint_nights_give_a_higher_night_level():
    levels = []
    for k in (1, 10, 60, 200, 700):    # one complaint a night: nights equal complaints until today's 12 dB ceiling is reached
        inc = {"night": [(LAT, east(20), n, 1) for n in range(k)]}
        levels.append(run(doc(incidents=inc)).levels["night"])
    assert levels == sorted(levels) and levels[3] > levels[2] and levels[4] > levels[3] > TODAY["night"]


def test_counting_nights_not_complaints():
    """Forty complaints on one night is one night of noise, not forty."""
    one_night = run(doc(incidents={"night": [(LAT, east(20), 7, 40)]})).levels["night"]
    forty_nights = run(doc(incidents={"night": [(LAT, east(20), n, 1) for n in range(40)]})).levels["night"]
    assert one_night < forty_nights
    assert one_night < TODAY["night"]    # today's bump reads 40 complaints; nights read 1


def test_complaints_outside_the_radius_do_not_count():
    inc = {"night": [(LAT, east(400), n, 1) for n in range(100)]}
    assert run(doc(incidents=inc)).levels == pytest.approx(TODAY, abs=1e-9)


def test_a_liquor_saloon_licence_grades_above_beer_and_wine():
    liquor = run(doc(venues=[(LAT, east(25), 1, "0370")])).levels["night"]
    wine = run(doc(venues=[(LAT, east(25), 1, "0267")])).levels["night"]
    hotel = run(doc(venues=[(LAT, east(25), 2, "0343")])).levels["night"]
    assert liquor > wine and liquor > hotel
    assert liquor > TODAY["night"] > wine


# ---------------------------------------------------------------- caps
def test_the_two_corrections_stay_inside_the_cap_and_terraces_come_on_top():
    venues = [(LAT, east(12 + i), 2, "0343") for i in range(30)]     # hotels: a grade 6 under other venues
    cafes = [(LAT, east(12 + i), 1) for i in range(30)]
    inc = {"night": [(LAT, east(30), 1, 2000)]}                       # a pile of complaints on one night
    N.TOTAL_CAP_DB, cap = 5.0, N.TOTAL_CAP_DB
    try:
        up = run(doc(venues=venues, cafes=cafes, incidents=inc))
    finally:
        N.TOTAL_CAP_DB = cap
    out = step(up, "nightlife.outdoor").value
    for s in SLOTS:
        assert abs(up.levels[s] - out[s] - TODAY[s]) <= 5.0 + 1e-9
    assert up.levels["night"] - out["night"] - TODAY["night"] == pytest.approx(-5.0, abs=1e-6)   # -3 grade, -2.7 nights
    assert up.levels["day"] - TODAY["day"] > N.TOTAL_CAP_DB      # thirty terraces at the door: sourced, not capped


def test_each_rule_stays_inside_its_own_bounds():
    venues = [(LAT, east(12), 0, "0340")]
    cafes = [(LAT, east(12 + i), 1) for i in range(40)]
    inc = {s: [(LAT, east(30), n, 3) for n in range(730)] for s in SLOTS}
    up = run(doc(venues=venues, cafes=cafes, incidents=inc))
    out = step(up, "nightlife.outdoor").value
    terraces = step(up, "nightlife.terrace").value
    top = 10 * math.log10(10 ** (TODAY["day"] / 10) + N.TERRACE_SLOT_SHARE["day"] * 10 ** (terraces / 10)) - TODAY["day"]
    assert out["day"] <= top + N.TOTAL_CAP_DB and out["early"] == 0 and 0 < out["night"] < out["day"]
    assert N.TERRACE_SLOT_SHARE == pytest.approx({"night": 1 / 7, "early": 0.0, "day": 3 / 14})
    assert N.TERRACE_DB == pytest.approx(56.8, abs=0.05)
    nf = step(up, "nightlife.nights_fix").value
    assert all(v <= N.NIGHTS_MIX * (N.NIGHTS_CAP_DB - 0.0) + 1e-9 for v in nf.values())
    assert N.NIGHTS_CAP_DB == pytest.approx(20.9, abs=0.1)


def test_nothing_nearby_changes_nothing():
    up = run(doc(venues=[(LAT + 0.05, LNG, 0, "0340")], cafes=[(LAT + 0.05, LNG, 0)],
                 incidents={"night": [(LAT + 0.05, LNG, 1, 5)]}))
    assert up.levels == pytest.approx(TODAY, abs=1e-9)
    assert "No outdoor dining" in up.evidence[0]


# ---------------------------------------------------------------- speed and the built file
@pytest.mark.skipif(not REAL.exists(), reason="artifact not built")
def test_built_artifact_loads_once_and_answers_fast():
    N._ART, N._LOADED = None, False
    N.upgrade(40.7580, -73.9855, TODAY, FACTS)      # loads
    t = time.perf_counter()
    for lat, lng in [(40.7580, -73.9855), (40.7266, -73.9815), (40.8116, -73.9465), (40.7061, -74.0088)]:
        N.upgrade(lat, lng, TODAY, FACTS)
    assert (time.perf_counter() - t) / 4 < 0.05


@pytest.mark.skipif(not REAL.exists(), reason="artifact not built")
def test_built_artifact_is_manhattan_sized_and_small():
    assert REAL.stat().st_size < 8_000_000
    N._ART, N._LOADED = None, False
    N.upgrade(40.7580, -73.9855, TODAY, FACTS)
    meta = N._ART["meta"]
    assert len(meta["venues"]) > 5000 and len(meta["cafes"]) > 1000 and meta["window"]["days"] >= 700
