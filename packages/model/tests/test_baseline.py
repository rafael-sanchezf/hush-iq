"""The Manhattan baseline [M12]: the decomposition it relies on, the sampler and the rank. No network."""
import itertools

from noise_score import baseline, model
from noise_score.model import Profile, Unit

from test_model import base_inputs, complaint, facility, road, venue


def busy_inputs():
    pl = {"yearbuilt": "1925", "numfloors": "6", "bldgclass": "C1", "unitsres": "20", "unitstotal": "22", "landuse": "4"}
    return base_inputs(
        pluto=pl,
        roads=[road("BROADWAY", lanes="4", speed="30")],
        liquor=[venue("Club"), venue("Restaurant", dlat=0.0006)],
        complaints=[complaint("Noise - Residential", "Loud Music/Party", h) for h in (1, 2, 23, 14)]
        + [complaint("Noise - Commercial", "Loud Music/Party", 1, bbl="3000000002", dlat=0.0004)],
        facilities=[facility("fire")],
    )


def test_neutral_levels_plus_position_reproduce_the_full_model():
    inp = busy_inputs()
    neutral = baseline.neutral_levels(inp)
    facts = baseline.building_facts(inp["pluto"])
    profiles = [None, Profile("light", True, ["sirens", "neighbors"]), Profile("heavy", False, ["traffic", "people"])]
    for floor, pos, prof in itertools.product([None, 1, 2, 3, 6], ["front", "rear", "unknown"], profiles):
        unit = Unit(floor, pos)
        full = model.score(inp, unit, prof)["internal_level"]
        got = baseline.level_for(neutral, facts, unit, prof, cap_floor=False)
        assert abs(got - full) <= 0.051, (floor, pos, prof, got, full)


def test_floor_is_capped_at_the_sampled_buildings_height():
    inp = busy_inputs()
    neutral, facts = baseline.neutral_levels(inp), baseline.building_facts(inp["pluto"])
    high = baseline.level_for(neutral, facts, Unit(30, "front"), None)
    top = baseline.level_for(neutral, facts, Unit(6, "front"), None)
    assert abs(high - top) < 1e-9


def lot(bbl, cd, units):
    return {"bbl": f"{bbl}.00000000", "cd": cd, "unitsres": str(units)}


def test_draw_allocates_by_units_and_weights_big_buildings():
    lots = [lot(1000010001 + i, "101", 10) for i in range(50)] + [lot(1000020001, "102", 1500)]
    picked = baseline.draw(lots, 4, seed=7)
    assert sum(h for _, h in picked) == 4
    big = [h for l, h in picked if l["cd"] == "102"]
    # cd 102 holds 1500 of 2000 units: 3 of the 4 points, all on the one building
    assert big == [3]


def test_rank_orders_quieter_and_louder_apartments():
    quiet = {"bbl": "1", "weight": 1, "floors": 5, "commercial": False,
             "levels": {n: {w: 45.0 for w in model.WINDOWS} for n in baseline.INGREDIENTS}}
    loud = {**quiet, "bbl": "2", "levels": {n: {w: 65.0 for w in model.WINDOWS} for n in baseline.INGREDIENTS}}
    doc = {"samples": [quiet, loud, loud, loud], "universe": {"units": 4}, "as_of": "2026-10-22"}
    mid = baseline.level_for(quiet["levels"], quiet, Unit(), None) + 5
    r = baseline.rank(mid, Unit(), None, baseline=doc)
    assert r["quieter_than"] == 75.0 and r["n"] == 4
    assert r["median_score"] == model.to_score(baseline.level_for(loud["levels"], loud, Unit(), None))
