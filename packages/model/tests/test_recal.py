"""Engine v2 recalibration [V10]: today's numbers reproduce model.py, the research numbers move each source the way
the research says, and the floor-and-side rules. No network."""
import pytest

from noise_score import baseline, model, recal, v2
from noise_score import config_v2 as V

from test_model import LAT, LNG, base_inputs, complaint, facility, road, venue

U0 = model.Unit(floor=None, position="front")


def busy_inputs():
    """A block with something in every source, to check the copy against model.py."""
    roads = [road("BROADWAY", lanes="4", speed="30", snow="C"), road("W 1 ST", offset=0.0004),
             dict(road("FDR DR", rw="2", speed="45", offset=0.0003), trafdir="FT")]
    complaints = ([complaint("Noise - Vehicle", "Engine Idling", h) for h in (1, 2, 3, 9, 14)] * 20
                  + [complaint("Noise - Commercial", "Loud Music/Party", h) for h in (23, 0, 1, 15)] * 30
                  + [complaint("Noise", "Noise: Construction Before/After Hours (NM1)", 6)] * 12
                  + [complaint("Noise - Residential", "Loud Music/Party", 23, bbl="3000000001")] * 9)
    liquor = [venue("Club"), venue("Restaurant", 0.0002), venue("Hotel", 0.0005)]
    stations = [{"structure": "Elevated", "gtfs_latitude": str(LAT + 0.001), "gtfs_longitude": str(LNG),
                 "stop_name": "X", "daytime_routes": "1"}]
    permits = [{"work_type": "Foundation", "expired_date": "2027-01-01"}]
    facs = [facility("hospital"), facility("fire", "ENGINE 1", 0.003), facility("police", "PCT", 0.004)]
    return base_inputs(roads=roads, complaints=complaints, liquor=liquor, stations=stations, permits=permits,
                       facilities=facs, pluto={"yearbuilt": "1955", "numfloors": "6", "bldgclass": "D1",
                                               "unitsres": "40", "unitstotal": "42"})


@pytest.mark.parametrize("inputs", [base_inputs(), busy_inputs()], ids=["quiet", "busy"])
def test_todays_numbers_reproduce_the_frozen_model(inputs):
    then = recal.levels(inputs, recal.TODAY)
    frozen = baseline.neutral_levels(inputs)
    for n in recal.SOURCES:
        assert then[n] == pytest.approx(frozen[n], abs=1e-9), n


def test_street_complaints_stop_at_three():
    inp = busy_inputs()
    then, now = recal.street(inp, recal.TODAY), recal.street(inp, recal.NUMBERS)
    no311 = recal.street(dict(inp, complaints=[]), recal.NUMBERS)
    assert max(now[w] - no311[w] for w in model.WINDOWS) == pytest.approx(V.STREET_311_MAX_DB)
    assert now["night"] < then["night"]


def test_no_road_nearby_is_fifty():
    assert recal.street(base_inputs(), recal.NUMBERS)["day"] == pytest.approx(V.STREET_NONE_DB)


def test_a_restaurant_reads_eleven_quieter_and_the_complaint_bump_is_kept():
    one = base_inputs(liquor=[venue("Restaurant", 0.0)])
    assert recal.nightlife(one, recal.NUMBERS)["night"] == pytest.approx(47.0)
    assert recal.nightlife(one, recal.TODAY)["night"] == pytest.approx(58.0)
    party = base_inputs(complaints=[complaint("Noise - Commercial", "Loud Music/Party", h) for h in (1, 15)] * 200)
    now, quiet = recal.nightlife(party, recal.NUMBERS), recal.nightlife(base_inputs(), recal.NUMBERS)
    assert now["night"] - quiet["night"] == pytest.approx(12.0)       # decision U6: today's bump, every slot
    assert now["day"] - quiet["day"] == pytest.approx(12.0)


def test_building_era_is_split_by_code_year():
    def era(year):
        inp = base_inputs(pluto={"yearbuilt": str(year), "numfloors": "6", "bldgclass": "D1", "unitsres": "40"})
        return recal.building(inp, inp["pluto"], recal.NUMBERS)["night"]
    assert era(1950) - era(1990) == pytest.approx(2.0)
    assert era(1970) - era(1990) == pytest.approx(1.0)
    assert era(1990) == pytest.approx(era(2005))


