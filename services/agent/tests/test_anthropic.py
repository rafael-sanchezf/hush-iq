"""The Anthropic adapter: the loop's Responses calls answered through the Messages API, against a fake Claude."""
import json

import pytest

from conftest import FakeScorer, fixture_text, listing, read
from fakes import KEY, FakeClaude, text, thinking, tool_use
from reader import anthropic_adapter, client, loop
from reader.client import make_client

FIELDS_01 = {"address": read("315 West 86th Street", "315 West 86th Street"),
             "unit": read("11C", "Apartment 11C"),
             "floor": read(11, "on the eleventh floor"),
             "side": read("rear", "The\nbedroom and the living room face the rear")}
PHOTO = '```json\n{"fields": {"side": {"status": "read", "value": "rear", "what": "back yards below the window"}}, ' \
        '"note": "a bedroom window over back yards"}\n```'


def test_a_listing_with_a_photo_through_claude():
    first = [thinking("sig-1"), text("I will look at the photo first."), tool_use("read_photo", {"indexes": [0]}, 1)]
    second = [thinking("sig-2"), tool_use("submit_listing", {"fields": dict(FIELDS_01, side=read("rear", photo=0))}, 2)]
    api = FakeClaude([first, second], photo=PHOTO)
    scorer = FakeScorer()
    result = loop.read(listing(fixture_text("01-stated-rear.txt"), photos=1), plan=make_client("anthropic", KEY,
                                                                                               transport=api),
                       scorer=scorer)

    assert result["status"] == "complete" and [t["tool"] for t in result["trace"]] == \
        ["read_photo", "submit_listing", "locate", "score"]
    assert result["ai"] == {"mode": "model", "provider": "anthropic", "model": "claude-opus-5-5", "key": "caller",
                            "reason": None, "message": None}
    assert result["fields"]["side"]["evidence"] == [{"source": "photo:0", "what": "back yards below the window"}]
    assert result["photo_readings"][0]["note"] == "a bedroom window over back yards"     # the fence was stripped
    assert result["trace"][0]["tokens"] == {"input": 1000, "output": 200, "reasoning": None}

    assert {(r[0], r[1]) for r in api.requests} == {("api.anthropic.com", KEY)}
    agent1, photo, agent2 = (r[3] for r in api.calls)
    assert agent1["system"] == loop.INSTRUCTIONS and agent1["model"] == "claude-opus-5-5"
    assert agent1["max_tokens"] == 16000 and agent1["cache_control"] == {"type": "ephemeral"}
    assert agent1["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert [t["name"] for t in agent1["tools"]] == ["read_photo", "submit_listing"]
    assert agent1["tools"][1]["input_schema"]["required"] == ["fields"]
    assert agent1["messages"] == [{"role": "user", "content": [{"type": "text", "text": loop.first_message(
        listing(fixture_text("01-stated-rear.txt"), photos=1))}]}]

    assert "tools" not in photo and photo["system"] == anthropic_adapter.JSON_ONLY
    image = photo["messages"][0]["content"][1]
    assert image["type"] == "image" and image["source"]["type"] == "base64"
    assert image["source"]["media_type"] == "image/png"

    # The second turn replays the first exactly as Claude sent it, thinking block and signature included, then
    # answers its tool call.
    assert agent2["messages"][1] == {"role": "assistant", "content": first}
    assert agent2["messages"][2]["role"] == "user"
    result_block = agent2["messages"][2]["content"][0]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "toolu_1"
    assert json.loads(result_block["content"])["photos"][0]["index"] == 0


def test_refusals_go_back_to_claude_and_the_last_turn_follows_the_tool_result():
    invented = dict(FIELDS_01, floor=read(11, "11th floor, rear"))
    api = FakeClaude([[tool_use("submit_listing", {"fields": invented}, 1)],
                      [tool_use("submit_listing", {"fields": FIELDS_01}, 2)]])
    result = loop.read(listing(fixture_text("01-stated-rear.txt")), plan=make_client("anthropic", KEY, transport=api),
                       scorer=None, turns=2)

    assert result["status"] == "complete" and result["trace"][0]["result"]["refused"]["floor"]
    last = api.calls[1][3]["messages"][-1]["content"]
    assert [b["type"] for b in last] == ["tool_result", "text"] and last[1]["text"] == loop.LAST_TURN


def test_an_assistant_turn_that_did_not_come_from_claude_is_rebuilt():
    turns = anthropic_adapter._messages([
        {"role": "user", "content": "Read this listing."},
        {"type": "function_call", "call_id": "c1", "name": "read_photo", "arguments": '{"indexes": [0]}'},
        {"type": "function_call_output", "call_id": "c1", "output": '{"photos": []}'},
    ])
    assert turns == [{"role": "user", "content": [{"type": "text", "text": "Read this listing."}]},
                     {"role": "assistant", "content": [{"type": "tool_use", "id": "c1", "name": "read_photo",
                                                        "input": {"indexes": [0]}}]},
                     {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1",
                                                   "content": '{"photos": []}'}]}]


def test_an_image_that_is_not_a_data_url_is_a_400():
    with pytest.raises(ValueError, match="base64 data URLs"):
        anthropic_adapter._user_blocks([{"type": "input_image", "image_url": "https://example.com/a.jpg"}])


@pytest.mark.parametrize("fail, reason", [("401", "key_rejected"), ("429", "provider_busy"), ("529", "provider_busy"),
                                          ("404", "provider_error"), ("timeout", "provider_error")])
def test_claude_failing_runs_basic(monkeypatch, fail, reason):
    monkeypatch.setattr(client, "CALLER_RETRIES", 0)
    api = FakeClaude(fail=fail)
    result = loop.read(listing(fixture_text("03-street-front.txt")), plan=make_client("anthropic", KEY, transport=api),
                       scorer=None)
    assert result["ai"]["mode"] == "basic" and result["ai"]["reason"] == reason
    assert result["ai"]["message"].startswith("Anthropic")
    assert result["fields"]["side"]["value"] == "street" and len(api.calls) == 1
