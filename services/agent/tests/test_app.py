"""POST /read: input parsing and the event stream, against the mock model and a fake scorer."""
import json

import pytest
from fastapi.testclient import TestClient

from conftest import EXPECTED, PNG, FakeScorer, fixture_text
from reader import mock
from reader.app import create_app


def events(response):
    """[(event, data)] from a server-sent event stream."""
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def client():
    app = create_app(make_client=lambda: (mock.client(mock.HeuristicModel()), "mock"), make_scorer=FakeScorer)
    return TestClient(app)


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


def test_index_says_the_mode(client):
    assert client.get("/").json()["mode"] == "mock"
