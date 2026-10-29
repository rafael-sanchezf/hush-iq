"""The agent loop in mock mode: the five cases of HIQ-13 to HIQ-15, plus the ways a run can go wrong."""
import json

from conftest import CANT, Scripted, fixture_text, listing, read
from reader import loop, mock

FIELDS_01 = {
    "address": read("315 West 86th Street", "315 West 86th Street"),
    "unit": read("11C", "Apartment 11C"),
    "floor": read(11, "The unit is on the eleventh floor"),
    "side": read("rear", "face the rear of the building"),
}


def outputs_seen(body):
    """The tool results the model was sent, parsed."""
    return [json.loads(i["output"]) for i in body["input"] if isinstance(i, dict) and i.get("type") == "function_call_output"]


def test_floor_and_side_stated_in_the_text(scorer):
    model = Scripted([("submit_listing", {"fields": FIELDS_01})])
    text = fixture_text("01-stated-rear.txt")
    result = loop.read(listing(text), client=model.client, scorer=scorer, turns=8)

    assert result["status"] == "complete" and result["stopped"] == "submitted"
    f = result["fields"]
    assert (f["address"]["value"], f["unit"]["value"], f["floor"]["value"], f["side"]["value"]) == \
        ("315 West 86th Street", "11C", 11, "rear")
    assert result["position"] == "rear"
    for ev in (e for field in f.values() for e in field["evidence"]):
        assert text[ev["start"]:ev["end"]] == ev["quote"]           # offsets point at the quote in the text sent
    assert scorer.scored == [{"address": "315 WEST 86TH STREET, New York, NY, USA", "floor": 11, "position": "rear",
                              "answers": {"sleep_from": 23, "sleep_until": 7, "day_bothers": True, "bothers": []}}]
    assert [(t["by"], t["tool"]) for t in result["trace"]] == [("model", "submit_listing"), ("code", "locate"),
                                                               ("code", "score")]
    first = result["trace"][0]
    assert first["args"]["fields"]["floor"]["value"] == 11 and first["ok"] and isinstance(first["ms"], int)
    assert result["score"]["verdict"] == "Typical" and result["score_engine"] == "v2"
    assert result["turns"] == {"used": 1, "budget": 8} and result["mode"] == "live"


def test_a_silent_listing_scores_with_a_range(scorer):
    model = Scripted([("submit_listing", {"fields": {
        "address": read("201 East 87th Street", "201 East 87th Street"),
        "unit": CANT, "floor": CANT, "side": CANT}})])
    result = loop.read(listing(fixture_text("02-silent.txt")), client=model.client, scorer=scorer)

    assert result["status"] == "complete"
    assert result["fields"]["floor"] == {"value": None, "status": "cant_tell", "evidence": []}
    assert result["fields"]["side"] == {"value": "unknown", "status": "cant_tell", "evidence": []}
    assert result["position"] == "unknown"
    assert scorer.scored[0]["floor"] is None and scorer.scored[0]["position"] == "unknown"
    assert result["score"]["range"]["loudest_case"]["verdict"] == "Loud"


def test_adjectives_are_refused_as_evidence(scorer):
    fields = {"address": read("201 East 87th Street", "201 East 87th Street"), "unit": CANT, "floor": CANT,
              "side": read("rear", "A peaceful, serene home")}
    model = Scripted([("submit_listing", {"fields": fields}),
                      ("submit_listing", {"fields": dict(fields, side=CANT)})])
    result = loop.read(listing(fixture_text("02-silent.txt")), client=model.client, scorer=scorer)

    refusal = result["trace"][0]["result"]
    assert not result["trace"][0]["ok"]
    assert "adjectives are not evidence (peaceful, serene)" in refusal["refused"]["side"]
    assert result["status"] == "complete" and result["position"] == "unknown"


def test_an_invented_quote_is_refused_then_retried_within_budget(scorer):
    invented = dict(FIELDS_01, floor=read(11, "Bright 11th floor rear unit, very quiet"))
    model = Scripted([("submit_listing", {"fields": invented}), ("submit_listing", {"fields": FIELDS_01})])
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), client=model.client, scorer=scorer, turns=4)

    refused, accepted = result["trace"][0], result["trace"][1]
    assert refused["tool"] == "submit_listing" and not refused["ok"]
    assert list(refused["result"]["refused"]) == ["floor"]
    assert "quote not found in the listing text" in refused["result"]["refused"]["floor"]
    assert set(refused["result"]["accepted"]) >= {"address", "unit", "side"}
    assert "floor" in outputs_seen(model.agent_requests[1])[0]["refused"]     # the model was told why
    assert accepted["ok"] and accepted["result"]["status"] == "accepted"
    assert result["status"] == "complete" and result["fields"]["floor"]["value"] == 11
    assert result["turns"]["used"] == 2


PHOTOS = {
    0: {"fields": {
        "side": {"status": "read", "value": "courtyard", "what": "the window looks down into an enclosed courtyard"},
        "view": {"status": "read", "value": "courtyard", "what": "fire escapes on the courtyard walls opposite"},
        "windows": {"status": "read", "value": {"floor_to_ceiling": False, "operable": True},
                    "what": "double-hung sash window with the lower sash raised"},
        "floor": {"status": "read", "value": 3, "what": "3"}},          # no description: dropped to cant_tell
        "note": "bedroom window"},
    1: {"fields": {
        "ac_units": {"status": "read", "value": "window", "what": "a window air conditioner in the living room"},
        "wall_material": {"status": "read", "value": "brick", "what": "exposed red brick behind the sofa"},
        "side": {"status": "read", "value": "sideways", "what": "the living room window at an angle"}},
        "note": "living room"},
}
OBSERVED = {"view": read("courtyard", photo=0),
            "windows": read({"floor_to_ceiling": False, "operable": True}, photo=0),
            "ac_units": read("window", photo=1), "wall_material": read("brick", photo=1)}


