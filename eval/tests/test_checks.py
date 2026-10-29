"""Each check catches what it is for. No network, no services."""
import copy

from hush_eval import checks as C
from hush_eval import shapes as S

LISTING = {"text": "Apt 4B on the fourth floor of 2109 Broadway. Quiet block! The bedroom faces Broadway.",
           "photos": ["data:image/png;base64,AAAA"]}


def field(value, quote=None, source="text", what=None):
    if value is None:
        return {"value": None, "status": "cant_tell", "evidence": []}
    ev = {"source": "text", "quote": quote} if source == "text" else {"source": source, "what": what}
    return {"value": value, "status": "read", "evidence": [ev]}


def good_reader():
    return {
        "fields": {"address": field("2109 Broadway", "2109 Broadway"), "unit": field("4B", "Apt 4B"),
                   "floor": field(4, "on the fourth floor"), "side": field("front", "The bedroom faces Broadway")},
        "position": "front",
        "observed": {"view": field(None), "windows": field(None), "ac_units": field("yes", source="photo:0", what="a window unit"),
                     "wall_material": field(None)},
    }


def hard(problems):
    return [p for p in problems if p.hard]


def test_a_grounded_reader_passes():
    assert C.reader_grounding(good_reader(), LISTING) == []


def test_a_quote_that_is_not_in_the_listing_fails():
    r = good_reader()
    r["fields"]["floor"]["evidence"][0]["quote"] = "on the 4th floor"
    [p] = hard(C.reader_grounding(r, LISTING))
    assert p.where == "fields.floor" and "not in the listing" in p.message


def test_whitespace_and_curly_quotes_do_not_break_a_real_quote():
    r = good_reader()
    r["fields"]["floor"]["evidence"][0]["quote"] = "on the  fourth\nfloor"
    assert C.reader_grounding(r, LISTING) == []
    listing = dict(LISTING, text=LISTING["text"].replace("faces", "face’s"))
    r["fields"]["side"]["evidence"][0]["quote"] = "The bedroom face's Broadway"
    assert hard(C.reader_grounding(r, listing)) == []


def test_a_photo_that_does_not_exist_fails():
    r = good_reader()
    r["observed"]["ac_units"]["evidence"][0]["source"] = "photo:3"
    [p] = hard(C.reader_grounding(r, LISTING))
    assert "photo:3" in p.message and "1 photo" in p.message


def test_a_photo_citation_must_say_what_it_shows():
    r = good_reader()
    r["observed"]["ac_units"]["evidence"][0]["what"] = " "
    assert any("says nothing" in p.message for p in hard(C.reader_grounding(r, LISTING)))


def test_read_without_evidence_and_cant_tell_with_a_value_fail():
    r = good_reader()
    r["fields"]["unit"]["evidence"] = []
    r["fields"]["address"] = {"value": "2109 Broadway", "status": "cant_tell", "evidence": []}
    msgs = [p.message for p in hard(C.reader_grounding(r, LISTING))]
    assert "read with no evidence" in msgs and any("cant_tell with a value" in m for m in msgs)


def test_a_sales_adjective_is_not_evidence_for_the_side():
    r = good_reader()
    r["fields"]["side"] = field("rear", "Quiet block")
    r["position"] = "rear"
    [p] = hard(C.reader_grounding(r, LISTING))
    assert "sales adjective" in p.message


def test_position_must_agree_with_the_side_field():
    r = good_reader()
    r["position"] = "rear"
    assert any(p.where == "position" for p in hard(C.reader_grounding(r, LISTING)))
    r["fields"]["side"] = field(None)
    r["position"] = "unknown"
    assert hard(C.reader_grounding(r, LISTING)) == []


def test_values_stay_in_range():
    r = good_reader()
    r["fields"]["floor"]["value"] = 0
    r["fields"]["side"]["value"] = "north"
    msgs = " ".join(p.message for p in hard(C.reader_grounding(r, LISTING)))
    assert "floor 0" in msgs and "side 'north'" in msgs


