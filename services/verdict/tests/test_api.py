import pytest
from fastapi.testclient import TestClient

from conftest import FIELDS, load
from test_writer import GOOD
from verdict import api


@pytest.fixture
def client():
    api.app.dependency_overrides[api.get_backend] = lambda: None
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def test_post_verdict_returns_evidence_and_cited_sentences(client):
    r = client.post("/verdict", json={"score": load("claremont"), "fields": FIELDS["claremont"],
                                      "answers": {"sleep_from": 23, "sleep_until": 7, "day_bothers": True, "bothers": ["sirens"]}})
    assert r.status_code == 200
    body = r.json()
    assert body["writer"] == "template"
    assert set(body["evidence"][0]) == {"id", "text", "kind", "source"}
    known = {e["id"] for e in body["evidence"]}
    assert body["sentences"] and all(set(s["cites"]) <= known and s["cites"] for s in body["sentences"])
    assert "dB" not in r.text and "decibel" not in r.text.lower()


def test_v1_score_is_accepted(client):
    r = client.post("/verdict", json={"score": load("claremont_v1"),
                                      "answers": {"sleep_from": 23, "sleep_until": 7, "bothers": ["sirens"]}})
    assert r.status_code == 200 and r.json()["evidence"][0]["kind"] == "verdict"
    # v1 carries decibel levels in its raw shape; none come out
    assert '"levels"' not in r.text and "dB" not in r.text


def test_the_model_backend_and_the_template_switch(client, backend):
    api.app.dependency_overrides[api.get_backend] = lambda: backend(GOOD)
    body = {"score": load("ludlow"), "fields": FIELDS["ludlow"]}
    assert client.post("/verdict", json=body).json()["writer"] == "muse-spark-open"
    api.app.dependency_overrides[api.get_backend] = lambda: backend(GOOD)
    assert client.post("/verdict?writer=template", json=body).json()["writer"] == "template"


def test_bad_input_is_a_422(client):
    assert client.post("/verdict", json={"score": {"verdict": "Quiet"}}).status_code == 422
    assert client.post("/verdict", json={"score": load("ludlow"), "answers": {"bothers": ["dogs"]}}).status_code == 422
    assert client.post("/verdict", json={"answers": {}}).status_code == 422


def test_health_names_the_writer(client):
    assert client.get("/health").json()["writer"] == "template"
