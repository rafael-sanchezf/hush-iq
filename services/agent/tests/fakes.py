"""The providers' APIs answered in process, so caller keys are tested without a network or a real key.

    FakeOpenAI   api.openai.com or api.meta.ai (httpx): POST /responses, GET /models
    FakeClaude   api.anthropic.com (httpx2, as the Anthropic SDK uses): POST /v1/messages, GET /v1/models

fail="401" | "429" | "404" | "529" | "timeout" makes every call fail that way. A failure's message quotes the key
in full, the worst a provider could do, so the tests show the reader takes it out. Both record every request.
"""
import json
import re

import httpx
import httpx2

from reader import mock

KEY = "sk-test-FAKE-0123456789abcdef"


def _error(fail, key, kind):
    message = {"401": f"Incorrect API key provided: {key}", "429": f"Rate limit reached for key {key}",
               "404": "The model does not exist or you do not have access to it.",
               "529": "Overloaded"}[fail]
    if kind == "anthropic":
        return {"type": "error", "error": {"type": "error", "message": message}}
    return {"error": {"message": message, "type": "invalid_request_error", "code": None}}


class FakeOpenAI(httpx.BaseTransport):
    def __init__(self, responder=None, models=("gpt-6-luna", "muse-spark-1.3"), fail=None):
        self.responder = responder or mock.HeuristicModel()
        self.models, self.fail = models, fail
        self.requests = []      # (host, authorization, path, body)

    def handle_request(self, request):
        auth = request.headers.get("authorization", "")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.url.host, auth, request.url.path, body))
        if self.fail == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if self.fail:
            return httpx.Response(int(self.fail), json=_error(self.fail, auth.removeprefix("Bearer "), "openai"))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": m, "object": "model", "created": 0, "owned_by": "x"} for m in self.models]})
        return httpx.Response(200, json=mock._response_body(self.responder(body) or {}, len(self.requests)))


def thinking(signature="sig"):
    return {"type": "thinking", "thinking": "", "signature": signature}


def tool_use(name, arguments, n=1):
    return {"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": arguments}


def text(value):
    return {"type": "text", "text": value}


class FakeClaude(httpx2.BaseTransport):
    """turns: the agent's replies in order, each a list of content blocks; with none left, it submits what
    mock.heuristic_fields reads. photo: the text a photo reading returns."""

    def __init__(self, turns=None, photo='{"fields": {}, "note": "a room"}', models=("claude-opus-5-5",), fail=None):
        self.turns, self.photo, self.models, self.fail = list(turns or []), photo, models, fail
        self.requests = []      # (host, key, path, body)

    def handle_request(self, request):
        # anthropic 2.x sends the key as a bearer token; older versions used x-api-key
        key = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.url.host, key, request.url.path, body))
        if self.fail == "timeout":
            raise httpx2.ReadTimeout("timed out", request=request)
        if self.fail:
            return httpx2.Response(int(self.fail), json=_error(self.fail, key, "anthropic"))
        if request.url.path.endswith("/models"):
            return httpx2.Response(200, json={"data": [
                {"id": m, "type": "model", "display_name": m, "created_at": "2026-01-01T00:00:00Z"} for m in self.models],
                "has_more": False, "first_id": None, "last_id": None})
        if "tools" not in body:
            content, stop = [text(self.photo)], "end_turn"
        elif self.turns:
            content, stop = self.turns.pop(0), "tool_use"
        else:
            first = body["messages"][0]["content"]
            listing = first if isinstance(first, str) else first[0]["text"]
            m = re.search(r"<<<\n(.*)\n>>>", listing, re.S)
            content = [tool_use("submit_listing", {"fields": mock.heuristic_fields(m.group(1) if m else "")},
                                len(self.requests))]
            stop = "tool_use"
        return httpx2.Response(200, json={
            "id": f"msg_{len(self.requests)}", "type": "message", "role": "assistant", "model": body["model"],
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0}})

    @property
    def calls(self):
        return [r for r in self.requests if r[2].endswith("/messages")]
