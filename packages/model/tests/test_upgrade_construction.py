"""Construction upgrade (engine v2): street work and after-hours work. No network.

Most tests install a tiny artifact in memory (C._use) so they do not depend on the permits of the day; the last
group checks the built artifact when it exists."""
import datetime as dt
import time
from pathlib import Path

import pytest

from noise_score import config as K
from noise_score.upgrades import SLOTS, construction as C, load

LAT, LNG = 40.7500, -73.9800
M = 1 / 111000.0                     # one metre of latitude, in degrees
TODAY = {"night": 40.0, "early": 52.0, "day": 55.0}   # a typical day 55, night -15, early -3
KINDS = {"today_input", "new_input", "rule", "result"}
STATUSES = {"live", "new", "judgment"}


def doc(sites=(), ahv=(), built="2026-10-28"):
    """sites: (metres north, wclass 0..2, days with a permit, active, night hour-days, early hour-days) at a point.
    ahv: (metres north, nights, weighted night hours, early mornings, weighted early hours)."""
    loc, rec = [], []
    for i, (north, wc, days, act, nhd, ehd) in enumerate(sites):
        la = round(LAT + north * M, 6)
        loc.append([la, LNG, la, LNG])
        rec.append([i, 0, wc, 0, 1, days, 1 if act else 0, 20 if act else 0, nhd, ehd])
    sites_ahv = [[round(LAT + n * M, 6), LNG, nights, nh, mornings, eh, 3, 0] for (n, nights, nh, mornings, eh) in ahv]
    return {"built": built, "street": {"loc": loc, "rec": rec}, "ahv": sites_ahv}


NOW = dt.date(2026, 10, 30)          # two days after the synthetic artifacts' build date: the tests do not age


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(C, "_now", lambda: NOW)
    C._reset()
    yield
    C._reset()


def run(d, today=TODAY, lat=LAT, lng=LNG):
    C._use(d)
    return C.upgrade(lat, lng, dict(today), {"floors": 6, "commercial": False})


def step(up, sid):
    return next(s for s in up.steps if s.id == sid)


# ---------------------------------------------------------------- the contract
def test_constants_match_todays_model():
    assert C.BASE_DB == K.CONSTRUCTION_BASE_DB
    assert C.DB_PER_DOUBLING == K.CONSTRUCTION_PERMIT_DB_PER_DOUBLING
    assert C.MAX_BUMP_DB == K.CONSTRUCTION_MAX_BUMP_DB
    assert C.NIGHT_HOURS == K.WINDOW_HOURS["night"]


def test_name():
    assert C.NAME == "construction"


def test_three_slots_and_valid_board():
    up = run(doc([(30, 2, 200, True, 600, 0)], [(40, 100, 400, 50, 60)]))
    assert set(up.levels) == set(SLOTS) and len(up.levels) == 3
    ids = [s.id for s in up.steps]
    assert len(ids) == len(set(ids)), "step ids must be unique"
    for s in up.steps:
        assert s.id.startswith("construction.")
        assert s.kind in KINDS and s.status in STATUSES
        assert set(s.feeds) <= set(ids), f"{s.id} feeds an unknown step"
        assert s.id not in s.feeds
        assert s.label and s.source is not None and s.unit is not None
    last = up.steps[-1]
    assert last.id == "construction.level" and last.kind == "result"
    assert last.value == pytest.approx(up.levels, abs=0.006)
    assert last.unit == "index"
    # today's inputs are live, new inputs are new, chosen numbers are judgment
    assert {s.status for s in up.steps if s.kind == "today_input"} == {"live"}
    assert any(s.status == "new" and s.kind == "new_input" for s in up.steps)
    assert any(s.status == "judgment" for s in up.steps)
    # every non-result step feeds something
    assert all(s.feeds for s in up.steps if s.kind != "result")


def test_every_decibel_shaped_step_is_an_index():
    up = run(doc([(30, 2, 200, True, 600, 0)]))
    for sid in ("construction.today", "construction.day_level", "construction.night_mix", "construction.early_mix",
                "construction.day_correction", "construction.level"):
        assert step(up, sid).unit == "index"


def test_today_is_not_mutated():
    t = dict(TODAY)
    C._use(doc([(30, 2, 200, True, 0, 0)]))
    C.upgrade(LAT, LNG, t, {})
    assert t == TODAY


