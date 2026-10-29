"""The writer: a Meta model drafts the paragraph, the checks in validate.py decide whether a renter reads it.

    lines -> prompt -> model -> parse -> validate.check
      pass                    -> the model's sentences
      fail                    -> one retry with the errors listed -> pass, or the template
      timeout or API error    -> the template, at once

Two backends behind one interface, both through the OpenAI SDK:

  muse-spark-open  meta-models/muse-spark-open-1026 on Baseten (https://inference.baseten.co/v1, BASETEN_API_KEY).
                   Baseten's docs say this model accepts a json_schema response_format but does not enforce it, so
                   the reply comes back as one forced tool call whose parameters are the schema.
  muse-spark-1.3   muse-spark-1.3 on the Meta Model API (https://api.meta.ai/v1, MODEL_API_KEY), with
                   response_format json_schema and strict on.

In both, `cites` is an enum of the ids actually sent. Neither schema is trusted: the checks run on every reply.
With no key the template writes (the mock-mode default); tests pass a scripted client instead of a real one.

A caller's own key (AI_SWITCH contract, HIQ-76) gets a backend built for that one request by `from_request`: meta and
openai through the OpenAI SDK with a strict json_schema, anthropic through the Anthropic SDK with a strict
`output_config.format`. Same prompt, same checks, same retry-then-template for every provider.
"""
import importlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import template, validate

TOOL_NAME = "submit_verdict"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

SYSTEM = """You write the "what you'll hear" paragraph for one renter looking at one New York City apartment.

The user message holds numbered evidence lines (E1, E2, ...): the verdict for this renter, how each noise source
ranks against Manhattan, the weight each source got and why, what the city's records show near the building, the
renter's sleep hours and answers, and the floor and side used. Nothing else is known about this apartment.

Write 3 to 5 short sentences to the renter ("you") on what they will hear here and when, for the way they sleep.
Keep each sentence to one point and under 30 words. Choose what matters most for this renter; do not list every line.
Start with the verdict. Then the sources that matter most for them, the loudest and the ones they said bother them,
each with one concrete record (the nearest bar, road or hospital, or a 311 count). End with the floor and side used;
when the evidence gives a loudest and a quietest case because the listing was silent, give that range.

Write as a person would say it, not as the lines are written: verdict words in lowercase inside a sentence ("very
loud", "quiet"); a rank of 0% as "among the loudest in Manhattan"; no "for local businesses" or "of 6" tails copied over;
no first person ("I", "we"): the paragraph speaks for the evidence.

Code checks every reply and rejects one that breaks any of these rules:
1. Each sentence lists in cites the ids of the lines it states, and only ids from the evidence.
2. Every number in a sentence appears, written the same way, in a line that sentence cites. Do not compute, round,
   convert or add up numbers.
3. Every name (a street, a building, a hospital, a station, a borough) in a sentence appears in a line it cites.
4. Mention a kind of source (subway, bar, hospital, construction, traffic) only if a line it cites mentions it.
5. No decibels and no sound levels. The ranks are comparisons, not measurements: say "quieter than 34% of
   Manhattan apartments".
6. No ids in the text, and no sentence over 300 characters.
7. Give a reason only where a cited line gives that reason. No advice, no sales talk, no adjectives the lines do not
   support."""

FINISH = {"tool": f"Answer by calling {TOOL_NAME} once.", "json_schema": "Answer with the JSON object only.",
          "anthropic": "Answer with the JSON object only."}


