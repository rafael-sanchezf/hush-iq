"""Street upgrade: what actually passes, per hour, by slot. No network."""
import copy
import math

import pytest

from noise_score import baseline
from noise_score.upgrades import SLOTS, street

TODAY = {"night": 60.0, "early": 63.0, "day": 66.0}
SAMPLES = baseline.load()["samples"]

LAT, LNG = 40.7500, -73.9800


def seg(name, cls, q, b=(0, 0, 0), tier=2, lat=LAT, nv=0, route=0):
    """A synthetic east-west segment 120 m long, 30 m north of (lat, LNG) so it is inside the 60 m radius."""
    line = [(LNG - 0.0007, lat + 0.00027), (LNG + 0.0007, lat + 0.00027)]
    return {"n": name, "k": cls, "ln": 3, "sp": 25, "cr": 0, "tw": 0, "nv": nv, "t": route, "s": tier,
            "q": list(q), "b": list(b), "g": [street._encode_part(line)], "cy": 2024, "cd": 1}


def prepared(main, others=()):
    """A tiny artifact: `main` plus counted arterials of 400/300/500 veh/h (the class reference) and a few more."""
    ref = [seg(f"REF {i}", "arterial", (400, 300, 500), lat=LAT + 0.01 * (i + 1)) for i in range(3)]
    doc = {"meta": {"gtfs_date": "2026-11-10"}, "tau": {"0": [0.02, 0.03, 0.05], "1": [0.04, 0.05, 0.08],
                                                        "2": [0.06, 0.07, 0.10]},
           "segs": [main, *others, *ref]}
    return street._prepare(doc)


@pytest.fixture
def use(monkeypatch):
    def _use(prep):
        monkeypatch.setattr(street, "_STATE", {"ready": True, "st": prep})
    return _use


def check_contract(up):
    ids = [s.id for s in up.steps]
    assert len(ids) == len(set(ids)), "step ids must be unique"
    assert ids[-1] == "street.level" and up.steps[-1].kind == "result"
    for s in up.steps:
        for f in s.feeds:
            assert f in ids, f"{s.id} feeds missing step {f}"
        assert s.kind in ("today_input", "new_input", "rule", "result")
        assert s.status in ("live", "new", "judgment")
    assert set(up.levels) == set(SLOTS)
    assert set(up.steps[-1].value) == set(SLOTS)
    assert 1 <= len(up.evidence) <= 3
    for e in up.evidence:
        assert "dB" not in e and "decibel" not in e.lower()


def test_correction_is_zero_at_the_class_volume_and_grows_with_traffic():
    assert street.correction_db(500, 500) == 0
    assert street.correction_db(1000, 500) == pytest.approx(3.01, abs=0.01)
    assert street.correction_db(250, 500) == pytest.approx(-3.01, abs=0.01)
    vals = [street.correction_db(v, 500) for v in (100, 200, 400, 800, 1600)]
    assert vals == sorted(vals)


def test_the_cap_holds_both_ways():
    assert street.correction_db(1e9, 500) == street.CORRECTION_CAP
    assert street.correction_db(0, 500) == -street.CORRECTION_CAP
    assert street.correction_db(0, 0) == 0


def test_a_truck_or_bus_counts_for_more_than_a_car():
    cars = street.effective([100, 100, 100], [0, 0, 0], [0, 0, 0])
    trucks = street.effective([100, 100, 100], [0, 0, 0], [0.1, 0.1, 0.1])
    buses = street.effective([100, 100, 100], [10, 10, 10], [0, 0, 0])
    assert trucks[0] > cars[0] and buses[0] > cars[0]
    assert cars == [100, 100, 100]
    assert buses[0] == pytest.approx(100 + street.K_HEAVY * 10)


def test_more_traffic_gives_a_higher_level(use):
    quiet = prepared(seg("QUIET AVE", "arterial", (100, 50, 150)))
    busy = prepared(seg("BUSY AVE", "arterial", (900, 700, 1100)))
    use(quiet)
    low = street.upgrade(LAT, LNG, TODAY, {})
    use(busy)
    high = street.upgrade(LAT, LNG, TODAY, {})
    for slot in SLOTS:
        assert high.levels[slot] > low.levels[slot]
    check_contract(low)
    check_contract(high)