# ---------------------------------------------------------------- never raises
def test_never_raises_on_odd_points_and_inputs():
    C._use(doc([(30, 2, 200, True, 600, 0)]))
    for lat, lng in [(40.77, -74.05),            # the Hudson River
                     (0.0, 0.0), (90.0, 180.0), (40.75, -73.98), (float("nan"), 1.0), (None, None), ("x", "y")]:
        up = C.upgrade(lat, lng, dict(TODAY), {})
        assert set(up.levels) == set(SLOTS)
        assert up.steps[-1].id == "construction.level"
    assert set(C.upgrade(LAT, LNG, {}, None).levels) == set(SLOTS)            # no levels at all
    assert set(C.upgrade(LAT, LNG, {"day": 50.0}, {}).levels) == set(SLOTS)   # slots missing


def test_river_and_empty_ground_return_todays_levels_with_a_sentence():
    for point in [(40.77, -74.05), (LAT, LNG)]:
        up = run(doc(), lat=point[0], lng=point[1])
        assert up.levels == TODAY
        assert len(up.evidence) == 1 and "No DOT street-work permits" in up.evidence[0]


def test_missing_artifact_is_a_passthrough():
    C._use(None)
    up = C.upgrade(LAT, LNG, dict(TODAY), {})
    assert up.levels == TODAY and up.steps[-1].id == "construction.level" and up.steps[-1].kind == "result"


def test_a_broken_artifact_is_a_passthrough():
    C._IDX, C._TRIED = object(), True   # something that is not an index
    up = C.upgrade(LAT, LNG, dict(TODAY), {})
    assert up.levels == TODAY


# ---------------------------------------------------------------- the day
def test_more_nearby_street_work_gives_a_higher_day_level():
    one = run(doc([(30, 2, 150, False, 0, 0)])).levels["day"]
    three = run(doc([(30, 2, 150, False, 0, 0), (40, 2, 150, False, 0, 0), (50, 1, 150, False, 0, 0)])).levels["day"]
    many = run(doc([(10 + 5 * i, 2, 150, False, 0, 0) for i in range(12)])).levels["day"]
    assert TODAY["day"] < one < three < many


def test_longer_and_heavier_work_counts_more_and_active_now_adds():
    short = run(doc([(30, 2, 20, False, 0, 0)])).levels["day"]
    long_ = run(doc([(30, 2, 300, False, 0, 0)])).levels["day"]
    light = run(doc([(30, 0, 300, False, 0, 0)])).levels["day"]
    live = run(doc([(30, 2, 300, True, 0, 0)])).levels["day"]
    assert short < long_ < live and light < long_


def test_distance_weight_falls_to_zero_at_100_m():
    near = run(doc([(10, 2, 200, False, 0, 0)])).levels["day"]
    mid = run(doc([(60, 2, 200, False, 0, 0)])).levels["day"]
    far = run(doc([(99, 2, 200, False, 0, 0)])).levels["day"]
    out = run(doc([(150, 2, 200, False, 0, 0)])).levels["day"]
    assert near > mid > far > TODAY["day"] and out == TODAY["day"]
    assert C._w_dist(0) == C._w_dist(C.NEAR_M) == 1.0 and C._w_dist(C.RADIUS_M) == 0.0


def test_the_lift_shrinks_where_today_is_already_near_its_ceiling():
    d = doc([(30, 2, 300, True, 0, 0)])
    low = run(d, {"night": 25.0, "early": 37.0, "day": 40.0}).levels["day"] - 40.0
    high = run(d, {"night": 50.0, "early": 62.0, "day": 65.0}).levels["day"] - 65.0
    assert low > high > 0
    assert high == pytest.approx(low * (1 - C.OVERLAP_DISCOUNT), rel=1e-3)


def test_street_work_without_night_hours_leaves_night_and_early_alone():
    up = run(doc([(30, 2, 300, True, 0, 0)]))
    assert up.levels["day"] > TODAY["day"]
    assert up.levels["night"] == TODAY["night"] and up.levels["early"] == TODAY["early"]


# ---------------------------------------------------------------- the night
def test_an_after_hours_variance_raises_night_and_scales_with_nights():
    none = run(doc()).levels["night"]
    few = run(doc(ahv=[(40, 10, 40, 0, 0)])).levels["night"]
    some = run(doc(ahv=[(40, 100, 400, 0, 0)])).levels["night"]
    most = run(doc(ahv=[(40, 300, 1500, 0, 0)])).levels["night"]
    assert none == TODAY["night"] < few < some < most
    assert run(doc(ahv=[(40, 100, 400, 0, 0)])).levels["day"] == TODAY["day"]   # a variance says nothing about the day


