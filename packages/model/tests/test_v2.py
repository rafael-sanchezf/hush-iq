"""Engine v2 [V1 to V8]: ranks against a fixed Manhattan, weights from the answers, caps. No network."""
import json

import pytest

from noise_score import baseline, model, v2
from noise_score.model import Unit

from test_baseline import busy_inputs

SAMPLES = baseline.load()["samples"]


def test_default_hours_weigh_night_most():
    s = v2.slot_weights(v2.Answers())
    assert round(s["night"], 3) == 0.475 and round(s["early"], 3) == 0.175 and round(s["day"], 3) == 0.35


def test_late_sleeper_moves_weight_into_the_morning():
    early = v2.slot_weights(v2.Answers(sleep=(23, 7)))
    late = v2.slot_weights(v2.Answers(sleep=(2, 10)))
    assert late["day"] > early["day"] and late["night"] < early["night"]


def test_not_bothered_by_day_shrinks_the_day():
    assert v2.slot_weights(v2.Answers(day_bothers=False))["day"] < v2.slot_weights(v2.Answers())["day"]


def test_a_tick_triples_a_source_and_weights_sum_to_one():
    w, ticked = v2.source_weights(v2.Answers(ticks=["traffic"]))
    assert ticked == {"street"}
    assert abs(sum(w.values()) - 1) < 1e-9
    assert abs(w["street"] - 96 / 164) < 1e-9


def test_expected_floor_skips_a_commercial_ground_floor():
    assert v2.expected_floor({"floors": 6, "commercial": False}) == 4
    assert v2.expected_floor({"floors": 6, "commercial": True}) == 4
    assert v2.expected_floor({"floors": 5, "commercial": True}) == 4
    assert v2.expected_floor({"floors": None}) is None


def test_higher_and_rear_never_ranks_louder():
    """The v1 rank moved every sample to the renter's unit, so a quieter unit could rank worse. v2 must not."""
    for s in SAMPLES:
        low, top = v2.residential_floors(s)
        if not low or top < 3:
            continue
        loud = v2.score_levels(s["levels"], s, Unit(floor=low, position="front"))
        quiet = v2.score_levels(s["levels"], s, Unit(floor=top, position="rear"))
        assert quiet["quieter_than"] >= loud["quieter_than"] - 1e-9


def test_one_terrible_source_is_not_outvoted():
    """[V6] Any source in Manhattan's loudest 5% keeps the verdict at Loud or louder."""
    for s in SAMPLES:
        res = v2.score_levels(s["levels"], s, v2.typical_unit(s))
        if min(res["ranks"].values()) <= 5:
            assert res["verdict"] in ("Very loud", "Loud")


def test_a_ticked_loud_source_caps_at_typical():
    for s in SAMPLES:
        res = v2.score_levels(s["levels"], s, v2.typical_unit(s), v2.Answers(ticks=["traffic"]))
        if res["ranks"]["street"] <= 10:
            assert res["verdict"] in ("Very loud", "Loud", "Typical")
            assert any(c["source"] == "street" for c in res["caps"]) or res["uncapped_verdict"] == res["verdict"]


def test_silent_listing_gets_a_range_and_a_known_one_does_not():
    s = next(s for s in SAMPLES if (s.get("floors") or 0) >= 5)
    silent = v2.score_levels(s["levels"], s, Unit())
    assert silent["unit"]["floor_from"] == "expected" and silent["range"] is not None
    assert silent["range"]["quietest_case"]["quieter_than"] >= silent["range"]["loudest_case"]["quieter_than"]
    known = v2.score_levels(s["levels"], s, Unit(floor=3, position="rear"))
    assert known["range"] is None


def test_floor_above_the_roof_is_capped():
    s = next(s for s in SAMPLES if (s.get("floors") or 0) == 6)
    assert v2.score_levels(s["levels"], s, Unit(floor=40, position="rear"))["unit"]["floor"] == 6


@pytest.mark.parametrize("answers", [v2.Answers(), v2.Answers(sleep=(1, 9), day_bothers=False, ticks=["neighbors", "sirens"])])
def test_no_decibels_leave_the_engine(answers):
    """[V8] Every number in the response is a rank, a weight, a floor or a count."""
    res = v2.score(busy_inputs(), Unit(floor=3, position="front"), answers)
    text = json.dumps(res).lower()
    for banned in ('"level', "_db", "db\"", "internal_level", "decibel"):
        assert banned not in text, banned
    assert res["verdict"] in baseline.VERDICTS
    assert {i["name"] for i in res["ingredients"]} == set(baseline.INGREDIENTS)
