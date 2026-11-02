"""The AI switch and caller keys (AI_SWITCH contract): off, the house key, a caller's key for meta, openai or anthropic.

No live OpenAI or Anthropic call: the SDK clients are real, their transport is a mock (httpx2.MockTransport), so the
401, 429, timeout and bad-model paths raise the SDKs' own errors.
"""
import json
import logging

import anthropic
import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from conftest import FIELDS, load
from test_writer import GOOD
from verdict import api, mock, switch, writer

KEY = "sk-caller-LEAKCHECK-7f3a9c2e1b5d"
BODY = {"score": load("ludlow"), "fields": FIELDS["ludlow"]}
HOSTS = {"meta": "api.meta.ai", "openai": "api.openai.com", "anthropic": "api.anthropic.com"}


@pytest.fixture
def client():
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


def house(*script):
    """A house backend that would answer, so a test can show it was never called."""
    return mock.backend(*script, mode="json_schema")


def post(client, house_backend=None, **headers):
    api.app.dependency_overrides[api.get_backend] = lambda: house_backend
    names = {"ai": "X-HushIQ-AI", "provider": "X-HushIQ-Provider", "key": "X-HushIQ-Key", "model": "X-HushIQ-Model"}
    return client.post("/verdict", json=BODY, headers={names[k]: v for k, v in headers.items()})


def test_off_makes_no_model_call(client):
    h = house(GOOD)
    body = post(client, h, ai="off", key=KEY, provider="openai").json()
    assert body["writer"] == "template" and h.client.calls == []
    assert body["ai"] == {"mode": "basic", "provider": None, "model": None, "key": None, "reason": "switched_off",
                          "message": "AI reading is off, so this is the basic paragraph."}
    assert body["sentences"] and body["evidence"]


def test_no_headers_use_the_house_key(client):
    body = post(client, house(GOOD)).json()
    assert body["writer"] == "muse-spark-1.3" and body["sentences"] == GOOD["sentences"]
    assert body["ai"] == {"mode": "model", "provider": "meta", "model": "muse-spark-1.3", "key": "house",
                          "reason": None, "message": None}


def test_house_off_runs_basic_but_a_caller_key_still_works(client, monkeypatch):
    monkeypatch.setenv("HOUSE_AI", "off")
    h = house(GOOD)
    body = post(client, h).json()
    assert body["writer"] == "template" and h.client.calls == []
    assert body["ai"]["reason"] == "house_off" and "add your own key" in body["ai"]["message"]
    api.app.dependency_overrides[api.get_http_client] = lambda: _transports("success", [])
    body = post(client, h, provider="anthropic", key=KEY).json()
    assert body["writer"] == "claude-haiku-5-5" and body["ai"]["key"] == "caller" and h.client.calls == []
    assert client.get("/health").json()["house_ai"] == "off"


def test_no_key_anywhere_is_basic_not_an_error(client):
    r = post(client, None)
    assert r.status_code == 200 and r.json()["ai"]["reason"] == "no_key"
    body = post(client, house(GOOD), provider="openai").json()   # a provider named, no key: never the house key
    assert body["writer"] == "template"
    assert body["ai"]["reason"] == "no_key" and body["ai"]["provider"] == "openai" and "OpenAI key" in body["ai"]["message"]


@pytest.mark.parametrize("headers, says", [
    ({"ai": "maybe"}, "X-HushIQ-AI must be on or off"),
    ({"provider": "gemini", "key": KEY}, "X-HushIQ-Provider must be one of meta, openai, anthropic"),
    ({"provider": "openai", "key": KEY, "model": "gpt-0"}, "X-HushIQ-Model is not on the openai list"),
    ({"provider": "anthropic", "key": KEY, "model": "claude-opus-4-8"}, "X-HushIQ-Model is not on the anthropic list"),
    ({"model": KEY}, "X-HushIQ-Model is not on the meta list"),   # a key pasted in the wrong box is not echoed
    ({"provider": "openai", "key": KEY * 20}, "X-HushIQ-Key is not a key this server can send"),
])
def test_a_header_the_server_cannot_use_is_a_400_that_never_quotes_the_key(client, headers, says):
    r = post(client, house(GOOD), **headers)
    assert r.status_code == 400 and says in r.json()["detail"]
    assert KEY not in r.text


def test_openai_gets_a_strict_json_schema_and_no_temperature(lines):
    ls = lines("ludlow")
    b = writer.from_request("openai", KEY, client=mock.ScriptedClient(GOOD, mode="json_schema"))
    out = writer.write(ls, b)
    assert out["writer"] == "gpt-6-luna" and out["sentences"] == GOOD["sentences"]
    call = b.client.calls[0]
    assert call["model"] == "gpt-6-luna" and call["reasoning_effort"] == "low" and "temperature" not in call
    assert call["response_format"]["json_schema"]["strict"] is True and call["max_completion_tokens"] == 6000
    meta = writer.from_request("meta", KEY, "muse-spark-1.3", client=mock.ScriptedClient(GOOD, mode="json_schema"))
    writer.write(ls, meta)
    assert meta.client.calls[0]["temperature"] == 0.2   # Muse Spark's path is unchanged


def test_anthropic_gets_the_same_prompt_and_checks_through_output_config(lines, backend):
    ls = lines("ludlow")
    invented = {"sentences": [{"text": "It is very loud here.", "cites": ["E41"]}]}
    b = backend(invented, GOOD, mode="anthropic")
    out = writer.write(ls, b)
    assert out["writer"] == "claude-haiku-5-5" and out["sentences"] == GOOD["sentences"]
    assert out["trace"][0]["errors"] == ["sentence 1: cites E41, not in the evidence"]
    first, retry = b.client.calls
    assert first["system"].startswith(writer.SYSTEM) and first["model"] == "claude-haiku-5-5"
    fmt = first["output_config"]["format"]
    assert fmt["type"] == "json_schema" and first["output_config"]["effort"] == "low"
    assert fmt["schema"]["properties"]["sentences"]["items"]["properties"]["cites"]["items"]["enum"] == [l.id for l in ls]
    assert not {"temperature", "tool_choice", "tools"} & set(first)
    assert [m["role"] for m in retry["messages"]] == ["user"] and len(retry["messages"][0]["content"]) == 2
    assert "cites E41" in retry["messages"][0]["content"][1]["text"]