def test_photo_only(scorer):
    model = Scripted([("read_photo", {"indexes": [0, 1]}),
                      ("submit_listing", {"fields": {"address": CANT, "unit": CANT, "floor": CANT,
                                                     "side": read("courtyard", photo=0)}, "observed": OBSERVED})],
                     photos=PHOTOS)
    result = loop.read(listing(photos=2), client=model.client, scorer=scorer)

    assert result["status"] == "complete"
    assert result["fields"]["side"] == {"value": "courtyard", "status": "read", "evidence": [
        {"source": "photo:0", "what": "the window looks down into an enclosed courtyard"}]}
    assert result["position"] == "rear"
    assert result["fields"]["floor"]["status"] == "cant_tell"
    assert result["observed"]["windows"]["value"] == {"floor_to_ceiling": False, "operable": True}
    assert result["observed"]["ac_units"]["evidence"][0]["source"] == "photo:1"
    assert result["observed"]["wall_material"]["value"] == "brick"
    readings = result["photo_readings"]
    assert [r["index"] for r in readings] == [0, 1]
    assert readings[0]["fields"]["floor"]["status"] == "cant_tell" and readings[0]["dropped"]
    assert readings[1]["fields"]["side"]["status"] == "cant_tell"           # "sideways" is not a side
    image = model.photo_requests[0]["input"][0]["content"][1]
    assert image["type"] == "input_image" and image["image_url"].startswith("data:image/png;base64,")
    assert result["score"] is None and result["needs"] == ["address"] and scorer.located == []
    assert "LISTING TEXT: none" in model.agent_requests[0]["input"][0]["content"]


def test_photo_citations_are_checked(scorer):
    model = Scripted([
        ("read_photo", {"indexes": [2]}),                                           # no photo 2
        ("submit_listing", {"fields": {"address": CANT, "unit": CANT, "floor": CANT,
                                       "side": read("courtyard", photo=0)}}),       # not read yet
        ("read_photo", {"indexes": [0]}),
        ("submit_listing", {"fields": {"address": CANT, "unit": CANT, "floor": CANT,
                                       "side": read("rear", photo=0)}}),            # photo 0 says courtyard
        ("submit_listing", {"fields": {"address": CANT, "unit": CANT, "floor": CANT,
                                       "side": read("courtyard", photo=0)}}),
    ], photos=PHOTOS)
    result = loop.read(listing(photos=2), client=model.client, scorer=scorer)

    t = result["trace"]
    assert t[0]["result"]["error"].startswith("photo 2 does not exist; this listing has 2 photo(s), 0 to 1")
    assert "photo 0 has not been read; call read_photo first" in t[1]["result"]["refused"]["side"]
    assert "photo 0 does not show 'rear' (its reading says 'courtyard')" in t[3]["result"]["refused"]["side"]
    assert t[4]["ok"] and result["status"] == "complete" and result["fields"]["side"]["value"] == "courtyard"
    assert len(model.photo_requests) == 1                                           # a photo is read once


def test_budget_exhaustion_returns_a_clean_partial_result(scorer):
    invented = dict(FIELDS_01, floor=read(11, "11th floor, rear, very quiet"))
    model = Scripted([("submit_listing", {"fields": invented})] * 3)
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), client=model.client, scorer=scorer, turns=3)

    assert result["status"] == "partial" and result["stopped"] == "budget"
    assert result["turns"] == {"used": 3, "budget": 3}
    assert result["fields"]["address"]["status"] == "read"          # accepted fields are kept
    assert result["fields"]["side"]["value"] == "rear"
    assert result["fields"]["floor"] == {"value": None, "status": "cant_tell", "evidence": []}
    assert scorer.scored[0]["floor"] is None and scorer.scored[0]["position"] == "rear"
    assert loop.LAST_TURN in json.dumps(model.agent_requests[2]["input"])
    assert loop.LAST_TURN not in json.dumps(model.agent_requests[1]["input"])
    assert [t["tool"] for t in result["trace"]] == ["submit_listing"] * 3 + ["locate", "score"]
    assert any("used its 3 turns" in n for n in result["notes"])


def test_a_failing_model_api_returns_a_clean_partial_result(scorer):
    def down(body):
        raise mock.ApiFailure(503, "overloaded")

    invented = dict(FIELDS_01, floor=read(11, "11th floor, rear, very quiet"))
    model = Scripted([("submit_listing", {"fields": invented}), down])
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), client=model.client, scorer=scorer)

    assert result["status"] == "partial" and result["stopped"] == "model_error"
    assert "the Model API failed" in result["trace"][1]["result"]["error"]
    assert result["fields"]["address"]["status"] == "read" and result["fields"]["floor"]["status"] == "cant_tell"
    assert result["score"] is not None


def test_plain_text_is_not_a_turn_the_model_can_end_on(scorer):
    model = Scripted([lambda body: {"output_text": "The apartment is on the 11th floor."},
                      ("submit_listing", {"fields": FIELDS_01})])
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), client=model.client, scorer=scorer)

    assert result["trace"][0]["result"] == {"error": loop.PLAIN_TEXT}
    assert result["trace"][0]["said"] == "The apartment is on the 11th floor."
    assert result["status"] == "complete" and result["turns"]["used"] == 2


def test_no_scorer_means_no_network(scorer):
    model = Scripted([("submit_listing", {"fields": FIELDS_01})])
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), client=model.client, scorer=None)
    assert result["score"] is None and result["location"] is None
    assert [t["tool"] for t in result["trace"]] == ["submit_listing"]
