"""The AI switch and caller keys (HIQ-77): headers, the house key, the three providers, and the key never leaking.
The providers run on the real SDKs over a mock transport (tests/wire.py); nothing leaves the machine."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

from adjust import api, config as A, switch
from adjust.switch import BadSwitch, choose
from conftest import ScriptedClient, load
from test_permits import FACADE, SUBMIT_FACADE, bethune_readings
from wire import HOSTS, TIMEOUT, Wire

BETHUNE = load("55_bethune_street")
ROWS, AS_OF = BETHUNE["permits"], BETHUNE["as_of"]
KEY = "sk-test-FAKE-0123456789abcdef-hushiq"
READ = [("read_permits", {"readings": bethune_readings()})]
GOOD = [READ, [SUBMIT_FACADE]]
PROVIDERS = list(A.PROVIDERS)


class NoConnect:
    def __call__(self, *a):
        raise AssertionError("a caller client was built")


def never_called():
    return ScriptedClient([])   # any call fails: "the model was called more times than scripted"


# ---------------------------------------------------------------- S1 the headers
def test_absent_headers_mean_on_meta_house_key_default_model():
    c = choose()
    assert (c.on, c.provider, c.model, c.key) == (True, "meta", "muse-spark-1.3", None)
    assert choose(provider="anthropic").model == A.PROVIDERS["anthropic"]["default"]
    assert choose(ai="OFF").on is False


@pytest.mark.parametrize("headers", [{"ai": "maybe"}, {"provider": "gemini"},
                                     {"provider": "openai", "model": "claude-opus-5-5"}, {"model": KEY}])
def test_a_value_outside_its_list_is_refused_without_repeating_it(headers):
    with pytest.raises(BadSwitch) as e:
        choose(**headers)
    assert KEY not in str(e.value) and "gemini" not in str(e.value)


def test_the_key_is_not_in_the_choice_repr():
    assert KEY not in repr(choose(provider="openai", key=KEY))


# ---------------------------------------------------------------- S2 off, and the house key
def test_off_makes_no_model_call_and_no_adjustment():
    house = never_called()
    out = switch.run(ROWS, AS_OF, choose(ai="off", provider="anthropic", key=KEY), house=house, connect=NoConnect())
    assert out["adjustment"] is None and out["readings"] == [] and house.requests == []
    assert out["reader"] is None and len(out["not_read"]) == 4 and out["permits"]
    assert out["ai"] == {"mode": "basic", "provider": None, "model": None, "key": None, "reason": "switched_off",
                         "message": switch.MESSAGES["switched_off"]}
    assert out["why_none"] == out["ai"]["message"]


def test_house_off_runs_basic_unless_the_caller_brings_a_key(monkeypatch):
    monkeypatch.setenv("HOUSE_AI", "off")
    house = never_called()
    out = switch.run(ROWS, AS_OF, choose(), house=house, connect=NoConnect())
    assert out["ai"]["reason"] == "house_off" and out["ai"]["provider"] == "meta" and out["adjustment"] is None
    assert "Add your own key" in out["ai"]["message"]

    wire = Wire("meta", GOOD, KEY)
    out = switch.run(ROWS, AS_OF, choose(key=KEY), house=house, connect=wire.connect)
    assert out["ai"]["mode"] == "model" and out["ai"]["key"] == "caller" and out["adjustment"]["cites"] == [FACADE]
    assert house.requests == []


def test_no_house_key_and_no_caller_key_is_basic():
    assert switch.run(ROWS, AS_OF, choose(), house=None)["ai"]["reason"] == "no_key"
    out = switch.run(ROWS, AS_OF, choose(provider="openai"), house=never_called(), connect=NoConnect())
    assert out["ai"] == {"mode": "basic", "provider": "openai", "model": None, "key": None, "reason": "no_key",
                         "message": "No OpenAI key is set. Add your own key in settings to turn AI reading on."}


def test_house_key_reads_with_muse_spark():
    out = switch.run(ROWS, AS_OF, choose(), house=ScriptedClient(GOOD))
    assert out["ai"] == {"mode": "model", "provider": "meta", "model": "muse-spark-1.3", "key": "house",
                         "reason": None, "message": None}
    assert out["reader"] == "muse-spark-1.3" and out["adjustment"]["size"] == 1 and "failure" not in out


# ---------------------------------------------------------------- S4 the same checks for every provider
@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_provider_reads_with_the_callers_key_at_its_own_host(provider):
    wire = Wire(provider, GOOD, KEY)
    out = switch.run(ROWS, AS_OF, choose(provider=provider, key=KEY), house=never_called(), connect=wire.connect)
    model = A.PROVIDERS[provider]["default"]
    assert out["ai"] == {"mode": "model", "provider": provider, "model": model, "key": "caller",
                         "reason": None, "message": None}
    assert out["reader"] == model and out["refusals"] == [] and out["not_read"] == []
    assert out["adjustment"] == {"source": "construction", "direction": "louder", "size": 1, "cap": 2,
                                 "cites": [FACADE], "reason": SUBMIT_FACADE[1]["reason"]}
    assert out["usage"] == {"calls": 2, "prompt_tokens": 200, "completion_tokens": 100,
                            "reasoning_tokens": None if provider == "anthropic" else 80}
    assert {h for h, *_ in wire.requests} == {HOSTS[provider]}
    assert all(KEY in auth for _, _, auth, _ in wire.requests)   # the caller's key, sent to its own provider


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_provider_meets_the_same_cap_and_citation_checks(provider):
    over_cap = ("submit_adjustment", {**SUBMIT_FACADE[1], "size": 3})
    not_sent = ("submit_adjustment", {**SUBMIT_FACADE[1], "cites": ["M09999999-I1-GC"]})
    invented = [("read_permits", {"readings": bethune_readings(facade_quote="FULL FACADE REPLACEMENT")})]
    wire = Wire(provider, [invented, READ, [over_cap], [not_sent], [SUBMIT_FACADE]], KEY)
    out = switch.run(ROWS, AS_OF, choose(provider=provider, key=KEY), connect=wire.connect)
    assert [r["why"] for r in out["refusals"]] == [
        "quote 'FULL FACADE REPLACEMENT' is not in this permit's job description",
        "size 3 exceeds the construction cap of 2",
        "cites M09999999-I1-GC, which is not among the rows sent"]
    assert out["adjustment"]["size"] == 1 and out["adjustment"]["cap"] == 2


def test_claude_gets_its_thinking_back_and_no_forced_tool_call():
    wire = Wire("anthropic", GOOD, KEY)
    switch.run(ROWS, AS_OF, choose(provider="anthropic", key=KEY), connect=wire.connect)
    (_, path, _, first), (_, _, _, second) = wire.requests
    assert path == "/v1/messages" and first["tool_choice"] == {"type": "auto"} and "temperature" not in first
    assert first["fallbacks"] == "default" and first["output_config"] == {"effort": A.ANTHROPIC_EFFORT}
    assert second["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}
    assert second["messages"][2]["content"][0]["type"] == "tool_result"

    haiku = Wire("anthropic", GOOD, KEY)
    switch.run(ROWS, AS_OF, choose(provider="anthropic", model="claude-haiku-5-5", key=KEY), connect=haiku.connect)
    assert "fallbacks" not in haiku.requests[0][3]   # Haiku has no server-side fallback


def test_openai_stores_nothing_and_gets_its_reasoning_back():
    wire = Wire("openai", GOOD, KEY)
    switch.run(ROWS, AS_OF, choose(provider="openai", key=KEY), connect=wire.connect)
    (_, path, _, first), (_, _, _, second) = wire.requests
    assert path == "/v1/responses" and first["store"] is False
    assert first["include"] == ["reasoning.encrypted_content"]
    assert second["input"][1]["encrypted_content"] == "sealed-1"
    assert second["input"][-1]["type"] == "function_call_output"


def test_claude_declining_gives_no_adjustment():
    wire = Wire("anthropic", [READ], KEY)
    wire.anthropic = lambda n, turn: {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                      "content": [], "stop_reason": "refusal", "stop_sequence": None,
                                      "usage": {"input_tokens": 1, "output_tokens": 0}}
    out = switch.run(ROWS, AS_OF, choose(provider="anthropic", key=KEY), connect=wire.connect)
    assert out["adjustment"] is None and out["why_none"] == "the model declined to read these permits"
    assert out["ai"]["mode"] == "model" and len(wire.requests) == 1   # declined, not retried


# ---------------------------------------------------------------- S3 a failed key never falls back
@pytest.mark.parametrize("turn,reason", [(401, "key_rejected"), (403, "key_rejected"), (429, "provider_busy"),
                                         (TIMEOUT, "provider_busy"), (404, "provider_error"), (500, "provider_error")])
@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_failed_caller_key_is_basic_and_never_spends_the_house_key(provider, turn, reason):
    house = never_called()
    wire = Wire(provider, [turn], KEY)
    out = switch.run(ROWS, AS_OF, choose(provider=provider, key=KEY), house=house, connect=wire.connect)
    assert out["adjustment"] is None and house.requests == [] and len(wire.requests) == 1   # no retry
    assert out["ai"]["mode"] == "basic" and out["ai"]["reason"] == reason and out["ai"]["key"] == "caller"
    assert out["ai"]["provider"] == provider and switch.NAMES[provider] in out["ai"]["message"]
    assert out["trace"][-1]["error"] == reason


# ---------------------------------------------------------------- S4 the key never leaks
http = TestClient(api.app)


def post(headers, wire=None, house=None, body=None):
    api.app.dependency_overrides[api.get_client] = lambda: house
    api.app.dependency_overrides[api.get_connect] = lambda: (wire.connect if wire else NoConnect())
    try:
        return http.post("/adjust/permits", json=body or {"permits": ROWS, "as_of": AS_OF}, headers=headers)
    finally:
        api.app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["success", 401, 429, TIMEOUT, "provider rejects the model", "model not on the list"])
@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_fake_key_appears_nowhere(provider, path, caplog, capfd):
    caplog.set_level(logging.DEBUG)
    for name in ("openai", "anthropic", "httpx", "httpx2", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=name)
    turns = {"success": GOOD, "provider rejects the model": [404]}.get(path, [path])
    wire = Wire(provider, turns, KEY)
    headers = {"X-HushIQ-AI": "on", "X-HushIQ-Provider": provider, "X-HushIQ-Key": KEY}
    if path == "model not on the list":
        headers["X-HushIQ-Model"] = "not-a-model"
    r = post(headers, wire, house=never_called())

    assert r.status_code == (400 if path == "model not on the list" else 200)
    if r.status_code == 200:
        body = r.json()
        assert body["ai"]["key"] == "caller" and body["ai"]["mode"] == ("model" if path == "success" else "basic")
        assert KEY not in json.dumps(body["trace"])
    if path != "model not on the list":
        assert wire.requests and all(KEY in auth for _, _, auth, _ in wire.requests)   # it was really sent
    assert KEY not in r.text
    assert KEY not in caplog.text and all(KEY not in str(rec.args) for rec in caplog.records)
    out, err = capfd.readouterr()
    assert KEY not in out and KEY not in err


@pytest.mark.parametrize("turn", [401, 429, TIMEOUT, 404, 500])
@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_reader_keeps_no_provider_text_before_redaction(provider, turn):
    """The first gate: read_permits itself, before switch.redact, holds the failure kind and status only."""
    from adjust.permits import read_permits
    out = read_permits(ROWS, AS_OF, client=Wire(provider, [turn], KEY).backend())
    assert out["failure"] and KEY not in json.dumps(out) and "Incorrect API key" not in json.dumps(out)


def test_redact_is_the_last_gate():
    reply = {"trace": [{"said": f"my key is {KEY}"}], KEY: [KEY, 1, None]}
    assert KEY not in json.dumps(switch.redact(reply, KEY))
    assert switch.redact({"a": "short"}, "short") == {"a": "short"}   # too short to be a key; left alone


# ---------------------------------------------------------------- the endpoint
def test_headers_outside_their_lists_are_400():
    assert post({"X-HushIQ-AI": "sometimes"}).status_code == 400
    assert post({"X-HushIQ-Provider": "gemini"}).status_code == 400
    r = post({"X-HushIQ-Provider": "anthropic", "X-HushIQ-Model": "gpt-6.1-sol", "X-HushIQ-Key": KEY})
    assert r.status_code == 400 and "claude-opus-5-5" in r.json()["detail"]


def test_off_over_http_and_reader_model_when_nothing_can_run():
    body = post({"X-HushIQ-AI": "off"}, house=never_called()).json()
    assert body["ai"]["reason"] == "switched_off" and body["adjustment"] is None
    assert post({"X-HushIQ-AI": "off"}, body={"permits": ROWS, "reader": "model"}).status_code == 503


def test_rules_on_request_and_off_wins_over_them():
    body = post({}, body={"permits": ROWS, "as_of": AS_OF, "reader": "rules"}).json()
    assert body["reader"] == "rules" and body["adjustment"]["cites"] == [FACADE] and body["ai"]["mode"] == "rules"
    body = post({"X-HushIQ-AI": "off"}, body={"permits": ROWS, "as_of": AS_OF, "reader": "rules"}).json()
    assert body["ai"]["reason"] == "switched_off" and body["adjustment"] is None
