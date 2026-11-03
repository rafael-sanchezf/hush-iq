"""The one origin (api/index.py): every route on one host, CORS open for POST, and the extension's route probe.
Offline: the reader runs with AI off and no scorer, and the verdict with the template."""
import json
import os
from pathlib import Path

os.environ["READER_SCORE"] = "off"     # read before api.index builds the reader; no score API call from here

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import index  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OFF = {"X-HushIQ-AI": "off"}


@pytest.fixture(scope="module")
def client():
    return TestClient(index.app)


def test_every_route_is_on_one_host(client):
    paths = {r.path for r in index.gateway.routes}
    assert {"/", "/v1/score", "/v2/score", "/v1/raw", "/read", "/key-check", "/verdict", "/adjust/permits",
            "/health", "/health/reader", "/health/verdict"} <= paths
    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/index/health").status_code == 200          # the prefix Vercel's router may add


def test_the_bare_host_is_an_index_not_the_prototype_page(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    routes = r.json()["routes"]
    assert "POST /read" in routes and "GET /v2/score" in routes
    served = {(m, rt.path) for rt in index.gateway.routes for m in getattr(rt, "methods", ())}
    for k in routes:
        method, path = k.split(" ", 1)
        assert (method, path) in served, k


def test_head_answers_405_on_a_route_and_404_off_one(client):
    """The extension's auto mode: a HEAD that answers 404 means the route is missing and the panel replays it."""
    for path in ("/read", "/verdict", "/key-check"):
        assert client.head(path).status_code == 405, path
    assert client.head("/nothing-here").status_code == 404


def test_a_browser_may_post_with_the_ai_headers(client):
    """The score API alone allows GET only, so a browser POST to /read on its host failed preflight."""
    r = client.options("/read", headers={"Origin": "https://hushiq.example", "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": "content-type,x-hushiq-ai,x-hushiq-key"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "POST" in r.headers["access-control-allow-methods"]


def test_read_streams_a_result_with_ai_off(client):
    text = (ROOT / "services/agent/fixtures/01-stated-rear.txt").read_text()
    r = client.post("/read", json={"text": text}, headers=OFF)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = [block.split("\n")[0].removeprefix("event: ") for block in r.text.strip().split("\n\n")]
    assert events[-1] == "result", events
    result = json.loads(r.text.strip().split("\n\n")[-1].split("data: ", 1)[1])
    assert result["ai"]["mode"] != "model"


def test_verdict_answers_with_the_template_when_ai_is_off(client):
    score = json.loads((ROOT / "services/verdict/tests/fixtures/v2_claremont_floor4_rear.json").read_text())
    r = client.post("/verdict", json={"score": score}, headers=OFF)
    assert r.status_code == 200
    body = r.json()
    assert body["writer"] == "template" and body["evidence"] and body["sentences"]
    assert client.get("/health/verdict").json()["ok"] is True
