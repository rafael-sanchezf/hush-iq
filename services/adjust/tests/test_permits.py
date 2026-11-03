"""The permit reader in mock mode: a scripted model, real permit rows."""
import json
import re

import pytest

from adjust import config as A
from adjust.adjustment import Refused
from adjust.permits import check_quote, check_reading, permits_to_read, read_permits, scrub
from conftest import FIXTURES, ScriptedClient, load

BETHUNE = load("55_bethune_street")
EAST_86 = load("350_east_86th_street")
WEST_57 = load("100_west_57th_street")

FACADE = "M01113570-I1-GC"    # 155 Bank Street: "EXTERIOR MASONRY RESTORATION, ROOF REPLACEMENTS, ..."
SHED = "M01255421-S1-SH"
CHUTE = "M01265075-I1-PMM"
SCAFFOLD = "M01181311-I1-SC"


def bethune_readings(facade_quote="EXTERIOR MASONRY RESTORATION"):
    return [
        {"id": FACADE, "kind": "facade", "kind_quote": facade_quote,
         "duration": "months", "duration_quote": facade_quote},
        {"id": CHUTE, "kind": "other", "kind_quote": "INSTALLATION OF TEMPORARY DEBRIS CHUTE", "duration": "cant_tell"},
        {"id": SHED, "kind": "scaffold_shed", "kind_quote": "TEMP SIDEWALK SHED",
         "duration": "months", "duration_quote": "TEMP SIDEWALK SHED"},
        {"id": SCAFFOLD, "kind": "scaffold_shed", "kind_quote": "suspended scaffold for facade work or inspection",
         "duration": "cant_tell"},
    ]


SUBMIT_FACADE = ("submit_adjustment", {"direction": "louder", "size": 1, "cites": [FACADE],
                                       "reason": "A masonry restoration on the block will run for months."})


# ---------------------------------------------------------------- the five the card asks for
def test_facade_permit_read_correctly():
    client = ScriptedClient([[("read_permits", {"readings": bethune_readings()})], [SUBMIT_FACADE]])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)

    assert out["reader"] == A.MODEL_DEFAULT
    assert out["refusals"] == [] and out["not_read"] == []
    facade = next(r for r in out["readings"] if r["id"] == FACADE)
    assert facade["address"] == "155 Bank Street"
    assert facade["kind"] == {"value": "facade", "status": "read",
                              "evidence": [{"source": f"permit:{FACADE}", "quote": "EXTERIOR MASONRY RESTORATION"}]}
    assert facade["duration"]["value"] == "months"
    chute = next(r for r in out["readings"] if r["id"] == CHUTE)
    assert chute["duration"] == {"value": None, "status": "cant_tell", "evidence": []}
    assert out["adjustment"] == {"source": "construction", "direction": "louder", "size": 1, "cap": 2,
                                 "cites": [FACADE], "reason": "A masonry restoration on the block will run for months."}
    assert len(client.requests) == 2 and client.turns == []


def test_invented_quote_refused():
    invented = bethune_readings(facade_quote="FULL FACADE REPLACEMENT OF ALL ELEVATIONS")
    client = ScriptedClient([
        [("read_permits", {"readings": invented})],
        [("read_permits", {"readings": bethune_readings()[:1]})],   # the model corrects the one refused
        [SUBMIT_FACADE],
    ])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)

    seen = client.tool_results(1)[-1]   # what the model was told after its first call
    assert seen["ok"] is False and seen["accepted"] == [CHUTE, SHED, SCAFFOLD]
    assert seen["refused"][0]["id"] == FACADE and "not in this permit's job description" in seen["refused"][0]["why"]
    assert seen["not_read_yet"] == [FACADE]
    assert out["refusals"][0]["id"] == FACADE
    facade = next(r for r in out["readings"] if r["id"] == FACADE)
    assert facade["kind"]["evidence"][0]["quote"] == "EXTERIOR MASONRY RESTORATION"
    assert out["adjustment"]["cites"] == [FACADE]


def test_adjustment_over_cap_refused():
    readings = [
        {"id": "M00625489-S2-SE", "kind": "new_building", "kind_quote": "SUBSEQUENT FILING TO NB #M00625489",
         "duration": "years", "duration_quote": "NB #M00625489"},
        {"id": "M01159724-I1-GC", "kind": "facade", "kind_quote": "Facade Repairs",
         "duration": "months", "duration_quote": "Facade Repairs"},
    ]
    over = {"direction": "louder", "size": 3, "cites": ["M00625489-S2-SE"], "reason": "A new building is going up."}
    client = ScriptedClient([
        [("read_permits", {"readings": readings}), ("submit_adjustment", over)],
        [("submit_adjustment", {**over, "size": 2})],
    ])
    out = read_permits(EAST_86["permits"], EAST_86["as_of"], client=client)

    seen = client.tool_results(1)[-1]
    assert seen == {"ok": False, "refused": "size 3 exceeds the construction cap of 2"}
    assert out["adjustment"]["size"] == 2 and out["adjustment"]["cap"] == 2
    assert {"tool": "submit_adjustment", "why": "size 3 exceeds the construction cap of 2"} in out["refusals"]


