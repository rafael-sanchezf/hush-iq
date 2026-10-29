import pytest

from conftest import SCORES, load
from verdict import evidence
from verdict.evidence import DECIBEL


@pytest.mark.parametrize("name", list(SCORES))
def test_numbered_one_fact_per_line_and_no_decibels(lines, name):
    ls = lines(name)
    assert [l.id for l in ls] == [f"E{i}" for i in range(1, len(ls) + 1)]
    assert ls[0].kind == "verdict"
    for l in ls:
        assert not DECIBEL.search(l.text), l.text
        assert "LICENSEE" not in l.text          # licensee names never become evidence
        assert l.text.endswith(".")


def test_v2_ranks_weights_and_why(lines):
    ls = lines("claremont")
    ranks = {l.source: l for l in ls if l.kind == "rank"}
    weights = {l.source: l for l in ls if l.kind == "weight"}
    assert set(ranks) == set(weights) == set(evidence.SOURCES)
    assert ranks["sirens"].text == "Sirens: Very quiet, quieter than 89% of Manhattan apartments for sirens."
    assert weights["sirens"].text == ("Sirens weight: 43% of the verdict, counted three times because you said "
                                      "sirens bother you.")
    assert "scaled down because you ticked other sources" in weights["street"].text
    assert ls[0].text == "Verdict for you: Very quiet, quieter than 99% of Manhattan apartments."


def test_floor_and_side_read_from_the_listing_carry_the_quote(lines):
    ls = lines("claremont")
    floor = next(l for l in ls if l.kind == "floor")
    side = next(l for l in ls if l.kind == "side")
    assert floor.text == 'Floor 4 of 6, read from the listing: "4th floor, elevator building".'
    assert side.text == "Facing the rear, seen in photo 3: bedroom window onto a courtyard."
    assert any(l.kind == "unit" and "4C" in l.text for l in ls)


def test_silent_listing_gets_expected_floor_unknown_side_and_a_range(lines):
    ls = lines("ludlow")
    floor = next(l for l in ls if l.kind == "floor")
    side = next(l for l in ls if l.kind == "side")
    rng = [l for l in ls if l.kind == "range"]
    assert floor.data == {"floor": 4, "how": "expected"}
    assert "assumed" in floor.text and "5 floors" in floor.text
    assert side.data["side"] == "unknown"
    assert [l.data["case"] for l in rng] == ["loudest_case", "quietest_case"]
    assert rng[0].text == ("Loudest case for this listing: floor 2, the lowest apartment floor, facing the street: "
                           "Very loud, quieter than 0% of Manhattan apartments.")
    assert rng[1].text.startswith("Quietest case for this listing: floor 5, the top floor, at the rear: Loud")


def test_caps_name_the_source_and_whether_they_bit(lines):
    score = load("ludlow")
    caps = [l for l in lines("ludlow") if l.kind == "cap"]
    assert [c.source for c in caps] == ["nightlife"]   # the 5% cap, not both: it is the stricter one
    assert caps[0].text.startswith("Cap not needed: nightlife is in Manhattan's loudest 5%")
    score["verdict"], score["uncapped_verdict"] = "Loud", "Typical"
    score["caps"][0]["applied"] = True
    bit = [l for l in evidence.build(score) if l.kind == "cap"]
    assert bit[0].text == ("Cap: nightlife is in Manhattan's loudest 5%, which holds the verdict at Loud; "
                           "without the cap it would be Typical.")


def test_v1_fallback_has_the_verdict_and_details_but_no_ranks(lines):
    answers = {"sleep_from": 23, "sleep_until": 7, "day_bothers": True, "bothers": ["sirens"]}
    ls = lines("claremont_v1", answers)
    kinds = {l.kind for l in ls}
    assert ls[0].text == "Verdict for you: Very quiet, quieter than 95% of Manhattan apartments."
    assert "rank" not in kinds and "range" not in kinds
    assert any(l.text == "Sirens are weighted up because you said sirens bother you." for l in ls)
    assert any(l.kind == "hours" and "11 pm to 7 am" in l.text for l in ls)
    floor = next(l for l in ls if l.kind == "floor")
    assert floor.data["how"] == "listing"   # the reader read 4 and v1 scored 4


def test_listing_quotes_lose_any_sound_level(lines):
    fields = {"floor": {"value": 4, "status": "read",
                        "evidence": [{"source": "text", "quote": "new windows cut street noise by 30 dB, triple pane"}]}}
    ls = evidence.build(load("claremont"), None, fields)
    floor = next(l for l in ls if l.kind == "floor")
    assert "30 dB" not in floor.text and "[sound level removed]" in floor.text


@pytest.mark.parametrize("raw,expected", [
    ("CLAREMONT AVE: two lane, 2 travel lanes, 25 mph, bus or truck route, 36 m away",
     "Street: Claremont Ave, 36 m away, 2 travel lanes, 25 mph, a bus or truck route."),
    ("FDR DR: highway, 3 travel lanes, 40 mph, 55 m away", "Street: FDR Dr, 55 m away, a highway, 3 travel lanes, 40 mph."),
    ("Elevated subway (1) at 125 St, 120 m away", "Street: elevated subway (1) at the 125 St station, 120 m away."),
    ("nearest loud: SOMEONE'S NAME (bar), 152 LUDLOW STREET, 15 m", "Nightlife: a bar at 152 Ludlow Street, 15 m away."),
    ("ENGINE 37/LADDER 40 (firehouse), 415 WEST 125 STREET, 554 m",
     "Sirens: Engine 37/Ladder 40, a firehouse at 415 West 125 Street, 554 m away."),
    ("120 Claremont Avenue: Structural to 2026-12-31",
     "Construction: a structural permit at 120 Claremont Avenue, open until December 31, 2026."),
    ("2 construction noise complaints within 100 m in 24 months (noise: construction equipment (nc1) 2)",
     "Construction: 2 construction noise complaints to 311 within 100 m in 24 months (construction equipment 2)."),
    ("built 1900: pre-war walk-up, wood joists and plaster carry footsteps",
     "Neighbors: built 1900, a pre-war walk-up, where wood joists and plaster carry footsteps."),
])
def test_engine_evidence_reads_as_plain_lines(raw, expected):
    source = {"Street": "street", "Nightlife": "nightlife", "Sirens": "sirens", "Construction": "construction",
              "Neighbors": "building"}[expected.split(":")[0]]
    assert evidence.detail(source, raw)[0] == expected


def test_a_score_that_is_neither_engine_is_refused():
    with pytest.raises(evidence.EvidenceError):
        evidence.build({"verdict": "Quiet"})
    with pytest.raises(evidence.EvidenceError):
        evidence.build("not a score")
