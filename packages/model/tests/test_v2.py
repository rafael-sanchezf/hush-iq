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


# ---------------------------------------------------------------- [V11] block bars
def test_block_bars_are_the_same_for_every_apartment_and_renter():
    """The block's number does not move with the floor, the side or the answers; the apartment's does."""
    runs = [v2.score(busy_inputs(), Unit(floor=f, position=p), a) for f, p, a in (
        (2, "front", v2.Answers()), (12, "rear", v2.Answers(sleep=(1, 9), day_bothers=False, ticks=["traffic"])),
        (None, "unknown", v2.Answers(ticks=["people"])))]
    blocks = [{i["name"]: i["block_quieter_than"] for i in r["ingredients"]} for r in runs]
    assert blocks[0] == blocks[1] == blocks[2]
    assert {i["name"]: i["quieter_than"] for i in runs[0]["ingredients"]} != {i["name"]: i["quieter_than"] for i in runs[1]["ingredients"]}
    assert all(0 <= v <= 100 for v in blocks[0].values())


def test_block_bars_rank_the_typical_apartment_over_the_whole_day():
    s = v2.uniform_slots()
    assert (round(24 * s["night"]), round(24 * s["early"]), round(24 * s["day"])) == (7, 3, 14)
    res = v2.score(busy_inputs(), Unit(floor=2, position="front"), v2.Answers())
    pl = busy_inputs()["pluto"]
    _, neutral = v2._neutral(busy_inputs())
    levels, _ = v2._upgraded(busy_inputs(), neutral, baseline.building_facts(pl))
    want = v2.block_ranks(levels, baseline.building_facts(pl))
    assert {i["name"]: i["block_quieter_than"] for i in res["ingredients"]} == {n: round(r, 1) for n, r in want.items()}


def test_nightlife_reads_local_businesses_and_keeps_its_key():
    res = v2.score(busy_inputs(), Unit(floor=2, position="front"), v2.Answers())
    night = next(i for i in res["ingredients"] if i["name"] == "nightlife")
    assert night["label"] == "Local businesses"


# ---------------------------------------------------------------- [V12] numbers behind each source, display only
from noise_score import upgrades as _upgrades  # noqa: E402
from noise_score.upgrades import sirens as _sirens  # noqa: E402

W57 = (40.76739, -73.983679)   # 315 West 57th Street


@pytest.mark.skipif(_upgrades.load("sirens") is None, reason="sirens artifact not built")
def test_siren_routes_give_trips_and_stations_in_numbers():
    r = _sirens.routes(*W57)
    assert r["covered"] is True and r["radius_m"] == 300
    near = r["nearest_street"]
    assert {"fire_per_day", "ambulance_per_day", "transport_per_day", "m", "name"} <= set(near)
    assert r["busiest_street"]["trips_per_day"] >= near["fire_per_day"] + near["ambulance_per_day"] + near["transport_per_day"] - 0.2
    assert set(r["nearest"]) == {"hospital", "firehouse", "police_station"} and all(v["m"] > 0 for v in r["nearest"].values())
    assert _sirens.routes(0.0, 0.0)["covered"] is False and _sirens.routes(float("nan"), 0.0) is None


@pytest.mark.skipif(_upgrades.load("sirens") is None, reason="sirens artifact not built")
def test_numbers_carry_counts_never_internal_levels():
    up = _sirens.upgrade(*W57, {"night": 50.0, "early": 50.0, "day": 52.0}, {})
    nums = v2.numbers_of(up)
    assert {"street_fire", "busiest_street", "hospital_m"} <= set(nums)
    assert all(n["unit"] != "index" for n in nums.values())
    assert nums["hospital_m"]["unit"] == "m" and nums["street_fire"]["kind"] == "new_input"
    assert v2.numbers_of(None) == {}


def test_every_ingredient_has_numbers_and_sirens_has_routes():
    res = v2.score(busy_inputs(), Unit(floor=3, position="front"), v2.Answers())
    assert all(isinstance(i["numbers"], dict) for i in res["ingredients"])
    assert "routes" in next(i for i in res["ingredients"] if i["name"] == "sirens")
