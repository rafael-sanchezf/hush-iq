"""Pure model tests on synthetic inputs. No network."""
import copy

from noise_score import config as C
from noise_score import model
from noise_score.model import Profile, Unit

LAT, LNG = 40.7187, -73.9571


def base_inputs(**over):
    d = {
        "address": {"label": "TEST", "lat": LAT, "lng": LNG, "bbl": "3000000001", "bin": "3000001", "borough": "Brooklyn"},
        "as_of": "2026-10-21", "lookback_months": 24, "since": "2024-10-26",
        "pluto": {"yearbuilt": "1910", "numfloors": "4", "bldgclass": "C4", "unitsres": "8", "unitstotal": "9"},
        "complaints": [], "liquor": [], "roads": [], "stations": [], "permits": [], "facilities": [], "sources": [],
    }
    d.update(over)
    return d


def road(name="MAIN ST", lanes="2", speed="25", snow="S", rw="1", offset=0.0002):
    # a segment running east-west, `offset` degrees north of the point (~22 m per 0.0002)
    return {"full_street_name": name, "rw_type": rw, "number_travel_lanes": lanes, "posted_speed": speed,
            "snow_priority": snow, "trafdir": "TW",
            "the_geom": {"type": "MultiLineString", "coordinates": [[[LNG - 0.002, LAT + offset], [LNG + 0.002, LAT + offset]]]}}


def complaint(ctype, desc, hour, bbl="3000000001", dlat=0.0):
    return {"complaint_type": ctype, "descriptor": desc, "created_date": f"2025-06-01T{hour:02d}:30:00.000",
            "latitude": str(LAT + dlat), "longitude": str(LNG), "bbl": bbl}


def venue(desc="Club", dlat=0.0003):
    return {"legalname": "X", "description": desc, "actualaddressofpremises": "1 X ST",
            "georeference": {"type": "Point", "coordinates": [LNG, LAT + dlat]}}


def facility(kind="hospital", name="ST X HOSPITAL", dlat=0.0009):
    # 0.0009 degrees of latitude is about 100 m
    return {"name": name, "kind": kind, "address": "1 X ST", "latitude": LAT + dlat, "longitude": LNG}


def test_energy_sum_is_dominated_by_the_loud_source():
    assert abs(model.energy_sum([60, 60]) - 63.01) < 0.01
    assert model.energy_sum([70, 40]) < 70.1


def test_scale_direction():
    assert model.to_score(C.SCALE_QUIET_DB) == 100
    assert model.to_score(C.SCALE_QUIET_DB + 100 / C.SCALE_SLOPE) == 0
    assert model.to_score(C.SCALE_QUIET_DB + 50 / C.SCALE_SLOPE) == 50


def test_window_of_wraps_midnight():
    assert model.window_of(23) == "night" and model.window_of(2) == "night"
    assert model.window_of(6) == "early" and model.window_of(12) == "day"


def test_quiet_block_scores_high():
    res = model.score(base_inputs(), Unit(floor=3))
    assert res["score"] >= 70
    assert res["by_time"]["night"] >= res["by_time"]["day"] - 5


def test_arterial_is_louder_than_side_street_and_higher_floors_help():
    quiet = model.score(base_inputs(roads=[road(lanes="1")]), Unit(floor=2, position="front"))
    loud = model.score(base_inputs(roads=[road(name="BIG AVE", lanes="3", speed="30", snow="C")]), Unit(floor=2, position="front"))
    assert loud["score"] < quiet["score"]
    high = model.score(base_inputs(roads=[road(name="BIG AVE", lanes="3", speed="30", snow="C")]), Unit(floor=9, position="front"))
    rear = model.score(base_inputs(roads=[road(name="BIG AVE", lanes="3", speed="30", snow="C")]), Unit(floor=2, position="rear"))
    assert high["score"] > loud["score"]
    assert rear["score"] > loud["score"]


def test_same_street_segments_do_not_double_count():
    one = model.score(base_inputs(roads=[road()]), Unit(floor=2))
    two = model.score(base_inputs(roads=[road(), road(offset=0.0003)]), Unit(floor=2))
    assert one["score"] == two["score"]


def test_building_complaints_lower_the_score_and_top_floor_helps():
    rows = [complaint("Noise - Residential", "Banging/Pounding", h) for h in (23, 0, 1, 2, 22, 23, 1, 0, 14, 15)]
    noisy = model.score(base_inputs(complaints=rows), Unit(floor=2))
    calm = model.score(base_inputs(), Unit(floor=2))
    assert noisy["score"] < calm["score"]
    b = next(i for i in noisy["ingredients"] if i["name"] == "building")
    assert b["complaints"] == 10 and b["rate_vs_borough"] > 1
    assert b["levels"]["night"] > b["levels"]["day"]
    top = model.score(base_inputs(complaints=rows), Unit(floor=4))
    assert top["unit"]["top_floor"] and top["score"] > noisy["score"]


