"""[HIQ-133] The upgraded Manhattan sample must match the upgrade code on disk. When it does not, engine v2 scores
every address on today's levels instead, renter and sample alike, so nothing else fails: this test does."""
from noise_score import v2
from noise_score.upgrades import apply as A

from test_baseline import busy_inputs


def test_the_upgraded_sample_matches_the_code_on_disk():
    built = [n for n in A.SOURCES if (A.DATA / f"{n}.json.gz").exists()]
    if not built:
        return   # a checkout without the artifacts scores on today's levels by design
    A._ready = None
    assert A.ready() is not None, (
        "manhattan_upgraded.json was built with other upgrade code, artifacts or research numbers, so /v2/score has "
        f"silently dropped its upgrades. Rebuild it: {A.REBUILD}, then commit the JSON with the change.")


def test_the_response_says_which_sources_are_upgraded():
    data = v2.score(busy_inputs())["engine_data"]
    if A.ready() is None:
        assert data == {"recalibrated": False, "upgraded": []}
    else:
        assert data["recalibrated"] is True and set(data["upgraded"]) <= set(A.SOURCES)


def test_a_renter_scored_weeks_later_matches_the_stored_sample(monkeypatch):
    """[HIQ-139] Construction counted the permits active on the day it ran. Every sample building, scored as a
    renter on Dec 1, must get exactly its stored levels, or renters drift away from the sample they are ranked on."""
    import datetime as dt

    from noise_score import baseline, recal
    from noise_score.upgrades import construction as C

    doc = A.ready()
    if doc is None:
        return   # no upgraded sample: today's levels for everyone, nothing to drift
    C._reset()   # the real artifact, not a test's stand-in
    monkeypatch.setattr(C, "_now", lambda: dt.date(2026, 12, 1))
    stored = {r["bbl"]: r["levels"] for r in doc["samples"]}
    start = recal.sample()
    for s in baseline.load()["samples"]:
        levels, _ = A.apply(s["lat"], s["lng"], start[s["bbl"]], s)
        for n in A.SOURCES:
            for slot, v in levels[n].items():
                assert abs(v - stored[s["bbl"]][n][slot]) < 1e-3, (s["bbl"], n, slot)
    C._reset()