def test_a_farther_station_fades_faster():
    near = base_inputs(facilities=[facility(dlat=0.0004)])           # under 50 m: no distance loss either way
    far = base_inputs(facilities=[facility(dlat=0.0036)])            # about 400 m
    assert recal.sirens(near, recal.NUMBERS) == pytest.approx(recal.sirens(near, recal.TODAY))
    assert recal.sirens(far, recal.TODAY)["day"] - recal.sirens(far, recal.NUMBERS)["day"] == pytest.approx(3.0, abs=0.1)


def test_construction_complaints_count_half():
    inp = base_inputs(complaints=[complaint("Noise", "Noise: Construction Before/After Hours (NM1)", 6)] * 30)
    then, now = recal.construction(inp, recal.TODAY), recal.construction(inp, recal.NUMBERS)
    assert now["day"] - 40 == pytest.approx((then["day"] - 40) / 2)


def test_the_board_gets_two_boxes_per_source():
    inp = busy_inputs()
    then, now = recal.levels(inp, recal.TODAY), recal.levels(inp)
    for n in recal.SOURCES:
        s = recal.steps(n, then[n], now[n], [f"{n}.today"])
        assert [x.id for x in s] == [f"{n}.as_built", f"{n}.recal"] and s[1].feeds == [f"{n}.today"]
        assert s[1].value == {w: round(now[n][w] - then[n][w], 2) for w in model.WINDOWS}


# ---------------------------------------------------------------- floor and side [V10]
def test_traffic_barely_drops_below_the_fifth_floor():
    walkup = {"floors": 6, "commercial": False}
    assert v2.position_db(walkup, model.Unit(floor=4, position="front"))["street"] == 0.0     # 10.9 m up
    assert v2.position_db(walkup, model.Unit(floor=5, position="front"))["street"] == pytest.approx(-0.26, abs=0.01)
    assert v2.position_db(walkup, model.Unit(floor=6, position="front"))["street"] == pytest.approx(-0.62, abs=0.01)
    tower = {"floors": 15, "commercial": False}
    assert v2.position_db(tower, model.Unit(floor=10, position="front"))["street"] == pytest.approx(-1.9, abs=0.05)
    high = {"floors": 70, "commercial": False}
    assert v2.position_db(high, model.Unit(floor=60, position="front"))["sirens"] == V.LINE_MAX_DB
    assert v2.position_db(walkup, model.Unit(floor=6, position="front"))["nightlife"] == -5.0  # point sources: -1 a floor
    assert v2.position_db(high, model.Unit(floor=60, position="front"))["construction"] == V.POINT_MAX_DB


def test_rear_is_ten_for_traffic_and_eight_for_the_rest():
    adj = v2.position_db({"floors": 6}, model.Unit(floor=1, position="rear"))
    assert adj["street"] == -10.0 and adj["nightlife"] == adj["sirens"] == adj["construction"] == -8.0
    unknown = v2.position_db({"floors": 6}, model.Unit(floor=1, position="unknown"))
    assert all(unknown[n] == V.UNKNOWN_SIDE_DB for n in ("street", "nightlife", "sirens", "construction"))


def test_neighbors_top_floor_four_and_no_bumps_low_down():
    shop = {"floors": 5, "commercial": True}
    assert v2.position_db(shop, model.Unit(floor=5, position="front"))["building"] == V.TOP_FLOOR_DB == -4.0
    assert v2.position_db(shop, model.Unit(floor=2, position="front"))["building"] == 0.0
    assert v2.position_db(shop, model.Unit(floor=1, position="front"))["building"] == 0.0
    assert v2.position_db(shop, model.Unit(floor=2, position="front"))["nightlife"] == pytest.approx(5.0 - 1.0)


def test_story_height_bands():
    assert v2.story_height(None) == V.STORY_HEIGHT_M
    assert (v2.story_height(5), v2.story_height(12), v2.story_height(40)) == (3.64, 3.44, 3.16)


# ---------------------------------------------------------------- the built sample, when it is on disk
@pytest.mark.skipif(not recal.SAMPLE.exists(), reason="recal_sample.json not built")
def test_built_sample_matches_the_baseline_and_these_numbers():
    import json
    doc = json.loads(recal.SAMPLE.read_text())
    assert len(doc["samples"]) == len(baseline.load()["samples"])
    assert doc["check"]["max_diff_vs_baseline_with_todays_numbers"] <= 0.01
    assert doc["numbers_sha"] == recal.numbers_sha()