def test_a_variance_far_away_or_without_night_hours_does_nothing():
    assert run(doc(ahv=[(250, 300, 1500, 0, 0)])).levels == TODAY
    assert run(doc(ahv=[(40, 0, 0.0, 0, 0.0)])).levels == TODAY


def test_early_hours_raise_early_only():
    up = run(doc(ahv=[(40, 0, 0.0, 200, 300.0)]))
    assert up.levels["early"] > TODAY["early"] and up.levels["night"] == TODAY["night"]


def test_night_work_in_a_permit_text_raises_night():
    up = run(doc([(30, 2, 120, False, 120 * 6.0, 0)]))
    assert up.levels["night"] > TODAY["night"]
    assert step(up, "construction.street_night_sites").value == 1


def test_two_sources_of_night_work_combine_without_exceeding_the_working_level():
    a = run(doc(ahv=[(40, 150, 600, 0, 0)])).levels["night"]
    both = run(doc([(30, 2, 150, False, 150 * 6.0, 0)], [(40, 150, 600, 0, 0)])).levels
    assert both["night"] > a and both["night"] <= both["day"]


# ---------------------------------------------------------------- caps
def test_caps_hold():
    crowd = [(5 + (i % 40), 2, 365, True, 365 * 7.0, 365 * 2.0) for i in range(300)]
    ahv = [(10 + i, 365, 365 * 7.0, 365, 365 * 2.0) for i in range(30)]
    for today in (TODAY, {"night": 25.0, "early": 37.0, "day": 40.0}, {"night": 20.0, "early": 32.0, "day": 35.0}):
        up = run(doc(crowd, ahv), today)
        corr = step(up, "construction.day_correction").value
        assert 0.0 <= corr <= C.CAP_DAY_DB + 0.01
        assert up.levels["day"] <= today["day"] + C.CAP_DAY_DB + 0.01
        assert step(up, "construction.night_share").value <= C.P_MAX + 1e-9
        assert step(up, "construction.early_share").value <= C.P_MAX + 1e-9
        assert today["night"] <= up.levels["night"] <= up.levels["day"] + 1e-6
        assert today["early"] <= up.levels["early"] <= up.levels["day"] + 1e-6
        assert up.levels["day"] >= today["day"]


def test_no_upgrade_ever_lowers_a_level():
    for sites in ([], [(30, 2, 100, True, 0, 0)], [(80, 0, 5, False, 50, 5)]):
        up = run(doc(sites, [(50, 5, 20, 2, 3)]))
        assert all(up.levels[s] >= TODAY[s] - 1e-9 for s in SLOTS)


# ---------------------------------------------------------------- the snapshot expires
def test_active_flags_lapse_when_the_snapshot_is_old(monkeypatch):
    d = doc([(30, 2, 100, True, 0, 0)])                       # active on 2026-10-28, ends 20 days later
    fresh = run(d)
    assert step(fresh, "construction.street_active").value == 1
    monkeypatch.setattr(C, "_now", lambda: dt.date(2026, 12, 20))     # 53 days old, the permit has ended
    ended = run(d)
    assert step(ended, "construction.street_active").value == 0
    monkeypatch.setattr(C, "_now", lambda: dt.date(2027, 3, 1))       # past STALE_DAYS
    stale = run(d)
    snap = step(stale, "construction.snapshot").value
    assert "stale" in snap and "rebuild" in snap
    assert stale.levels["day"] < fresh.levels["day"]


def test_the_board_says_permits_are_a_snapshot():
    up = run(doc([(30, 2, 100, True, 0, 0)]))
    snap = step(up, "construction.snapshot")
    assert "2026-10-28" in snap.value and "snapshot" in snap.formula and "expire" in snap.formula


# ---------------------------------------------------------------- evidence
def test_evidence_is_renter_facing_counts_and_distances():
    up = run(doc([(40, 2, 200, True, 600, 0), (60, 1, 100, False, 0, 0)], [(70, 120, 500, 0, 0)]))
    assert 1 <= len(up.evidence) <= 3
    text = " ".join(up.evidence)
    assert "Con Ed street opening permit is active" in text and "40 m away" in text.replace("on a block ", "")
    assert "after-hours variance" in text and "120 nights" in text
    for bad in ("dB", "decibel", "index", "—", "–"):
        assert bad not in text