def test_other_buildings_complaints_do_not_count_as_this_building():
    rows = [complaint("Noise - Residential", "Loud Music/Party", 23, bbl="3000000002") for _ in range(10)]
    res = model.score(base_inputs(complaints=rows), Unit(floor=2))
    b = next(i for i in res["ingredients"] if i["name"] == "building")
    assert b["complaints"] == 0


def test_nightlife_is_a_night_problem_and_party_complaints_are_not_street():
    rows = [complaint("Noise - Street/Sidewalk", "Loud Music/Party", 1) for _ in range(12)]
    res = model.score(base_inputs(liquor=[venue(), venue("Restaurant")], complaints=rows), Unit(floor=2, position="front"))
    n = next(i for i in res["ingredients"] if i["name"] == "nightlife")
    s = next(i for i in res["ingredients"] if i["name"] == "street")
    assert n["levels"]["night"] > n["levels"]["day"]
    assert res["by_time"]["night"] < res["by_time"]["day"]
    assert not any("vehicle" in e for e in s["evidence"])


def test_construction_is_temporary_and_quiet_at_night():
    rows = [complaint("Noise", "Noise: Jack Hammering (NC2)", 10) for _ in range(6)]
    permits = [{"work_type": "Full Demolition", "expired_date": "2027-01-01T00:00:00.000", "house_no": "1", "street_name": "X ST"}]
    res = model.score(base_inputs(complaints=rows, permits=permits), Unit(floor=2))
    c = next(i for i in res["ingredients"] if i["name"] == "construction")
    assert c["temporary"] and c["levels"]["day"] > c["levels"]["night"]
    expired = copy.deepcopy(permits); expired[0]["expired_date"] = "2025-01-01T00:00:00.000"
    res2 = model.score(base_inputs(complaints=rows, permits=expired), Unit(floor=2))
    c2 = next(i for i in res2["ingredients"] if i["name"] == "construction")
    assert c2["levels"]["day"] < c["levels"]["day"]


def test_sirens_hospital_at_100m_and_none_within_radius():
    res = model.score(base_inputs(facilities=[facility()]), Unit(floor=1, position="front"))
    s = next(i for i in res["ingredients"] if i["name"] == "sirens")
    assert abs(s["raw_level"] - 60.0) < 0.1          # 64 - 4 dB per doubling from 50 m to 100 m
    assert s["levels"]["day"] == s["raw_level"] and s["levels"]["night"] == s["raw_level"] - 3
    assert s["evidence"][0] == "1 emergency facilities within 600 m: 1 hospital"
    assert s["evidence"][1].startswith("ST X HOSPITAL (hospital), 1 X ST, ") and s["evidence"][1].endswith(" m")
    assert not s["temporary"]
    none = model.score(base_inputs(), Unit(floor=1, position="front"))
    s0 = next(i for i in none["ingredients"] if i["name"] == "sirens")
    assert s0["raw_level"] == C.SIRENS_NONE_DB
    assert s0["evidence"] == ["no hospital, firehouse or police station within 600 m"]
    assert res["score"] < none["score"]


def test_sirens_sum_counts_kinds_and_stays_out_of_street_only():
    facs = [facility(), facility("fire", "ENGINE 1", 0.002), facility("fire", "EMS 2", 0.003), facility("police", "PCT 3", 0.004),
            facility("fire", "FAR AWAY", 0.02)]   # 2.2 km, outside the radius
    inp = base_inputs(facilities=facs)
    res = model.score(inp, Unit(floor=2, position="front"), Profile(sleep="light", bothers=["sirens"]))
    s = next(i for i in res["ingredients"] if i["name"] == "sirens")
    assert s["evidence"][0] == "4 emergency facilities within 600 m: 1 hospital, 2 firehouses, 1 police station"
    assert len(s["evidence"]) == 4 and s["weighted_up"]
    assert [i["name"] for i in res["ingredients"]] == ["street", "nightlife", "building", "sirens", "construction"]
    assert res["street_only_score"] == model.score(base_inputs(), Unit(floor=2, position="front"))["street_only_score"]
    rear = model.score(inp, Unit(floor=9, position="rear"))
    assert rear["score"] > model.score(inp, Unit(floor=2, position="front"))["score"]


def test_profile_changes_the_number_not_the_ingredients():
    # a nightlife block: the club is the loud source, so a light sleeper who names people must score lower
    inp = base_inputs(liquor=[venue(), venue("Additional Bar", 0.0004)])
    plain = model.score(inp, Unit(floor=2, position="front"))
    light = model.score(inp, Unit(floor=2, position="front"), Profile(sleep="light", bothers=["people"]))
    heavy = model.score(inp, Unit(floor=2, position="front"), Profile(sleep="heavy"))
    assert light["score"] < plain["score"] < heavy["score"]
    assert light["ingredients"][1]["weighted_up"] and not plain["ingredients"][1]["weighted_up"]


def test_street_only_ignores_floor():
    inp = base_inputs(roads=[road(name="BIG AVE", lanes="3", snow="C")])
    a = model.score(inp, Unit(floor=1, position="front"))
    b = model.score(inp, Unit(floor=10, position="rear"))
    assert a["street_only_score"] == b["street_only_score"]
    assert a["score"] < b["score"]
