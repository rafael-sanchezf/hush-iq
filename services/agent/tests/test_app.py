"""POST /read and POST /key-check: input parsing, the headers and the event stream, against the basic reader, fake
providers and a fake scorer."""
import functools
import json

import pytest
from fastapi.testclient import TestClient

from conftest import EXPECTED, PNG, FakeScorer, events, fixture_text
from fakes import KEY, FakeOpenAI
from reader import client as model_client
from reader.app import create_app


@pytest.fixture
def client():
    """No house key (conftest), so a request with no headers gets the basic reader."""
    return TestClient(create_app(make_scorer=FakeScorer))


@pytest.fixture
def openai_api():
    return FakeOpenAI()


@pytest.fixture
def with_openai(openai_api):
    return TestClient(create_app(make_client=functools.partial(model_client.make_client, transport=openai_api),
                                 check_key=functools.partial(model_client.check_key, transport=openai_api),
                                 make_scorer=FakeScorer))


def test_json_listing_streams_turns_then_the_result(client):
    r = client.post("/read", json={"text": fixture_text("03-street-front.txt")})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = events(r)
    assert [kind for kind, _ in evs] == ["turn", "turn", "turn", "result"]
    assert [data["tool"] for _, data in evs[:3]] == ["submit_listing", "locate", "score"]
    result = evs[-1][1]
    want = EXPECTED["03-street-front.txt"]
    assert {k: result["fields"][k]["value"] for k in ("address", "unit", "floor", "side")} == \
        {k: want[k] for k in ("address", "unit", "floor", "side")}
    assert result["position"] == "front" and result["mode"] == "mock"
    assert result["trace"] == [data for _, data in evs[:3]]


def test_multipart_with_photos_and_answers(client):
    r = client.post("/read", data={"text": fixture_text("05-courtyard-unit-only.txt"),
                                   "answers": json.dumps({"sleep_from": 0, "sleep_until": 8, "bothers": ["sirens"]})},
                    files=[("photos", ("a.png", PNG, "image/png")), ("photos", ("b.png", PNG, "image/png"))])
    evs = events(r)
    assert evs[0][1]["tool"] == "read_photo" and evs[0][1]["args"] == {"indexes": [0, 1]}
    result = evs[-1][1]
    assert result["answers"] == {"sleep_from": 0, "sleep_until": 8, "day_bothers": True, "bothers": ["sirens"]}
    assert len(result["photo_readings"]) == 2
    assert result["fields"]["side"]["value"] == "courtyard" and result["fields"]["floor"]["status"] == "cant_tell"


def test_json_photos_are_data_urls(client):
    import base64
    url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    evs = events(client.post("/read", json={"text": "", "photos": [url]}))
    result = evs[-1][1]
    assert result["needs"] == ["address"] and result["photo_readings"][0]["index"] == 0


@pytest.mark.parametrize("kwargs, message", [
    ({"json": {"text": "   "}}, "send the listing text, photos, or both"),
    ({"json": {"text": "x", "photos": ["data:image/png;base64,aGVsbG8="]}}, "not a JPEG, PNG, WebP or GIF"),
    ({"json": {"text": "x", "answers": {"bothers": ["dogs"]}}}, "answers.bothers must be among"),
    ({"json": {"text": "x", "answers": {"sleep_from": 25}}}, "answers.sleep_from must be an hour"),
    ({"json": ["x"]}, "must be a JSON object"),
    ({"content": "text=x", "headers": {"content-type": "text/plain"}}, "multipart/form-data or application/json"),
])
def test_bad_input_is_a_400(client, kwargs, message):
    r = client.post("/read", **kwargs)
    assert r.status_code == 400 and message in r.json()["error"]


def test_index_says_the_mode_and_what_a_caller_may_ask_for(client, monkeypatch):
    index = client.get("/").json()
    assert index["mode"] == "mock" and index["ai"]["house"]["reason"] == "no_key"
    assert index["ai"]["providers"]["anthropic"] == {"models": ["claude-opus-5-5", "claude-sonnet-5-5",
                                                                "claude-haiku-5-5"], "default": "claude-opus-5-5"}
    assert index["ai"]["headers"] == ["x-hushiq-ai", "x-hushiq-key", "x-hushiq-model", "x-hushiq-provider"]
    monkeypatch.setenv("MODEL_API_KEY", "house-key-for-tests-0123456789")
    assert client.get("/").json()["ai"]["house"]["mode"] == "model"
    monkeypatch.setenv("HOUSE_AI", "off")
    assert client.get("/").json()["ai"]["house"]["reason"] == "house_off"


def test_every_result_has_the_ai_object(client):
    result = events(client.post("/read", json={"text": fixture_text("03-street-front.txt")}))[-1][1]
    assert result["ai"] == {"mode": "basic", "provider": "meta", "model": None, "key": "house", "reason": "no_key",
                            "message": "This server has no AI key, so the basic reader read this listing."}
    assert result["mode"] == "mock" and result["model"] == "muse-spark-1.3"


def test_ai_off_and_house_off(client, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "house-key-for-tests-0123456789")
    off = events(client.post("/read", json={"text": "x 1 Main Street"}, headers={"X-HushIQ-AI": "off"}))[-1][1]
    assert off["ai"]["reason"] == "switched_off" and off["ai"]["provider"] is None
    monkeypatch.setenv("HOUSE_AI", "off")
    house = events(client.post("/read", json={"text": "x 1 Main Street"}))[-1][1]
    assert house["ai"]["reason"] == "house_off" and house["ai"]["message"].startswith("AI reading is off.")


def test_a_caller_key_reads_with_its_provider(with_openai, openai_api):
    r = with_openai.post("/read", json={"text": fixture_text("03-street-front.txt")},
                         headers={"X-HushIQ-Provider": "openai", "X-HushIQ-Key": KEY, "X-HushIQ-Model": "gpt-6.1-terra"})
    result = events(r)[-1][1]
    assert result["ai"] == {"mode": "model", "provider": "openai", "model": "gpt-6.1-terra", "key": "caller",
                            "reason": None, "message": None}
    assert result["mode"] == "live" and openai_api.requests[0][3]["model"] == "gpt-6.1-terra"


@pytest.mark.parametrize("headers, message", [
    ({"X-HushIQ-AI": "sometimes"}, "X-HushIQ-AI must be one of on, off"),
    ({"X-HushIQ-Provider": "gemini"}, "X-HushIQ-Provider must be one of meta, openai, anthropic"),
    ({"X-HushIQ-Provider": "openai", "X-HushIQ-Key": KEY, "X-HushIQ-Model": "gpt-4o"}, "not one of openai's models"),
])
def test_bad_headers_are_a_400(client, headers, message):
    r = client.post("/read", json={"text": "x"}, headers=headers)
    assert r.status_code == 400 and message in r.json()["error"] and KEY not in r.text


def test_key_check(with_openai):
    r = with_openai.post("/key-check", headers={"X-HushIQ-Provider": "openai", "X-HushIQ-Key": KEY})
    assert r.json() == {"ok": True, "provider": "openai", "message": "OpenAI accepted the key, and gpt-6-luna is "
                                                                     "available."}
    assert with_openai.post("/key-check", headers={"X-HushIQ-Provider": "x"}).status_code == 400
    assert with_openai.post("/key-check").json()["ok"] is False
