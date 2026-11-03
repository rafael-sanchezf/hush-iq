"""make_client: which model a request gets, the OpenAI path, key checks, and no way back to the house key."""
import pytest

from conftest import FakeScorer, fixture_text, listing
from fakes import KEY, FakeClaude, FakeOpenAI
from reader import client, loop, settings
from reader.client import BadChoice, make_client

HOUSE = "house-key-for-tests-0123456789"


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(client, "CALLER_RETRIES", 0)
    monkeypatch.setattr(client, "MAX_RETRIES", 0)


@pytest.mark.parametrize("kwargs, env, want", [
    ({"ai": "off"}, {"MODEL_API_KEY": HOUSE}, ("basic", None, None, "switched_off")),
    ({"ai": "off", "provider": "openai", "key": KEY}, {}, ("basic", None, None, "switched_off")),
    ({}, {"MODEL_API_KEY": HOUSE, "HOUSE_AI": "off"}, ("basic", "meta", "house", "house_off")),
    ({}, {"MODEL_API_KEY": HOUSE, "READER_MODE": "mock"}, ("basic", "meta", "house", "house_off")),
    ({}, {}, ("basic", "meta", "house", "no_key")),
    ({"provider": "openai"}, {"MODEL_API_KEY": HOUSE}, ("basic", "openai", None, "no_key")),
    ({"provider": "anthropic"}, {"MODEL_API_KEY": HOUSE}, ("basic", "anthropic", None, "no_key")),
    ({}, {"MODEL_API_KEY": HOUSE}, ("model", "meta", "house", None)),
    ({"provider": "openai", "key": KEY}, {"HOUSE_AI": "off"}, ("model", "openai", "caller", None)),
    ({"provider": "anthropic", "key": KEY}, {}, ("model", "anthropic", "caller", None)),
    ({"provider": "META", "key": KEY, "ai": "ON"}, {}, ("model", "meta", "caller", None)),
])
def test_what_a_request_gets(monkeypatch, kwargs, env, want):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    plan = make_client(**kwargs)
    ai = plan.ai
    assert (ai["mode"], ai["provider"], ai["key"], ai["reason"]) == want
    assert (ai["message"] is None) == (ai["mode"] == "model")
    assert plan.mode == ("live" if ai["mode"] == "model" else "mock")


def test_messages_name_the_provider_and_whose_key():
    assert client.message("no_key", "anthropic") == ("Anthropic needs your own API key: add it in settings. The basic "
                                                     "reader read this listing.")
    assert client.message("key_rejected", "openai", "caller").startswith("OpenAI rejected your key")
    assert client.message("house_off", "meta", "house") == ("AI reading is off. Add your own key in settings to turn "
                                                            "it on.")


@pytest.mark.parametrize("kwargs, message", [
    ({"ai": "maybe"}, "X-HushIQ-AI must be one of on, off"),
    ({"provider": "gemini"}, "X-HushIQ-Provider must be one of meta, openai, anthropic"),
    ({"provider": "openai", "model": "gpt-4o"}, "'gpt-4o' is not one of openai's models"),
    ({"provider": "anthropic", "model": "claude-3-opus"}, "is not one of anthropic's models: claude-opus-5-5"),
    ({"model": "gpt-6-luna"}, "is not one of meta's models: muse-spark-1.3"),
])
def test_bad_choices_are_refused(kwargs, message):
    with pytest.raises(BadChoice, match=message):
        make_client(**kwargs)