def test_the_readers_spellings_pass():
    r = good_reader()
    r["fields"]["side"] = field("street", "The bedroom faces Broadway")
    r["fields"]["unit"] = {"value": None, "status": "cant_tell", "evidence": []}
    r["observed"]["windows"] = {"value": {"floor_to_ceiling": True, "operable": None}, "status": "read",
                                "evidence": [{"source": "photo:0", "what": "glass to the floor"}]}
    assert C.reader_grounding(r, LISTING) == []
    r["fields"]["side"] = {"value": "unknown", "status": "cant_tell", "evidence": []}   # the reader's cant_tell side
    r["position"] = "unknown"
    assert C.reader_grounding(r, LISTING) == []
    assert C.compare("windows", "floor_to_ceiling", {"floor_to_ceiling": True, "operable": None}) == C.CORRECT
    assert C.compare("view", "open", "water") == C.CORRECT and C.compare("wall_material", "drywall", "plaster") == C.CORRECT


def test_offsets_must_point_at_the_quote():
    r = good_reader()
    q = "on the fourth floor"
    start = LISTING["text"].index(q)
    r["fields"]["floor"]["evidence"][0].update(start=start, end=start + len(q))
    assert C.reader_grounding(r, LISTING) == []
    r["fields"]["floor"]["evidence"][0].update(start=start + 1, end=start + len(q) + 1)
    [p] = hard(C.reader_grounding(r, LISTING))
    assert "offsets" in p.message


def test_unknown_sources_and_statuses_fail():
    r = good_reader()
    r["fields"]["floor"]["evidence"][0] = {"source": "pluto", "what": "6 floors"}
    r["fields"]["unit"]["status"] = "guessed"
    msgs = " ".join(p.message for p in hard(C.reader_grounding(r, LISTING)))
    assert "unknown evidence source 'pluto'" in msgs and "status 'guessed'" in msgs


# ---------------------------------------------------------------- verdict
VERDICT = {"evidence": [{"id": "E1", "text": "Street: quieter than 41% of Manhattan apartments"},
                        {"id": "E2", "text": "Sirens: quieter than 12% of Manhattan apartments"}],
           "sentences": [{"text": "The street is quieter than 41% of Manhattan.", "cites": ["E1"]},
                         {"text": "Sirens are what you will hear.", "cites": ["E2"]}],
           "writer": "muse-spark-open"}


def test_a_cited_verdict_passes():
    assert C.verdict_citations(VERDICT) == []


def test_a_citation_to_a_missing_line_fails():
    v = copy.deepcopy(VERDICT)
    v["sentences"][1]["cites"] = ["E2", "E9"]
    [p] = hard(C.verdict_citations(v))
    assert "E9" in p.message and p.where == "sentences[1]"


def test_duplicate_ids_no_sentences_and_decibels_fail():
    v = copy.deepcopy(VERDICT)
    v["evidence"].append({"id": "E1", "text": "again"})
    v["sentences"][0]["text"] = "Expect 55 dB at night."
    msgs = " ".join(p.message for p in hard(C.verdict_citations(v)))
    assert "more than once" in msgs and "decibel" in msgs
    assert any("no sentences" in p.message for p in hard(C.verdict_citations({"evidence": [], "sentences": []})))


def test_uncited_sentences_and_stray_numbers_are_notes_not_failures():
    v = copy.deepcopy(VERDICT)
    v["sentences"].append({"text": "It is 30% louder than you think.", "cites": []})
    probs = C.verdict_citations(v)
    assert hard(probs) == []
    assert {p.message.split(":")[0] for p in probs} >= {"no citation"}
    assert any("30" in p.message for p in probs)


# ---------------------------------------------------------------- permit adjustments
ROWS = [{"work_permit": "M1-I1", "work_type": "General Construction", "job_description": "NEW BUILDING: erect 20 stories"},
        {"work_permit": "M2-I1", "work_type": "Plumbing", "job_description": "Replace sink"}]
CAPS = {"construction": 2.0}


def adj(size=1, cites=("M1-I1",), **extra):
    return {"adjustment": {"source": "construction", "direction": "louder", "size": size, "cap": 2, "cites": list(cites),
                           "reason": "x", **extra}}


def test_an_adjustment_within_cap_citing_pulled_rows_passes():
    assert C.adjustments(adj(2), ROWS, CAPS) == []
    assert C.adjustments({"adjustment": None, "why_none": "nothing moves"}, ROWS, CAPS) == []
    assert C.adjustments({"adjustments": [{"ingredient": "construction", "delta": -1, "cites": ["M2-I1"]}]}, ROWS, CAPS) == []


