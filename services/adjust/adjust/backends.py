"""One model loop, three wire formats. (Hackathon work, Oct 29, HIQ-77.)

The permit reader's loop (`permits.model_read`) asks a backend for the model's next reply and hands it the tool
results. The backend speaks one provider's API; the prompt, the tools and every check stay in permits.py, so a reply
from any provider is held to the same checks.

    ChatBackend       Chat Completions, OpenAI SDK: Muse Spark at api.meta.ai, the request run live on Oct 28
    ResponsesBackend  the Responses API, OpenAI SDK: OpenAI's models, which take function tools only there
    MessagesBackend   the Messages API, Anthropic SDK: Claude

A failed call raises ProviderFailure, which carries a kind and a status code and nothing else. The provider's own
error text never leaves this module, because it can quote the key.
"""
import json
from dataclasses import dataclass, field

import openai

from . import config as A


class ProviderFailure(Exception):
    """key_rejected (401, 403), provider_busy (429, 529, a timeout) or provider_error (anything else)."""

    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind, self.status = kind, status


def failure(e):
    """An SDK exception, OpenAI's or Anthropic's, as a ProviderFailure: by class name and status code alone."""
    status = getattr(e, "status_code", None)
    name = type(e).__name__
    if status in (401, 403) or name in ("AuthenticationError", "PermissionDeniedError"):
        return ProviderFailure("key_rejected", status)
    if status in (429, 529) or name in ("RateLimitError", "OverloadedError", "APITimeoutError", "DeadlineExceededError"):
        return ProviderFailure("provider_busy", status)
    return ProviderFailure("provider_error", status)


@dataclass
class Reply:
    calls: list = field(default_factory=list)   # (call id, tool name, arguments as a JSON string)
    text: str = ""
    finish: str | None = None
    usage: dict | None = None
    declined: bool = False                       # the provider's own safety check declined the request


def as_backend(client, model):
    """A backend as it is, or an OpenAI-SDK client (house Muse Spark, or the scripted mock) wrapped for chat."""
    return client if hasattr(client, "start") and hasattr(client, "call") else ChatBackend(client, model)


def _fn(tool):
    return tool["function"]


# ---------------------------------------------------------------- Chat Completions (Meta)
class ChatBackend:
    def __init__(self, client, model=None):
        self.client, self.model = client, model

    def start(self, system, user, tools):
        self.tools = tools
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def call(self):
        try:
            resp = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tools,
                                                       tool_choice="auto", temperature=A.MODEL_TEMPERATURE,
                                                       max_tokens=A.MODEL_MAX_TOKENS)
        except openai.OpenAIError as e:
            raise failure(e) from None
        choice = resp.choices[0]
        msg = choice.message
        u = getattr(resp, "usage", None)
        details = getattr(u, "completion_tokens_details", None)
        usage = None if u is None else {
            "prompt_tokens": getattr(u, "prompt_tokens", None), "completion_tokens": getattr(u, "completion_tokens", None),
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details is not None else None}
        return Reply([(c.id, c.function.name, c.function.arguments) for c in msg.tool_calls or []],
                     msg.content or "", getattr(choice, "finish_reason", None), usage)

    def keep(self, reply):
        self.messages.append({"role": "assistant", "content": reply.text, "tool_calls": [
            {"id": i, "type": "function", "function": {"name": n, "arguments": a}} for i, n, a in reply.calls]}
            if reply.calls else {"role": "assistant", "content": reply.text})

    def answer(self, results):
        self.messages += [{"role": "tool", "tool_call_id": i, "content": c} for i, c in results]

    def say(self, text):
        self.messages.append({"role": "user", "content": text})