def test_defaults_and_fixed_base_urls(monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE_URL", "https://example.invalid/v1")   # the house's setting, not a caller's
    assert make_client("openai", KEY).model == "gpt-6-luna"
    assert make_client("anthropic", KEY).model == "claude-opus-5-5"
    assert str(make_client("meta", KEY).client.base_url) == "https://api.meta.ai/v1/"
    assert str(make_client("openai", KEY).client.base_url) == "https://api.openai.com/v1/"
    assert str(make_client("anthropic", KEY).client._client._transport.claude.base_url).rstrip("/") == \
        "https://api.anthropic.com"
    assert make_client("openai", KEY, "gpt-6.1-sol").model == "gpt-6.1-sol"
    assert KEY not in repr(make_client("openai", KEY))


def test_the_openai_path_sends_encrypted_reasoning_and_loose_tools(scorer):
    api = FakeOpenAI()
    plan = make_client("openai", KEY, transport=api)
    result = loop.read(listing(fixture_text("03-street-front.txt")), plan=plan, scorer=scorer)

    assert result["status"] == "complete" and result["ai"]["mode"] == "model"
    assert result["ai"] == {"mode": "model", "provider": "openai", "model": "gpt-6-luna", "key": "caller",
                            "reason": None, "message": None}
    host, auth, path, body = api.requests[0]
    assert (host, auth, path) == ("api.openai.com", f"Bearer {KEY}", "/v1/responses")
    assert body["include"] == ["reasoning.encrypted_content"] and body["model"] == "gpt-6-luna"
    assert [t["strict"] for t in body["tools"]] == [False, False]
    assert result["mode"] == "live" and result["model"] == "gpt-6-luna"


def test_the_house_meta_path_is_unchanged(monkeypatch, scorer):
    monkeypatch.setenv("MODEL_API_KEY", HOUSE)
    api = FakeOpenAI()
    result = loop.read(listing(fixture_text("03-street-front.txt")), plan=make_client(transport=api), scorer=scorer)
    host, auth, _, body = api.requests[0]
    assert (host, auth) == ("api.meta.ai", f"Bearer {HOUSE}")
    assert "include" not in body and all("strict" not in t for t in body["tools"])
    assert result["ai"]["key"] == "house" and result["model"] == settings.DEFAULT_MODEL


@pytest.mark.parametrize("fail, reason", [("401", "key_rejected"), ("429", "provider_busy"),
                                          ("404", "provider_error"), ("timeout", "provider_error")])
def test_a_failing_caller_key_runs_basic_and_never_the_house_key(monkeypatch, fast, fail, reason):
    monkeypatch.setenv("MODEL_API_KEY", HOUSE)
    api = FakeOpenAI(fail=fail)
    scorer = FakeScorer()
    result = loop.read(listing(fixture_text("03-street-front.txt")), plan=make_client("openai", KEY, transport=api),
                       scorer=scorer)

    assert {r[1] for r in api.requests} == {f"Bearer {KEY}"}          # the caller's key, to OpenAI, and nothing else
    assert result["ai"]["mode"] == "basic" and result["ai"]["reason"] == reason
    assert result["ai"]["provider"] == "openai" and result["ai"]["key"] == "caller"
    assert result["ai"]["message"] == client.message(reason, "openai", "caller")
    assert result["trace"][0]["result"]["reason"] == reason and result["trace"][0]["ok"] is False
    assert result["status"] == "complete" and result["fields"]["address"]["value"] == "155 Ludlow Street"
    assert result["mode"] == "mock" and result["turns"]["used"] == 2


@pytest.mark.parametrize("provider, api, model, ok, message", [
    ("openai", FakeOpenAI(), None, True, "OpenAI accepted the key, and gpt-6-luna is available."),
    ("openai", FakeOpenAI(), "gpt-6.1-sol", False, "OpenAI accepted the key, but gpt-6.1-sol is not available to it."),
    ("openai", FakeOpenAI(fail="401"), None, False, "OpenAI rejected this key."),
    ("openai", FakeOpenAI(fail="429"), None, False, "OpenAI is rate-limiting this key right now. Try again in a minute."),
    ("openai", FakeOpenAI(fail="timeout"), None, False, "Could not reach OpenAI to check the key. Try again later."),
    ("meta", FakeOpenAI(), None, True, "Meta accepted the key, and muse-spark-1.3 is available."),
    ("anthropic", FakeClaude(), None, True, "Anthropic accepted the key, and claude-opus-5-5 is available."),
    ("anthropic", FakeClaude(fail="401"), None, False, "Anthropic rejected this key."),
    ("anthropic", FakeClaude(fail="529"), None, False, "Anthropic is rate-limiting this key right now. Try again in a minute."),
])
def test_check_key(fast, provider, api, model, ok, message):
    assert client.check_key(provider, KEY, model, transport=api) == {"ok": ok, "provider": provider, "message": message}
    host = {"openai": "api.openai.com", "meta": "api.meta.ai", "anthropic": "api.anthropic.com"}[provider]
    assert {r[0] for r in api.requests} == {host} and all(r[2].endswith("/models") for r in api.requests)


def test_check_key_without_a_key():
    assert client.check_key("openai", None) == {"ok": False, "provider": "openai",
                                                "message": "No key sent: put it in the X-HushIQ-Key header."}
