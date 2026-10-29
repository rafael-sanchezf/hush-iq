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

TOOL_NAME = "write_verdict"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

SYSTEM = """You write the "what you'll hear" paragraph for one renter looking at one New York City apartment.

The user message holds numbered evidence lines (E1, E2, ...): the verdict for this renter, how each noise source
ranks against Manhattan, the weight each source got and why, what the city's records show near the building, the
renter's sleep hours and answers, and the floor and side used. Nothing else is known about this apartment.

Write 3 to 5 plain sentences, to the renter ("you"), on what they will hear here and when, for the way they sleep.
Start with the verdict. Then the sources that matter most for them: the loudest, and the ones they said bother them.
Then the floor and side used; when the evidence gives a range because the listing was silent, give the range.

Code checks every reply and rejects one that breaks any of these rules:
1. Each sentence lists in cites the ids of the lines it states, and only ids from the evidence.
2. Every number in a sentence appears, written the same way, in a line that sentence cites. Do not compute, round,
   convert or add up numbers.
3. Every name (a street, a building, a hospital, a station, a borough) in a sentence appears in a line it cites.
4. Mention a kind of source (subway, bar, hospital, construction, traffic) only if a line it cites mentions it.
5. No decibels and no sound levels. The ranks are comparisons, not measurements: say "quieter than 34% of
   Manhattan apartments".
6. No ids in the text. No advice, no sales talk, no adjectives the lines do not support."""

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
    max_tokens: int = 1500

    def complete(self, lines, rejected=None):
        """One call -> the raw reply text (JSON, unchecked)."""
        ids = [l.id for l in lines]
        msgs = [{"role": "system", "content": f"{SYSTEM}\n\n{FINISH[self.mode]}"}] + messages(lines, rejected)
        kw = {"model": self.model, "messages": msgs, "temperature": 0.2, "max_tokens": self.max_tokens}
        if self.mode == "tool":
            kw["tools"] = [{"type": "function", "function": {
                "name": TOOL_NAME, "strict": True, "parameters": reply_schema(ids),
                "description": "Submit the paragraph: sentences, each with the evidence ids it states."}}]
            kw["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}
        else:
            kw["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "verdict", "schema": reply_schema(ids), "strict": True}}
        msg = self.client.chat.completions.create(**kw).choices[0].message
        for call in getattr(msg, "tool_calls", None) or []:
            if call.function.name == TOOL_NAME:
                return call.function.arguments
        return msg.content or ""   # a host may answer in the content anyway; the checks decide


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
                       timeout=float(env.get("VERDICT_TIMEOUT_S", 12)), max_retries=0)
        else:
            c = client
        return Backend(name=name, model=env.get(host["model_env"], host["model"]), mode=host["mode"], client=c,
                       max_tokens=int(env.get("VERDICT_MAX_TOKENS", 1500)))
    return None


def write(lines, backend=None):
    """[Line] -> {"sentences", "writer", "trace"}. The trace says what each attempt drew, so a fallback is never silent."""
    trace = []
    if backend is not None:
        rejected = None
        for attempt in (1, 2):
            t0 = time.monotonic()
            try:
                raw = backend.complete(lines, rejected)
            except Exception as e:   # timeout, connection, 4xx/5xx: no second call, the renter gets the template now
                trace.append({"writer": backend.name, "attempt": attempt, "ok": False,
                              "errors": [f"{type(e).__name__}: {str(e)[:200]}"], "ms": _ms(t0)})
                break
            reply, errors = validate.parse(raw)
            if reply is not None:
                errors = validate.check(reply, lines)
            trace.append({"writer": backend.name, "attempt": attempt, "ok": not errors, "errors": errors, "ms": _ms(t0)})
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
