"""A caller's key never leaves the request: not in a response body, a trace, an error, or a log line.

A fake key goes through every path (success, 401, 429, timeout, a model the provider does not have, a model id the
reader does not allow) for each provider, on POST /read and POST /key-check, with every logger at DEBUG. The fake
providers quote the key in full in their error messages, the worst a provider could do.
"""
import functools
import logging

import pytest
from fastapi.testclient import TestClient

from conftest import FakeScorer, events, fixture_text
from fakes import KEY, FakeClaude, FakeOpenAI
from reader import client as model_client
from reader.app import create_app

HOUSE = "house-key-for-tests-0123456789"
OUTCOMES = ("ok", "401", "429", "timeout", "404", "bad_model")
FRAGMENTS = (KEY, KEY.removeprefix("sk-"), "FAKE-0123456789abcdef", HOUSE)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(model_client, "CALLER_RETRIES", 0)
    monkeypatch.setattr(model_client, "MAX_RETRIES", 0)
    monkeypatch.setenv("MODEL_API_KEY", HOUSE)


def app_for(provider, outcome):
    fail = None if outcome in ("ok", "bad_model") else outcome
    api = FakeClaude(fail=fail) if provider == "anthropic" else FakeOpenAI(fail=fail)
    app = create_app(make_client=functools.partial(model_client.make_client, transport=api),
                     check_key=functools.partial(model_client.check_key, transport=api), make_scorer=FakeScorer)
    model = "not-a-model" if outcome == "bad_model" else None
    headers = {"X-HushIQ-Provider": provider, "X-HushIQ-Key": KEY}
    if model:
        headers["X-HushIQ-Model"] = model
    return TestClient(app), headers, api


def assert_no_key(*texts):
    for text in texts:
        for fragment in FRAGMENTS:
            assert fragment not in text


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("provider", ("meta", "openai", "anthropic"))
def test_read_never_shows_the_key(caplog, capsys, provider, outcome):
    caplog.set_level(logging.DEBUG)
    http, headers, api = app_for(provider, outcome)
    r = http.post("/read", json={"text": fixture_text("03-street-front.txt")}, headers=headers)

    if outcome == "bad_model":
        assert r.status_code == 400 and api.requests == []
    else:
        result = events(r)[-1][1]
        assert result["ai"]["mode"] == ("model" if outcome == "ok" else "basic")
        assert result["ai"]["key"] == "caller" and result["status"] == "complete"
        assert {req[1].removeprefix("Bearer ") for req in api.requests} == {KEY}    # never the house key
    out = capsys.readouterr()
    assert_no_key(r.text, caplog.text, out.out, out.err)
    assert any("api." in rec.getMessage() or "Request" in rec.getMessage() for rec in caplog.records) \
        or outcome == "bad_model"                                                  # the logs were captured


@pytest.mark.parametrize("outcome", OUTCOMES)
@pytest.mark.parametrize("provider", ("meta", "openai", "anthropic"))
def test_key_check_never_shows_the_key(caplog, capsys, provider, outcome):
    caplog.set_level(logging.DEBUG)
    http, headers, _ = app_for(provider, outcome)
    r = http.post("/key-check", headers=headers)
    assert r.status_code == (400 if outcome == "bad_model" else 200)
    out = capsys.readouterr()
    assert_no_key(r.text, caplog.text, out.out, out.err)


def test_the_house_key_is_scrubbed_too(caplog):
    caplog.set_level(logging.DEBUG)
    api = FakeOpenAI(fail="401")
    http = TestClient(create_app(make_client=functools.partial(model_client.make_client, transport=api),
                                 make_scorer=FakeScorer))
    r = http.post("/read", json={"text": fixture_text("03-street-front.txt")})
    result = events(r)[-1][1]
    assert result["ai"]["reason"] == "key_rejected" and result["ai"]["key"] == "house"
    assert "[redacted]" in result["trace"][0]["result"]["error"]
    assert_no_key(r.text, caplog.text)


def test_a_crash_mid_stream_is_scrubbed():
    from reader.app import sse

    def broken():
        yield "turn", {"n": 1}
        raise RuntimeError(f"something quoted {KEY}")

    out = "".join(sse(broken(), (KEY,)))
    assert "event: error" in out and "[redacted]" in out and KEY not in out
