"""Claude behind the loop's Responses calls. (Hackathon work, Oct 29.)

The loop and the photo reader speak the Responses API (client.responses.create). For a caller's Anthropic key,
client() returns the same OpenAI client, but its transport answers POST /responses by calling the Messages API
with the Anthropic SDK and translating the reply back, the way mock.py's transport answers it offline. The loop,
the tools and every check stay as they are, so Claude is held to exactly the checks Muse is held to.

    Responses request                          Messages request
    instructions                           ->  system
    input  user text, input_text           ->  user text block
           input_image (a data URL)        ->  user image block, base64
           function_call_output            ->  user tool_result block
           reasoning + message +           ->  the assistant turn, replayed exactly as Claude sent it
           function_call (one response)
    tools (function)                       ->  tools (input_schema)
    parallel_tool_calls false              ->  tool_choice auto with disable_parallel_tool_use
    text.format json_object                ->  one line more in the system prompt; a code fence is stripped
    max_output_tokens                      ->  max_tokens, at least 16,000 (thinking counts against it)

Claude's reply comes back as a reasoning item whose encrypted_content is the whole assistant content as JSON
(thinking blocks must go back unchanged, so the next request replays them from there), then its text as a
message and each tool_use as a function_call. Anthropic's errors come back as the same HTTP status, so the
OpenAI SDK raises the matching error and the loop treats Claude's failures like any provider's.
"""
import json
import re

import anthropic
import httpx
from openai import OpenAI

ADAPTER_URL = "https://anthropic-adapter.invalid/v1"   # never dialled: the transport answers it in process
MIN_MAX_TOKENS = 16000
JSON_ONLY = "Return only the JSON object: no code fence and no other text."
_DATA_URL = re.compile(r"data:(image/[a-z]+);base64,(.+)", re.S)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def client(key, base_url, *, transport=None, max_retries=1, timeout=60):
    """An OpenAI client whose Responses calls go to Claude. The key goes only into the Anthropic client, which
    talks only to base_url. transport (tests) replaces the Anthropic client's httpx2 transport."""
    claude = anthropic.Anthropic(api_key=key, base_url=base_url, max_retries=max_retries, timeout=timeout,
                                 http_client=anthropic.DefaultHttpxClient(transport=transport) if transport else None)
    return OpenAI(api_key="adapter", base_url=ADAPTER_URL, max_retries=0, timeout=timeout,
                  http_client=httpx.Client(transport=MessagesTransport(claude)))


class MessagesTransport(httpx.BaseTransport):
    def __init__(self, claude):
        self.claude = claude
        self.n = 0

    def handle_request(self, request):
        if request.method != "POST" or not request.url.path.endswith("/responses"):
            return httpx.Response(404, json={"error": {"message": "the Anthropic adapter answers POST /responses only"}})
        body = json.loads(request.content or b"{}")
        try:
            params = to_messages(body)
        except ValueError as e:
            return httpx.Response(400, json={"error": {"message": str(e), "type": "invalid_request_error"}})
        try:
            reply = self.claude.messages.create(**params)
        except anthropic.APITimeoutError:
            raise httpx.ReadTimeout("Anthropic did not answer in time", request=request)
        except anthropic.APIConnectionError:
            raise httpx.ConnectError("could not reach Anthropic", request=request)
        except anthropic.APIStatusError as e:
            return httpx.Response(e.status_code, json={"error": {"message": e.message, "type": "anthropic_error"}})
        self.n += 1
        return httpx.Response(200, json=to_response(reply, self.n, json_mode=_json_mode(body)))


def to_messages(body):
    """The Messages API arguments for one Responses request."""
    params = {"model": body["model"], "max_tokens": max(body.get("max_output_tokens") or 0, MIN_MAX_TOKENS),
              "messages": _messages(body.get("input") or []), "cache_control": {"type": "ephemeral"}}
    system = body.get("instructions") or ""
    if _json_mode(body):
        system = f"{system}\n\n{JSON_ONLY}".strip()
    if system:
        params["system"] = system
    functions = [t for t in body.get("tools") or [] if t.get("type") == "function"]
    if functions:
        params["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]}
                           for t in functions]
        params["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": body.get("parallel_tool_calls") is False}
    return params


def to_response(reply, n, json_mode=False):
    """A Responses API body for one Claude reply."""
    content = [b.model_dump(mode="json", exclude_none=True) for b in reply.content]
    output = [{"type": "reasoning", "id": f"rs_{n}", "summary": [], "encrypted_content": json.dumps(content)}]
    text = "".join(b.get("text", "") for b in content if b["type"] == "text")
    if json_mode and (m := _FENCE.match(text)):
        text = m.group(1)
    if text.strip():
        output.append({"type": "message", "id": f"msg_{n}", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    for i, b in enumerate(b for b in content if b["type"] == "tool_use"):
        output.append({"type": "function_call", "id": f"fc_{n}_{i}", "call_id": b["id"], "name": b["name"],
                       "arguments": json.dumps(b["input"]), "status": "completed"})
    u = reply.usage
    usage = {"input_tokens": u.input_tokens + (u.cache_creation_input_tokens or 0) + (u.cache_read_input_tokens or 0),
             "output_tokens": u.output_tokens}
    return {"id": f"resp_claude_{n}", "object": "response", "created_at": 0, "model": reply.model,
            "status": "incomplete" if reply.stop_reason == "max_tokens" else "completed", "output": output,
            "usage": dict(usage, total_tokens=usage["input_tokens"] + usage["output_tokens"]),
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": []}


def _messages(items):
    """Responses input items as Messages turns. Consecutive items of one role share a turn, and an assistant turn
    is replayed from its reasoning item, exactly as Claude sent it."""
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    turns, replaying = [], False
    for item in items:
        kind = item.get("type") or "message"
        if kind == "reasoning" and item.get("encrypted_content"):
            _add(turns, "assistant", json.loads(item["encrypted_content"]))
            replaying = True
        elif kind == "function_call" or (kind == "message" and item.get("role") == "assistant"):
            if not replaying:      # an assistant turn that did not come from Claude: rebuild it
                _add(turns, "assistant", _assistant_blocks(item))
        elif kind == "function_call_output":
            output = item.get("output")
            _add(turns, "user", [{"type": "tool_result", "tool_use_id": item["call_id"],
                                  "content": output if isinstance(output, str) else json.dumps(output)}])
            replaying = False
        elif kind == "message":
            _add(turns, "user", _user_blocks(item.get("content")))
            replaying = False
    return turns


def _add(turns, role, blocks):
    if turns and turns[-1]["role"] == role:
        turns[-1]["content"].extend(blocks)
    else:
        turns.append({"role": role, "content": list(blocks)})


def _assistant_blocks(item):
    if item.get("type") == "function_call":
        return [{"type": "tool_use", "id": item["call_id"], "name": item["name"],
                 "input": json.loads(item.get("arguments") or "{}")}]
    return [{"type": "text", "text": c["text"]} for c in item.get("content") or [] if c.get("text")]


def _user_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks = []
    for c in content or []:
        if c.get("type") in ("input_text", "text"):
            blocks.append({"type": "text", "text": c["text"]})
        elif c.get("type") == "input_image":
            m = _DATA_URL.fullmatch(c.get("image_url") or "")
            if not m:
                raise ValueError("the Anthropic adapter takes images as base64 data URLs")
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}})
    return blocks


def _json_mode(body):
    return ((body.get("text") or {}).get("format") or {}).get("type") == "json_object"