def reply_schema(ids):
    """The reply's JSON schema, with cites limited to the ids sent. Kept to keywords both hosts document for strict
    mode (no minItems or maxItems); the counts are checked in code."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["sentences"],
        "properties": {"sentences": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "cites"],
            "properties": {"text": {"type": "string"},
                           "cites": {"type": "array", "items": {"type": "string", "enum": list(ids)}}},
        }}},
    }


def messages(lines, rejected=None):
    """The prompt. On the retry, the rejected reply and every error it drew go back to the model."""
    evidence = "\n".join(f"{l.id}: {l.text}" for l in lines)
    out = [{"role": "user", "content": f"Evidence:\n{evidence}\n\nWrite the paragraph."}]
    if rejected:
        raw, errors = rejected
        out.append({"role": "user", "content": "Your reply was rejected by the checks:\n"
                    + "\n".join(f"- {e}" for e in errors)
                    + f"\n\nYour reply was:\n{(raw or '')[:3000]}\n\nWrite the whole reply again with every problem fixed."})
    return out


@dataclass
class Backend:
    name: str        # the reply's "writer"
    model: str
    mode: str        # "tool" (Baseten, Muse Spark Open) or "json_schema" (Meta Model API, Muse Spark 1.3)
    client: object   # an openai.OpenAI, or anything with .chat.completions.create
    max_tokens: int = 6000          # reasoning tokens count against it (up to 3,500 seen at effort low); too few
                                    # comes back as empty content with no error
    reasoning_effort: str | None = None
    temperature: float | None = 0.2  # None for OpenAI's reasoning models, which take only their default

    def complete(self, lines, rejected=None, max_tokens=None):
        """One call -> (the raw reply text, JSON and unchecked; what the host said about it: finish reason, tokens)."""
        budget = max_tokens or self.max_tokens
        ids = [l.id for l in lines]
        msgs = [{"role": "system", "content": f"{SYSTEM}\n\n{FINISH[self.mode]}"}] + messages(lines, rejected)
        kw = {"model": self.model, "messages": msgs}
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        if self.mode == "json_schema":   # the Meta Model API and OpenAI: max_tokens is a deprecated alias there
            kw["max_completion_tokens"] = budget
        else:
            kw["max_tokens"] = budget
        if self.reasoning_effort:
            kw["reasoning_effort"] = self.reasoning_effort
        if self.mode == "tool":
            kw["tools"] = [{"type": "function", "function": {
                "name": TOOL_NAME, "strict": True, "parameters": reply_schema(ids),
                "description": "Submit the paragraph: sentences, each with the evidence ids it states."}}]
            kw["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
        else:
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "verdict", "schema": reply_schema(ids), "strict": True}}
        resp = self.client.chat.completions.create(**kw)
        choice = resp.choices[0]
        meta = {"finish_reason": getattr(choice, "finish_reason", None), **_usage(getattr(resp, "usage", None))}
        for call in getattr(choice.message, "tool_calls", None) or []:
            if call.function.name == TOOL_NAME:
                return call.function.arguments, meta
        return choice.message.content or "", meta   # a host may answer in the content anyway; the checks decide


@dataclass
class AnthropicBackend:
    """Claude through the Anthropic SDK's Messages API. The reply schema goes in `output_config.format`: forcing a
    tool call (`tool_choice` tool) is refused with a 400 by Claude Opus 5.5 and Sonnet 5.5. No temperature: API
    version 2026-10-21 refuses every sampling parameter."""
    name: str
    model: str
    client: object   # an anthropic.Anthropic, or anything with .messages.create
    max_tokens: int = 6000   # thinking is on by default and counts against it
    reasoning_effort: str | None = "low"
    mode: str = field(default="anthropic", init=False)

    def complete(self, lines, rejected=None, max_tokens=None):
        budget = max_tokens or self.max_tokens
        output_config = {"format": {"type": "json_schema", "schema": reply_schema([l.id for l in lines])}}
        if self.reasoning_effort:
            output_config["effort"] = self.reasoning_effort
        # one user turn: the evidence, and on the retry the rejected reply and its errors
        content = [{"type": "text", "text": m["content"]} for m in messages(lines, rejected)]
        resp = self.client.messages.create(model=self.model, max_tokens=budget, system=f"{SYSTEM}\n\n{FINISH[self.mode]}",
                                           messages=[{"role": "user", "content": content}], output_config=output_config)
        stop = getattr(resp, "stop_reason", None)
        u = getattr(resp, "usage", None)
        meta = {"finish_reason": {"max_tokens": "length", "end_turn": "stop"}.get(stop, stop),
                **{k: v for k, v in (("prompt_tokens", getattr(u, "input_tokens", None)),
                                     ("completion_tokens", getattr(u, "output_tokens", None))) if v is not None}}
        return next((b.text for b in resp.content if getattr(b, "type", None) == "text"), ""), meta


def _usage(u):
    """Token counts as the host reports them, reasoning included where it says so."""
    if u is None:
        return {}
    out = {k: getattr(u, k, None) for k in ("prompt_tokens", "completion_tokens")}
    details = getattr(u, "completion_tokens_details", None)
    if details is not None and getattr(details, "reasoning_tokens", None) is not None:
        out["reasoning_tokens"] = details.reasoning_tokens
    return {k: v for k, v in out.items() if v is not None}


HOSTS = {
    "muse-spark-open": {"mode": "tool", "key": "BASETEN_API_KEY", "model": "meta-models/muse-spark-open-1026",
                        "model_env": "BASETEN_MODEL", "base_url": "https://inference.baseten.co/v1",
                        "base_url_env": "BASETEN_BASE_URL"},
    "muse-spark-1.3": {"mode": "json_schema", "key": "MODEL_API_KEY", "model": "muse-spark-1.3",
                       "model_env": "MODEL_NAME", "base_url": "https://api.meta.ai/v1", "base_url_env": "MODEL_BASE_URL"},
}


def load_env(path=ENV_FILE):
    """KEY=VALUE lines from services/verdict/.env, without overriding what the shell already set."""
    try:
        text = Path(path).read_text()
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def from_env(env=None, client=None):
    """The configured backend, or None for the template. VERDICT_BACKEND picks one (auto, muse-spark-open,
    muse-spark-1.3, template); auto takes Muse Spark Open when its key is set, then Muse Spark 1.3."""
    if env is None:
        load_env()
        env = os.environ
    choice = env.get("VERDICT_BACKEND", "auto").strip() or "auto"
    if choice == "template":
        return None
    names = [choice] if choice in HOSTS else [n for n in HOSTS if env.get(HOSTS[n]["key"]) or client is not None]
    for name in names:
        host = HOSTS[name]
        if client is None and not env.get(host["key"]):
            continue
        if client is None:
            from openai import OpenAI   # imported here so the template path needs no SDK
            c = OpenAI(api_key=env[host["key"]], base_url=env.get(host["base_url_env"], host["base_url"]),
                       timeout=float(env.get("VERDICT_TIMEOUT_S", 25)), max_retries=0)
        else:
            c = client
        effort = env.get("VERDICT_REASONING_EFFORT", "low" if host["mode"] == "json_schema" else "").strip()
        return Backend(name=name, model=env.get(host["model_env"], host["model"]), mode=host["mode"], client=c,
                       max_tokens=int(env.get("VERDICT_MAX_TOKENS", 6000)), reasoning_effort=effort or None)
    return None


# The providers a caller's own key may name (X-HushIQ-Provider). The base URL is fixed here, never read from the env or
# the request, so a key can only go to its own provider. `models` is the allowed list, the default first: the cheapest
# of each line-up until the eval picks (ids from each provider's model pages, 2026-10-29).
PROVIDERS = {
    "meta": {"name": "Meta", "base_url": "https://api.meta.ai/v1", "models": ("muse-spark-1.3",), "temperature": 0.2},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1",
               "models": ("gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-astra"), "temperature": None},
    "anthropic": {"name": "Anthropic", "base_url": "https://api.anthropic.com",
                  "models": ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")},
}


def from_request(provider, key, model=None, env=None, client=None, http_client=None):
    """A backend on the caller's own key, for one request: built here, used once, dropped, never cached. `client`
    replaces the SDK client (the tests' scripted one); `http_client` is handed to the SDK client (the tests' mock
    transport). The caller's headers were checked before this; a model off the list is a ValueError."""
    p = PROVIDERS[provider]
    model = model or p["models"][0]
    if model not in p["models"]:
        raise ValueError(f"{model} is not an allowed {provider} model")
    env = os.environ if env is None else env
    timeout, budget = float(env.get("VERDICT_TIMEOUT_S", 25)), int(env.get("VERDICT_MAX_TOKENS", 6000))
    if provider == "anthropic":
        if client is None:
            import anthropic   # an explicit api_key: the SDK reads no ANTHROPIC_* credential or profile from the server
            client = anthropic.Anthropic(api_key=key, base_url=p["base_url"], timeout=timeout, max_retries=0,
                                         http_client=http_client)
        return AnthropicBackend(name=model, model=model, client=client, max_tokens=budget)
    if client is None:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=p["base_url"], timeout=timeout, max_retries=0, http_client=http_client)
        client.organization = client.project = None   # not the server's OPENAI_ORG_ID or OPENAI_PROJECT_ID
    return Backend(name=model, model=model, mode="json_schema", client=client, max_tokens=budget,
                   reasoning_effort="low", temperature=p["temperature"])