# ---------------------------------------------------------------- the Responses API (OpenAI)
class ResponsesBackend:
    """Nothing is stored at OpenAI (store off), so each call sends the whole conversation, and the model's reasoning
    items go back encrypted, as the API asks when nothing is stored."""

    def __init__(self, client, model):
        self.client, self.model = client, model

    def start(self, system, user, tools):
        self.system = system
        self.tools = [{"type": "function", "name": _fn(t)["name"], "description": _fn(t)["description"],
                       "parameters": _fn(t)["parameters"]} for t in tools]
        self.input = [{"role": "user", "content": user}]

    def call(self):
        try:
            resp = self.client.responses.create(model=self.model, instructions=self.system, input=self.input,
                                                tools=self.tools, tool_choice="auto",
                                                max_output_tokens=A.MODEL_MAX_TOKENS,
                                                reasoning={"effort": A.OPENAI_EFFORT}, store=False,
                                                include=["reasoning.encrypted_content"])
        except openai.OpenAIError as e:
            raise failure(e) from None
        self._output = list(resp.output or [])
        calls, text = [], []
        for item in self._output:
            if item.type == "function_call":
                calls.append((item.call_id, item.name, item.arguments))
            elif item.type == "message":
                text += [c.text for c in item.content or [] if getattr(c, "type", None) == "output_text"]
        u = getattr(resp, "usage", None)
        details = getattr(u, "output_tokens_details", None)
        usage = None if u is None else {
            "prompt_tokens": getattr(u, "input_tokens", None), "completion_tokens": getattr(u, "output_tokens", None),
            "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details is not None else None}
        incomplete = getattr(resp, "incomplete_details", None)
        return Reply(calls, "".join(text), getattr(incomplete, "reason", None) or getattr(resp, "status", None), usage)

    def keep(self, reply):
        self.input += [item.to_dict() for item in self._output]

    def answer(self, results):
        self.input += [{"type": "function_call_output", "call_id": i, "output": c} for i, c in results]

    def say(self, text):
        self.input.append({"role": "user", "content": text})


# ---------------------------------------------------------------- the Messages API (Anthropic)
class MessagesBackend:
    """tool_choice stays auto: the current Claude models refuse a forced tool call with a 400, so the prompt names
    the tools and the loop nudges a reply that has none, as it does for Muse Spark. Thinking is adaptive and always
    on; the assistant's content goes back exactly as it came, thinking blocks included."""

    def __init__(self, client, model):
        self.client, self.model = client, model

    def start(self, system, user, tools):
        self.system = system
        self.tools = [{"name": _fn(t)["name"], "description": _fn(t)["description"],
                       "input_schema": _fn(t)["parameters"]} for t in tools]
        self.messages = [{"role": "user", "content": user}]

    def call(self):
        import anthropic
        kw = dict(model=self.model, max_tokens=A.ANTHROPIC_MAX_TOKENS, system=self.system, messages=self.messages,
                  tools=self.tools, tool_choice={"type": "auto"}, output_config={"effort": A.ANTHROPIC_EFFORT})
        try:
            if self.model in A.ANTHROPIC_FALLBACK:   # a declined request is re-run server-side on the fallback model
                resp = self.client.beta.messages.create(**kw, betas=["server-side-fallback-2026-07-01"],
                                                        fallbacks="default")
            else:
                resp = self.client.messages.create(**kw)
        except anthropic.AnthropicError as e:
            raise failure(e) from None
        self._content = list(resp.content)
        u = getattr(resp, "usage", None)
        usage = None if u is None else {"prompt_tokens": getattr(u, "input_tokens", None),
                                        "completion_tokens": getattr(u, "output_tokens", None),
                                        "reasoning_tokens": None}   # thinking is inside output_tokens
        return Reply([(b.id, b.name, json.dumps(b.input)) for b in self._content if b.type == "tool_use"],
                     "".join(b.text for b in self._content if b.type == "text"), resp.stop_reason, usage,
                     declined=resp.stop_reason == "refusal")

    def keep(self, reply):
        self.messages.append({"role": "assistant", "content": self._content})

    def answer(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": i, "content": c} for i, c in results]})

    def say(self, text):
        self.messages.append({"role": "user", "content": text})