def test_over_cap_unpulled_rows_unknown_source_bad_direction_and_no_cites_fail():
    msgs = [p.message for p in C.adjustments(adj(3, ("M1-I1", "M9-I1"), direction="sideways"), ROWS, CAPS)]
    assert any("over its cap of 2" in m for m in msgs)
    assert any("M9-I1" in m and "not in the pull" in m for m in msgs)
    assert any("direction 'sideways'" in m for m in msgs)
    other = {"adjustment": {"source": "nightlife", "size": 1, "cites": []}}
    msgs = [p.message for p in C.adjustments(other, ROWS, CAPS)]
    assert "source 'nightlife' has no cap" in msgs and "cites no rows" in msgs


def test_a_permit_reading_must_quote_its_own_row():
    def reading(pid, quote):
        ev = [{"source": f"permit:{pid}", "quote": quote}]
        return {"id": pid, "kind": {"value": "new_building", "status": "read", "evidence": ev},
                "duration": {"value": None, "status": "cant_tell", "evidence": []}}
    ok = dict(adj(), readings=[reading("M1-I1", "new  building")])          # case and spaces are forgiven
    assert C.adjustments(ok, ROWS, CAPS) == []
    wrong_row = dict(adj(), readings=[reading("M2-I1", "NEW BUILDING")])   # a real quote, from another permit
    other = dict(adj(), readings=[reading("M7-I1", "NEW BUILDING")])
    assert "not in M2-I1's description" in C.adjustments(wrong_row, ROWS, CAPS)[0].message
    assert "not a permit in the pull" in C.adjustments(other, ROWS, CAPS)[0].message


def test_a_missing_adjustment_fails():
    assert C.adjustments({"adjust": []}, ROWS, CAPS)[0].message.startswith("the permit reader returned no")


# ---------------------------------------------------------------- extraction
def test_outcomes_count_cant_tell_apart_from_wrong():
    assert C.compare("floor", 4, 4) == C.CORRECT
    assert C.compare("floor", 4, 5) == C.WRONG
    assert C.compare("floor", 4, S.CANT_TELL) == C.ABSTAINED
    assert C.compare("floor", None, 3) == C.INVENTED
    assert C.compare("floor", None, S.CANT_TELL) == C.CORRECT


def test_top_floor_accepts_top_or_the_building_height():
    assert C.compare("floor", "top", 18, building_floors=18) == C.CORRECT
    assert C.compare("floor", "top", "top") == C.CORRECT
    assert C.compare("floor", "top", 17, building_floors=18) == C.WRONG


def test_aliases_map_before_comparing():
    assert C.compare("side", "front", "street") == C.CORRECT
    assert C.compare("side", "rear", "courtyard") == C.CORRECT
    assert C.compare("ac_units", "yes", True) == C.CORRECT
    assert C.compare("windows", "floor_to_ceiling", "floor-to-ceiling") == C.CORRECT


def test_addresses_compare_on_house_number_and_street():
    same = [("51 Saint Marks Place", "51 St. Mark's Pl, New York, NY 10003"),
            ("2109 Broadway", "2109 B'WAY"),
            ("1 Fifth Avenue", "1 5 Avenue"),
            ("437 East 12th Street", "437 E 12 St"),
            ("2109 Broadway", "2109 Broadway Apt 4B")]
    for gold, got in same:
        assert C.compare("address", gold, got) == C.CORRECT, (gold, got)
    assert C.compare("address", "437 East 12th Street", "437 West 12th Street") == C.WRONG


def test_tally_rates():
    rows = C.tally([{"floor": {"outcome": C.CORRECT, "gold": 3}}, {"floor": {"outcome": C.ABSTAINED, "gold": 4}},
                    {"floor": {"outcome": C.CORRECT, "gold": None}}, {"floor": {"outcome": C.INVENTED, "gold": None}}],
                   ["floor"])["floor"]
    assert rows["answerable"] == 2 and rows["accuracy"] == 0.5 and rows["wrong_rate"] == 0.25