def test_citation_of_a_row_not_in_the_pull_refused():
    elsewhere = {"direction": "louder", "size": 1, "cites": [FACADE, "M00625489-S2-SE"],   # second: another block
                 "reason": "Facade work and a new building nearby."}
    client = ScriptedClient([
        [("read_permits", {"readings": bethune_readings()}), ("submit_adjustment", elsewhere)],
        [SUBMIT_FACADE],
    ])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)

    seen = client.tool_results(1)[-1]
    assert seen == {"ok": False, "refused": "cites M00625489-S2-SE, which is not among the rows sent"}
    assert out["adjustment"]["cites"] == [FACADE]


def test_no_permits_no_adjustment():
    client = ScriptedClient([])
    out = read_permits([], "2026-10-28", client=client)
    assert out["adjustment"] is None and out["permits"] == [] and out["readings"] == []
    assert out["why_none"] == "no unexpired loud-work or scaffold permit on this tax block"
    assert client.requests == []   # the model is never called

    expired = [{**p, "expired_date": "2026-01-01T00:00:00.000"} for p in BETHUNE["permits"]]
    assert read_permits(expired, "2026-10-28", client=client)["adjustment"] is None
    assert client.requests == []


# ---------------------------------------------------------------- the other refusals
def test_quote_from_another_permit_refused():
    sent = {p["work_permit"]: p for p in BETHUNE["permits"]}
    with pytest.raises(Refused, match="not in this permit's job description"):
        check_reading({"id": SHED, "kind": "facade", "kind_quote": "EXTERIOR MASONRY RESTORATION",
                       "duration": "months", "duration_quote": "EXTERIOR MASONRY RESTORATION"}, sent)


def test_quote_rules():
    desc = "INSTL OF TEMP  SIDEWALK SHED AS PER PLAN."
    assert check_quote("temp sidewalk shed", desc) == "temp sidewalk shed"   # case and spaces forgiven
    assert check_quote('"TEMP SIDEWALK SHED"', desc) == "TEMP SIDEWALK SHED"
    for bad in ("SHE", None, "TEMPORARY SIDEWALK SHED", "SIDEWALK SHED FOR FACADE"):
        with pytest.raises(Refused):
            check_quote(bad, desc)


def test_reading_needs_a_quote_unless_cant_tell():
    sent = {p["work_permit"]: p for p in BETHUNE["permits"]}
    with pytest.raises(Refused, match="a quote is required"):
        check_reading({"id": FACADE, "kind": "facade", "duration": "cant_tell"}, sent)
    with pytest.raises(Refused, match="not among the permits sent"):
        check_reading({"id": "M00000000-I1-GC", "kind": "cant_tell", "duration": "cant_tell"}, sent)
    with pytest.raises(Refused, match="kind 'tower'"):
        check_reading({"id": FACADE, "kind": "tower", "duration": "years"}, sent)
    r = check_reading({"id": FACADE, "kind": "cant_tell", "duration": "cant_tell"}, sent)
    assert r["kind"]["status"] == "cant_tell" and r["kind"]["value"] is None


def test_cite_without_an_accepted_reading_refused():
    client = ScriptedClient([
        [("read_permits", {"readings": bethune_readings()[1:]}),    # the facade permit is never read
         ("submit_adjustment", SUBMIT_FACADE[1])],
        [("no_adjustment", {"reason": "Nothing heavier than the count."})],
    ])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)
    assert client.tool_results(1)[-1]["refused"] == f"cites {FACADE}, which has no accepted reading"
    assert out["adjustment"] is None and out["why_none"] == "Nothing heavier than the count."
    assert out["not_read"] == [FACADE]


def test_direction_must_follow_the_cited_readings():
    readings = bethune_readings()
    client = ScriptedClient([
        [("read_permits", {"readings": readings}),
         ("submit_adjustment", {"direction": "louder", "size": 1, "cites": [SHED], "reason": "A shed."}),
         ("submit_adjustment", {"direction": "quieter", "size": 1, "cites": [SHED], "reason": "Only a shed."}),
         ("submit_adjustment", {"direction": "louder", "size": 2, "cites": [FACADE], "reason": "Facade work."})],
        [SUBMIT_FACADE],
    ])
    read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)
    refused = [r["refused"] for r in client.tool_results(1)[1:]]
    assert refused == ["none of the cited rows points louder",
                       "a permit on this block reads louder, so the block cannot be adjusted quieter",
                       "the cited rows support at most 1 step louder, not 2"]


def test_model_that_stops_gives_no_adjustment():
    client = ScriptedClient(["I think the facade job is loud.", "Still thinking."])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)
    assert out["adjustment"] is None and out["why_none"] == "the model stopped without submitting an adjustment"