# ---------------------------------------------------------------- helpers
def test_permit_hours_parser():
    assert C._permit_hours("WORK 11PM-5AM NIGHTLY.") == (6.0, 0.0)
    n, e = C._permit_hours("WORK 11PM-7AM WEEKNIGHTS ONLY .. NO WORK FRIDAY SATURDAY AND SUNDAY NIGHTS")
    assert n == pytest.approx(6.0 * C.WEEKNIGHT_FACTOR) and e == pytest.approx(2.0 * C.WEEKNIGHT_FACTOR)
    assert C._permit_hours("WORK 7AM-6PM MONDAY TO FRIDAY") == (0.0, 0.0)          # ordinary hours are not after-hours
    assert C._permit_hours("NO WORK 11PM-5AM") == (0.0, 0.0)
    assert C._permit_hours("MAY WORK 8PM-6AM FOR DEP WATER SHUT DOWNS") == (0.0, 0.0)
    assert C._permit_hours("WORK 10PM-3PM MONDAY TO SUNDAY") == (0.0, 0.0)         # a typo, longer than 14 hours
    assert C._permit_hours("") == (0.0, 0.0) and C._permit_hours(None) == (0.0, 0.0)
    assert C._permit_hours("WORK 11:30PM-5AM NIGHTLY")[0] == 5.5


def test_street_names_normalise_to_the_centreline_style():
    assert C._norm("EAST   60 STREET") == "E 60 ST" == C._norm("E  60 ST")
    assert C._norm("AVENUE OF THE AMERICAS") == "6 AVE" == C._norm("6 AVENUE")
    assert C._norm("WEST 42ND STREET") == "W 42 ST"


def test_placing_a_permit_between_two_cross_streets():
    def row(name, pts):
        return {"the_geom": {"coordinates": [pts]}, "full_street_name": name, "l_low_hn": "1", "l_high_hn": "99",
                "r_low_hn": "2", "r_high_hn": "100"}
    cl = C._Centerline([row("W 10 ST", [[-74.000, 40.730], [-73.995, 40.730]]),
                        row("5 AVE", [[-74.000, 40.730], [-74.000, 40.735]]),
                        row("6 AVE", [[-73.995, 40.730], [-73.995, 40.735]])])
    g = C._place(cl, "WEST   10 STREET", "5 AVENUE", "6 AVENUE", None)
    assert g == (40.73, -74.0, 40.73, -73.995)
    point = C._place(cl, "WEST   10 STREET", "5 AVENUE", None, None)
    assert point[:2] == point[2:] == (40.73, -74.0)
    h = C._place(cl, "WEST   10 STREET", "5 AVENUE", "6 AVENUE", "50")
    assert h[:2] == h[2:] and -74.0 < h[1] < -73.995       # house number 50 sits partway along the block
    assert C._place(cl, "NO SUCH STREET", "5 AVENUE", None, None) is None
    assert C._place(cl, "WEST   10 STREET", "AMTRAK RR", None, None) is None


# ---------------------------------------------------------------- the built artifact
ART = Path(__file__).resolve().parent.parent / "noise_score" / "data" / "upgrades" / "construction.json.gz"
needs_artifact = pytest.mark.skipif(not ART.exists(), reason="construction.json.gz not built")


@needs_artifact
def test_built_artifact_is_small_manhattan_and_dated():
    assert ART.stat().st_size < 8 * 1024 * 1024
    d = load("construction")
    assert d["built"] and d["window_days"] == 365
    assert d["sources"]["street_permits"]["placed_share"] >= 0.9
    la = [x[0] for x in d["street"]["loc"]] + [x[0] for x in d["ahv"]]
    ln = [x[1] for x in d["street"]["loc"]] + [x[1] for x in d["ahv"]]
    assert 40.68 < min(la) and max(la) < 40.89   # Governors Island is in the borough and -74.03 < min(ln) and max(ln) < -73.90


@needs_artifact
def test_built_artifact_finds_midtown_work_and_is_fast():
    C._reset()
    C.upgrade(40.7580, -73.9855, dict(TODAY), {})              # load
    t = time.perf_counter()
    for _ in range(50):
        up = C.upgrade(40.7580, -73.9855, dict(TODAY), {})
    assert (time.perf_counter() - t) / 50 < 0.05
    assert step(up, "construction.street_sites").value > 0
    assert all(up.levels[s] >= TODAY[s] for s in SLOTS)
    river = C.upgrade(40.77, -74.05, dict(TODAY), {})
    assert river.levels == TODAY


def test_doc_exists_and_is_short():
    md = Path(__file__).resolve().parent.parent / "upgrades" / "construction.md"
    if not md.exists():
        pytest.skip("doc not written")
    text = md.read_text()
    assert len(text.splitlines()) < 80 and "—" not in text
