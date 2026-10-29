"""POST /adjust/permits, with rows sent in the body (no network)."""
from fastapi.testclient import TestClient

from adjust import api
from conftest import ScriptedClient, load

BETHUNE = load("55_bethune_street")
http = TestClient(api.app)


def post(body, client=None):
    api.app.dependency_overrides[api.get_client] = lambda: client
    try:
        return http.post("/adjust/permits", json=body)
    finally:
        api.app.dependency_overrides.clear()


def test_rules_when_no_key():
    r = post({"permits": BETHUNE["permits"], "as_of": BETHUNE["as_of"]})
    assert r.status_code == 200
    body = r.json()
    assert body["reader"] == "rules" and body["source"] == "construction"
    assert body["adjustment"]["cites"] == ["M01113570-I1-GC"]
    assert {p["id"] for p in body["permits"]} == {p["work_permit"] for p in BETHUNE["permits"]}


def test_model_when_a_client_is_set():
    from test_permits import SUBMIT_FACADE, bethune_readings
    client = ScriptedClient([[("read_permits", {"readings": bethune_readings()}), SUBMIT_FACADE]])
    body = post({"permits": BETHUNE["permits"], "as_of": BETHUNE["as_of"]}, client).json()
    assert body["reader"] == "muse-spark-1.3" and body["adjustment"]["size"] == 1
    assert body["trace"][0]["tool"] == "read_permits"


def test_rules_on_request_even_with_a_client():
    client = ScriptedClient([])
    body = post({"permits": BETHUNE["permits"], "as_of": BETHUNE["as_of"], "reader": "rules"}, client).json()
    assert body["reader"] == "rules" and client.requests == []


def test_model_without_a_key_is_503():
    assert post({"permits": [], "reader": "model"}).status_code == 503


def test_exactly_one_of_address_or_permits():
    assert post({}).status_code == 422
    assert post({"address": "55 Bethune Street", "permits": []}).status_code == 422


def test_no_permits_no_adjustment():
    body = post({"permits": [], "as_of": "2026-10-28"}).json()
    assert body["adjustment"] is None and body["why_none"]