def test_buses_raise_the_level_on_the_same_street(use):
    plain = prepared(seg("BROADWAY", "arterial", (400, 300, 500), tier=0))
    bussed = prepared(seg("BROADWAY", "arterial", (400, 300, 500), b=(4, 10, 40), tier=0))
    use(plain)
    a = street.upgrade(LAT, LNG, TODAY, {})
    use(bussed)
    b = street.upgrade(LAT, LNG, TODAY, {})
    assert all(b.levels[s] > a.levels[s] for s in SLOTS)
    assert b.levels["day"] - a.levels["day"] > b.levels["night"] - a.levels["night"] - 10
    assert any("buses an hour" in e for e in b.evidence)


def test_the_correction_never_exceeds_the_cap(use):
    huge = prepared(seg("HUGE AVE", "arterial", (1e6, 1e6, 1e6)))
    none = prepared(seg("EMPTY PATH", "arterial", (0, 0, 0), nv=1))
    for prep in (huge, none):
        use(prep)
        up = street.upgrade(LAT, LNG, TODAY, {})
        for slot in SLOTS:
            assert abs(up.levels[slot] - TODAY[slot]) <= street.CORRECTION_CAP + 0.011
        check_contract(up)


def test_two_streets_never_move_more_than_the_cap(use):
    other = seg("SIDE ST", "arterial", (1e6, 1e6, 1e6), lat=LAT - 0.0004)
    use(prepared(seg("MAIN AVE", "arterial", (0, 0, 0), nv=1), [other]))
    up = street.upgrade(LAT, LNG, TODAY, {})
    for slot in SLOTS:
        assert abs(up.levels[slot] - TODAY[slot]) <= street.CORRECTION_CAP + 0.011


def test_the_evidence_names_counts_not_decibels(use):
    counted = prepared(seg("AMSTERDAM AVE", "arterial", (300, 200, 600), b=(2, 8, 40)))
    use(counted)
    up = street.upgrade(LAT, LNG, TODAY, {})
    text = " ".join(up.evidence)
    assert "Amsterdam Ave" in text and "buses an hour" in text and "count" in text


def test_a_street_without_a_count_says_so(use):
    est = prepared(seg("W  81 ST", "arterial", (300, 200, 600), tier=0))
    use(est)
    up = street.upgrade(LAT, LNG, TODAY, {})
    assert any("no traffic count" in e for e in up.evidence)
    ids = {s.id: s for s in up.steps}
    assert "estimated" in ids["street.volume_basis"].value


def test_a_point_in_the_river_returns_today(use):
    use(prepared(seg("MAIN AVE", "arterial", (400, 300, 500))))
    up = street.upgrade(40.7600, -74.0200, TODAY, {})
    assert up.levels == TODAY
    check_contract(up)


def test_a_missing_artifact_passes_today_through(use):
    use(None)
    up = street.upgrade(LAT, LNG, TODAY, {})
    assert up.levels == TODAY
    assert up.steps[-1].id.startswith("street.")


def test_garbage_in_never_raises(use):
    use(prepared(seg("MAIN AVE", "arterial", (400, 300, 500))))
    for args in [(float("nan"), float("nan"), TODAY), (None, None, TODAY), (0, 0, TODAY), (LAT, LNG, {}), (LAT, LNG, None),
                 ("x", "y", TODAY), (91.0, 200.0, TODAY)]:
        up = street.upgrade(*args, {})
        assert up is not None and hasattr(up, "levels")


def test_names_read_well():
    assert street._pretty("W  42 ST") == "West 42nd St"
    assert street._pretty("E  101 ST") == "East 101st St"
    assert street._pretty("AMSTERDAM AVE") == "Amsterdam Ave"
    assert street._pretty("W  END AVE") == "W End Ave"
    assert street._norm("WEST 145 STREET") == street._norm("W  145 ST")


def test_the_built_artifact_if_present():
    doc = street.load(street.NAME)
    if doc is None:
        pytest.skip("street.json.gz not built")
    street._STATE.clear()
    sample = [s for s in SAMPLES][:40]
    for s in sample:
        today = s["levels"]["street"]
        up = street.upgrade(s["lat"], s["lng"], today, {})
        check_contract(up)
        for slot in SLOTS:
            assert abs(up.levels[slot] - today[slot]) <= street.CORRECTION_CAP + 0.011
    # a point in the Hudson and one far from any count (upper Manhattan side street) still answer
    for lat, lng in ((40.7600, -74.0200), (40.8650, -73.9250)):
        check_contract(street.upgrade(lat, lng, TODAY, {}))
    street._STATE.clear()
