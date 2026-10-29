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
"""
import json
import os
import time
from dataclasses import dataclass
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
loud", "quiet"); a rank of 0% as "among the loudest in Manhattan"; no "for nightlife" or "of 6" tails copied over;
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

FINISH = {"tool": f"Answer by calling {TOOL_NAME} once.", "json_schema": "Answer with the JSON object only."}


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

    def complete(self, lines, rejected=None, max_tokens=None):
        """One call -> (the raw reply text, JSON and unchecked; what the host said about it: finish reason, tokens)."""
        budget = max_tokens or self.max_tokens
        ids = [l.id for l in lines]
        msgs = [{"role": "system", "content": f"{SYSTEM}\n\n{FINISH[self.mode]}"}] + messages(lines, rejected)
        kw = {"model": self.model, "messages": msgs, "temperature": 0.2}
        if self.mode == "json_schema":   # the Meta Model API: max_tokens is a deprecated alias there
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
                trace.append({"writer": backend.name, "attempt": attempt, "ok": False,
                              "errors": [f"{type(e).__name__}: {str(e)[:200]}"], "ms": _ms(t0)})
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