def failure_reason(e):
    """What a failed call means for the panel, in the AI_SWITCH reasons. The OpenAI and Anthropic SDKs both put the
    HTTP status on `status_code` and both raise an APITimeoutError."""
    status = getattr(e, "status_code", None)
    if status in (401, 402, 403):
        return "key_rejected"
    timeouts = [TimeoutError] + [getattr(m, "APITimeoutError") for m in map(_sdk, ("openai", "anthropic")) if m]
    if status in (429, 503, 529) or isinstance(e, tuple(timeouts)):
        return "provider_busy"
    return "provider_error"


def _sdk(name):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def write(lines, backend=None):
    """[Line] -> {"sentences", "writer", "trace"}. The trace says what each attempt drew, so a fallback is never silent."""
    trace = []
    if backend is not None:
        rejected, budget = None, backend.max_tokens
        for attempt in (1, 2):
            t0 = time.monotonic()
            try:
                raw, meta = backend.complete(lines, rejected, budget)
            except Exception as e:   # timeout, connection, 4xx/5xx: no second call, the renter gets the template now
                # The class and status only: a provider's message can quote the key it was sent.
                status = getattr(e, "status_code", None)
                trace.append({"writer": backend.name, "attempt": attempt, "ok": False,
                              "errors": [type(e).__name__ + (f" (HTTP {status})" if status else "")],
                              "reason": failure_reason(e), "ms": _ms(t0)})
                break
            reply, errors = validate.parse(raw)
            if reply is None and not (raw or "").strip():   # empty: usually the token budget spent on reasoning
                errors = [f"the reply is empty (finish_reason {meta.get('finish_reason')}, "
                          f"{meta.get('completion_tokens', '?')} completion tokens of {budget})"]
            if meta.get("finish_reason") == "length":         # cut off: the retry gets twice the room
                budget = min(2 * budget, 16000)
            if reply is not None:
                errors = validate.check(reply, lines)
            trace.append({"writer": backend.name, "attempt": attempt, "ok": not errors, "errors": errors, "ms": _ms(t0),
                          "model": backend.model, **({"usage": meta} if meta else {})})
            if not errors:
                return {"sentences": validate.clean(reply), "writer": backend.name, "trace": trace}
            rejected = (raw if isinstance(raw, str) else json.dumps(raw), errors)
    why = "no model configured" if backend is None else "the model's reply did not pass the checks or did not arrive"
    reply = template.write(lines)
    errors = validate.check(reply, lines)
    assert not errors, errors   # the template is held to the same rules; the tests make sure it holds
    trace.append({"writer": "template", "ok": True, "why": why})
    return {"sentences": validate.clean(reply), "writer": "template", "trace": trace}


def _ms(t0):
    return int((time.monotonic() - t0) * 1000)