def test_empty_reply_is_sent_again_with_room_to_reason():
    client = ScriptedClient(["", [("read_permits", {"readings": bethune_readings()})], [SUBMIT_FACADE]])
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=client)
    assert out["adjustment"]["cites"] == [FACADE]
    assert out["trace"][0]["empty"] is True and out["usage"]["calls"] == 3
    assert client.requests[0] == client.requests[1]   # the empty reply is not added to the conversation
    assert all(kw["max_tokens"] >= 2000 for kw in client.kwargs)

    only_empty = ScriptedClient([""] * (A.MODEL_EMPTY_RETRIES + 1))
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=only_empty)
    assert out["adjustment"] is None and out["why_none"] == "the model sent only empty replies"


def test_api_error_gives_no_adjustment():
    import httpx
    import openai
    err = openai.APIConnectionError(request=httpx.Request("POST", "https://api.meta.ai/v1/chat/completions"))
    out = read_permits(BETHUNE["permits"], BETHUNE["as_of"], client=ScriptedClient([err]))
    assert out["adjustment"] is None and out["why_none"] == "the model call failed"
    assert out["trace"][0]["error"] == out["failure"] == "provider_error"   # the kind only, never the SDK's text


# ---------------------------------------------------------------- live Muse Spark runs, replayed
@pytest.mark.parametrize("name", ["55_bethune_street", "350_east_86th_street", "100_west_57th_street"])
def test_recorded_muse_spark_run_replays(name):
    """Muse Spark's own tool calls from the live run of 2026-10-28, sent back through today's checks."""
    rec = json.loads((FIXTURES / "live" / f"{name}.json").read_text())
    doc = load(name)
    out = read_permits(doc["permits"], doc["as_of"], client=ScriptedClient(rec["turns"]))
    assert out["adjustment"] == rec["adjustment"]
    assert out["not_read"] == []
    assert all(e["quote"] for r in out["readings"] for f in ("kind", "duration") for e in r[f]["evidence"])


# ---------------------------------------------------------------- the rules reader, on the same rows
def test_rules_reader_on_the_fixtures():
    bethune = read_permits(BETHUNE["permits"], BETHUNE["as_of"])
    assert bethune["reader"] == "rules" and bethune["refusals"] == []
    assert bethune["adjustment"]["direction"] == "louder" and bethune["adjustment"]["size"] == 1
    assert bethune["adjustment"]["cites"] == [FACADE]

    east = read_permits(EAST_86["permits"], EAST_86["as_of"])
    nb = next(r for r in east["readings"] if r["id"] == "M00625489-S2-SE")
    assert nb["kind"]["value"] == "new_building" and nb["kind"]["evidence"][0]["quote"] == "NB #M00625489"
    assert east["adjustment"]["direction"] == "louder" and east["adjustment"]["size"] == 2
    assert "M00625489-S2-SE" in east["adjustment"]["cites"]

    west = read_permits(WEST_57["permits"], WEST_57["as_of"])
    assert west["adjustment"]["direction"] == "quieter" and west["adjustment"]["size"] == 1
    assert len(west["adjustment"]["cites"]) >= A.QUIETER_MIN_SHARE * len(west["permits"])


# ---------------------------------------------------------------- what is sent, and what is committed
def test_permits_to_read_dedupes_filters_and_scrubs():
    rows = [
        {"work_permit": "M1-I1-GC", "work_type": "General Construction", "job_description": "FACADE REPAIRS",
         "expired_date": "2026-05-01T00:00:00.000", "owner_name": "someone", "owner_business_name": "someone llc"},
        {"work_permit": "M1-I1-GC", "work_type": "General Construction",
         "job_description": "FACADE REPAIRS, CALL 212-555-0100 OR SOMEONE@EXAMPLE.COM",
         "expired_date": "2027-05-01T00:00:00.000", "applicant_first_name": "someone"},
        {"work_permit": "M2-I1-PL", "work_type": "Plumbing", "job_description": "NEW BOILER",
         "expired_date": "2027-05-01T00:00:00.000"},
        {"work_permit": "M3-I1-SC", "work_type": "Suspended Scaffold", "job_description": "SCAFFOLD",
         "expired_date": "2026-01-01T00:00:00.000"},
    ]
    sent = permits_to_read(rows, "2026-10-28")
    assert [r["work_permit"] for r in sent] == ["M1-I1-GC"]
    assert sent[0]["expired_date"].startswith("2027")
    assert sent[0]["job_description"] == "FACADE REPAIRS, CALL [removed] OR [removed]"
    assert set(sent[0]) <= set(A.PERMIT_FIELDS)


def test_fixtures_hold_no_personal_field():
    phone = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]\d{4}\b")
    for doc in (BETHUNE, EAST_86, WEST_57):
        for row in doc["permits"]:
            assert set(row) <= set(A.PERMIT_FIELDS), set(row) - set(A.PERMIT_FIELDS)
            assert row == scrub(row)
            assert "@" not in row.get("job_description", "") and not phone.search(row.get("job_description", ""))
