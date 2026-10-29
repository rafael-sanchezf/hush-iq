"""The three providers on a mock transport: the real OpenAI and Anthropic SDKs, with no network.

A turn is a list of (tool name, arguments) calls, a string for a reply with no tool call, an HTTP status code for an
error reply, or TIMEOUT. Every error body quotes the key, as OpenAI's 401 does, so a test can catch any path that
passes a provider's text through."""
import json

import anthropic
import httpx
import httpx2

from adjust import llm

TIMEOUT = "timeout"
HOSTS = {"meta": "api.meta.ai", "openai": "api.openai.com", "anthropic": "api.anthropic.com"}


class Wire:
    def __init__(self, provider, turns, key):
        self.provider, self.turns, self.key = provider, list(turns), key
        self.requests = []   # (host, path, auth header, body)

    def backend(self, model=None):
        lib = httpx2 if self.provider == "anthropic" else httpx
        transport = lib.MockTransport(self.handle)
        http = anthropic.DefaultHttpxClient(transport=transport) if lib is httpx2 else httpx.Client(transport=transport)
        return llm.client_for(self.provider, self.key, model, http_client=http)

    def connect(self, provider, key, model):
        assert provider == self.provider and key == self.key
        return self.backend(model)

    def handle(self, request):
        lib = httpx2 if self.provider == "anthropic" else httpx
        auth = request.headers.get("x-api-key") or request.headers.get("authorization")
        self.requests.append((request.url.host, request.url.path, auth, json.loads(request.content or b"{}")))
        assert self.turns, "the provider was called more times than scripted"
        turn = self.turns.pop(0)
        if turn == TIMEOUT:
            raise lib.ReadTimeout("timed out", request=request)
        if isinstance(turn, int):
            return lib.Response(turn, json={"type": "error", "error": {
                "type": "authentication_error", "code": "invalid_api_key",
                "message": f"Incorrect API key provided: {self.key}. The model you asked for may not exist."}})
        n = len(self.requests)
        return lib.Response(200, json=getattr(self, self.provider)(n, turn))

    @staticmethod
    def meta(n, turn):
        msg = {"role": "assistant", "content": turn} if isinstance(turn, str) else {
            "role": "assistant", "content": None, "tool_calls": [
                {"id": f"call_{n}_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for i, (name, args) in enumerate(turn)]}
        return {"id": f"chat_{n}", "object": "chat.completion", "created": 1, "model": "muse-spark-1.3",
                "choices": [{"index": 0, "message": msg, "finish_reason": "stop" if isinstance(turn, str) else "tool_calls"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
                          "completion_tokens_details": {"reasoning_tokens": 40}}}

    @staticmethod
    def openai(n, turn):
        output = [{"type": "reasoning", "id": f"rs_{n}", "summary": [], "encrypted_content": f"sealed-{n}"}]
        if isinstance(turn, str):
            output.append({"type": "message", "id": f"msg_{n}", "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": turn, "annotations": []}]})
        else:
            output += [{"type": "function_call", "id": f"fc_{n}_{i}", "call_id": f"call_{n}_{i}", "name": name,
                        "arguments": json.dumps(args), "status": "completed"} for i, (name, args) in enumerate(turn)]
        return {"id": f"resp_{n}", "object": "response", "created_at": 1, "model": "gpt-6.1-sol", "status": "completed",
                "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 40}}}

    @staticmethod
    def anthropic(n, turn):
        content = [{"type": "thinking", "thinking": "", "signature": f"sig-{n}"}]
        if isinstance(turn, str):
            content.append({"type": "text", "text": turn})
        else:
            content += [{"type": "tool_use", "id": f"toolu_{n}_{i}", "name": name, "input": args}
                        for i, (name, args) in enumerate(turn)]
        return {"id": f"msg_{n}", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
                "stop_reason": "end_turn" if isinstance(turn, str) else "tool_use", "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 50}}