def test_anthropic_cut_off_at_max_tokens_is_retried_with_twice_the_room(lines, backend):
    b = backend({"_content_only": True, "content": "", "finish_reason": "length"}, GOOD, mode="anthropic")
    out = writer.write(lines("ludlow"), b)
    assert out["writer"] == "claude-haiku-5-5"
    assert out["trace"][0]["errors"] == ["the reply is empty (finish_reason length, ? completion tokens of 6000)"]
    assert [c["max_tokens"] for c in b.client.calls] == [6000, 12000]


def test_a_draft_refused_twice_says_checks_failed(client):
    invented = {"sentences": [{"text": "It is very loud here.", "cites": ["E41"]}]}
    body = post(client, house(invented, invented)).json()
    assert body["writer"] == "template"
    assert body["ai"]["mode"] == "basic" and body["ai"]["reason"] == "checks_failed" and body["ai"]["key"] == "house"


def test_the_eval_entry_takes_the_same_switch(lines):
    import verdict
    out = verdict.write(score=load("ludlow"), fields=FIELDS["ludlow"], ai="off", client=mock.ScriptedClient(GOOD))
    assert out["writer"] == "template" and out["ai"]["reason"] == "switched_off"
    scripted = mock.ScriptedClient(GOOD, mode="anthropic")
    out = verdict.write(score=load("ludlow"), fields=FIELDS["ludlow"], provider="anthropic", key=KEY, client=scripted)
    assert out["writer"] == "claude-haiku-5-5" and out["ai"]["key"] == "caller" and KEY not in json.dumps(out)


def test_redact_reaches_every_string():
    obj = {"a": [f"x{KEY}y", {"b": (KEY,)}], KEY: 1, "n": 3}
    assert KEY not in json.dumps(switch.redact(obj, KEY)) and switch.redact(obj, None) is obj


# ---- the key-leak test: a fake key through every path, through the real SDKs and the HTTP API ----

def _reply(provider):
    text = json.dumps(GOOD)
    if provider == "anthropic":
        return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
                "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 900, "output_tokens": 400}}
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 400, "total_tokens": 1300}}


def _transports(path, seen):
    """provider -> an SDK http client whose transport answers `path`. Every error body quotes the key back, the worst
    a provider could do."""
    def factory(provider):
        def handle(request):
            seen.append(request)
            if path == "timeout":
                raise httpx2.ReadTimeout("timed out", request=request)
            status = {"success": 200, "401": 401, "429": 429, "bad_model": 404}[path]
            if status == 200:
                return httpx2.Response(200, json=_reply(provider))
            msg = f"rejected: {KEY}"
            body = ({"type": "error", "error": {"type": "error", "message": msg}} if provider == "anthropic"
                    else {"error": {"message": msg, "type": "invalid_request_error", "code": None}})
            return httpx2.Response(status, json=body)
        sdk = anthropic if provider == "anthropic" else openai
        return sdk.DefaultHttpxClient(transport=httpx2.MockTransport(handle))
    return factory


@pytest.mark.parametrize("provider", ["meta", "openai", "anthropic"])
@pytest.mark.parametrize("path, writer_is_model, reason", [
    ("success", True, None),
    ("401", False, "key_rejected"),
    ("429", False, "provider_busy"),
    ("timeout", False, "provider_busy"),
    ("bad_model", False, "provider_error"),
])
def test_a_caller_key_never_leaks_and_never_falls_back_to_the_house(client, monkeypatch, caplog, capfd,
                                                                     provider, path, writer_is_model, reason):
    # Server-side settings a caller's request must never pick up.
    for k, v in {"OPENAI_BASE_URL": "https://elsewhere.example/v1", "ANTHROPIC_BASE_URL": "https://elsewhere.example",
                 "OPENAI_ORG_ID": "org-house", "OPENAI_PROJECT_ID": "proj-house",
                 "ANTHROPIC_AUTH_TOKEN": "house-token", "ANTHROPIC_API_KEY": "house-key"}.items():
        monkeypatch.setenv(k, v)
    caplog.set_level(logging.DEBUG)
    seen, h = [], house(GOOD)
    api.app.dependency_overrides[api.get_http_client] = lambda: _transports(path, seen)
    r = post(client, h, provider=provider, key=KEY)

    assert r.status_code == 200
    body = r.json()
    assert (body["writer"] != "template") is writer_is_model
    assert body["ai"]["mode"] == ("model" if writer_is_model else "basic")
    assert body["ai"]["reason"] == reason and body["ai"]["key"] == "caller" and body["ai"]["provider"] == provider
    assert h.client.calls == []                                   # never the house key
    assert len(seen) == 1                                         # one call, no SDK retry
    sent = seen[0]
    assert sent.url.host == HOSTS[provider]
    auth = sent.headers.get("authorization", "") + sent.headers.get("x-api-key", "")
    assert KEY in auth and "house" not in auth
    assert "openai-organization" not in sent.headers and "openai-project" not in sent.headers

    out, err = capfd.readouterr()
    assert KEY not in r.text and KEY not in json.dumps(body["trace"])
    assert KEY not in caplog.text and KEY not in out and KEY not in err
    assert caplog.records   # the SDKs did log at debug: the check above looked at something
