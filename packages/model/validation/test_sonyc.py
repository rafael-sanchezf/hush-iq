"""Offline checks for the SONYC harness: no network, no annotation file."""
import random

from validation import sonyc


def clip(hour, gt=None, vol=()):
    cols = {c for cs in sonyc.TAGS.values() for c in cs}
    zero = {c: 0 for c in cols}
    mk = lambda hits: {**zero, **{h: 1 for h in hits}}
    return {"loc": (547, 40.72951, -73.99425), "sensor": 1, "hour": hour, "year": 2018, "split": "train",
            "gt": None if gt is None else mk(gt), "vol": [mk(v) for v in vol]}


def test_spearman_known_values():
    assert sonyc.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert sonyc.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert sonyc.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None      # a constant side is undefined
    assert sonyc.spearman([1, 2], [1, 2]) is None                  # too few points
    # ties use average ranks: ranks x = 1,2.5,2.5,4 and y = 1,2,3,4
    assert abs(sonyc.spearman([1, 2, 2, 3], [1, 2, 3, 4]) - 0.94868) < 1e-4


def test_majority_needs_two_of_three_and_verified_wins():
    col = "1_engine_presence"
    assert sonyc.present(clip(9, vol=[[col], [col], []]), col, "majority")
    assert not sonyc.present(clip(9, vol=[[col], [], []]), col, "majority")
    assert sonyc.present(clip(9, vol=[[col], [], []]), col, "any")
    assert not sonyc.present(clip(9, gt=[], vol=[[col], [col], [col]]), col, "majority")   # verified says absent
    assert sonyc.present(clip(9, gt=[col], vol=[[], [], []]), col, "any")                  # verified says present


def test_mapping_and_slots():
    c = clip(23, vol=[["6_music_presence"], ["6_music_presence"], []])
    assert sonyc.source_present(c, "nightlife", "majority") and not sonyc.source_present(c, "street", "majority")
    sirens = clip(3, vol=[["5-3_siren_presence"]] * 3)
    assert sonyc.source_present(sirens, "sirens", "majority")
    # the hour decides the slot: 22 to 5 night, 5 to 8 early, 8 to 22 day
    assert [sonyc.model.window_of(h) for h in (22, 4, 5, 7, 8, 21)] == ["night", "night", "early", "early", "day", "day"]


def test_aggregate_shares():
    clips = {f"a{i}": clip(10, vol=[["1_engine_presence"]] * 3 if i < 3 else [[], [], []]) for i in range(4)}
    clips["n0"] = clip(1)
    (loc,) = sonyc.aggregate(clips)
    assert loc["clips"] == {"night": 1, "early": 0, "day": 4}
    assert loc["shares"]["majority"]["street"]["day"] == 0.75
    assert loc["shares"]["majority"]["street"]["early"] is None


def test_bootstrap_is_seeded_and_brackets_a_clear_signal():
    x = list(range(30))
    y = [v + random.Random(1).random() for v in x]
    draws, _ = sonyc.bootstrap({"today": x}, y, [i // 2 for i in x], 300, random.Random("s"))
    again, _ = sonyc.bootstrap({"today": x}, y, [i // 2 for i in x], 300, random.Random("s"))
    assert draws == again
    lo, hi = sonyc._interval(draws["loc"]["today"])
    assert 0.9 < lo <= hi <= 1.0
