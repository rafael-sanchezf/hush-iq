"""The AI switch and caller keys, for the permit reader. (Hackathon work, Oct 29, HIQ-77.)

Four optional request headers say whether a model reads the permits and whose key pays for it. Off makes no model
call and no adjustment, so the permit count stands. On uses the house Meta key, or the caller's own key for Meta,
OpenAI or Anthropic, built for that one request and dropped after it. A caller's key that fails never falls back
to the house key. Rules S1 to S5 in CONTRACT.md.

    choice = choose(ai="on", provider="anthropic", key=k)   # BadSwitch on a value outside the lists
    reply = run(rows, as_of, choice, house=llm.client_from_env())
"""
import os
from dataclasses import dataclass, field

from . import config as A, llm
from .permits import read_permits, skip_permits

NAMES = {"meta": "Meta", "openai": "OpenAI", "anthropic": "Anthropic"}
REDACTED = "[key removed]"
MIN_SECRET = 8   # a key shorter than this is not a real key, and redacting it would mangle the reply's text

MESSAGES = {
    "switched_off": "AI reading is off, so the permit count stands as the city's data has it.",
    "house_off": "AI reading is off on this server. Add your own key in settings to turn it on.",
    "no_key": "No {name} key is set. Add your own key in settings to turn AI reading on.",
    "key_rejected": "{name} refused the key, so the permit count stands. Check the key in settings.",
    "key_rejected_house": "{name} refused this server's key, so the permit count stands.",
    "provider_busy": "{name} is busy or slow right now, so the permit count stands. Try again in a minute.",
    "provider_error": "{name} could not read the permits just now, so the permit count stands.",
}


class BadSwitch(ValueError):
    """A header value outside its list: a 400. The message never repeats a header's value."""


@dataclass(frozen=True)
class Choice:
    on: bool
    provider: str
    model: str
    key: str | None = field(default=None, repr=False)   # the caller's key; None means the house key


def choose(ai=None, provider=None, key=None, model=None):
    """[S1] The four headers, checked. Absent means on, Meta, the house key and the provider's default model."""
    ai = (ai or "on").strip().lower()
    if ai not in ("on", "off"):
        raise BadSwitch("X-HushIQ-AI must be on or off")
    provider = (provider or A.HOUSE_PROVIDER).strip().lower()
    if provider not in A.PROVIDERS:
        raise BadSwitch(f"X-HushIQ-Provider must be one of {', '.join(A.PROVIDERS)}")
    spec = A.PROVIDERS[provider]
    model = (model or spec["default"]).strip()
    if model not in spec["models"]:
        raise BadSwitch(f"X-HushIQ-Model is not on the {provider} list: {', '.join(spec['models'])}")
    return Choice(ai == "on", provider, model, (key or "").strip() or None)


def house_on():
    """[S2] HOUSE_AI=off turns the house key off, from the environment or services/adjust/.env."""
    llm.load_env()
    return (os.environ.get("HOUSE_AI") or A.HOUSE_AI_DEFAULT).strip().lower() != "off"


def ai_object(mode, choice=None, key=None, reason=None):
    """[S5] The `ai` object on every reply."""
    name = NAMES.get(choice.provider) if choice else None
    msg = None
    if reason:
        msg = MESSAGES["key_rejected_house" if reason == "key_rejected" and key == "house" else reason].format(name=name)
    named = choice is not None and reason != "switched_off"
    return {"mode": mode, "provider": choice.provider if named else None,
            "model": choice.model if named and reason != "no_key" else None,
            "key": key, "reason": reason, "message": msg}


def blocked(choice, house):
    """Why the reply is basic before any call [S2], or None when a model can run. With no caller key only Meta has
    a house key."""
    if not choice.on:
        return "switched_off"
    if choice.key:
        return None
    if choice.provider != A.HOUSE_PROVIDER:
        return "no_key"
    if not house_on():
        return "house_off"
    return "no_key" if house is None else None


def plan(choice, house, connect=llm.client_for):
    """(client, "house" | "caller", None), or (None, None, reason). A caller's key builds a client for its own
    provider and that request only, and is never swapped for the house key [S3]."""
    reason = blocked(choice, house)
    if reason:
        return None, None, reason
    if choice.key:
        return connect(choice.provider, choice.key, choice.model), "caller", None
    return house, "house", None


def run(rows, as_of, choice, house=None, connect=llm.client_for):
    """The permit reader behind the switch: read_permits' reply plus `ai`, with the caller's key redacted from it."""
    client, key, reason = plan(choice, house, connect)
    if reason:
        out = skip_permits(rows, as_of, MESSAGES[reason].format(name=NAMES[choice.provider]))
        out["ai"] = ai_object("basic", choice, None, reason)
        return out
    out = read_permits(rows, as_of, client=client, model=choice.model)
    failure = out.pop("failure", None)   # [S3] a failed key makes no adjustment and says why; no second try
    out["ai"] = ai_object("basic", choice, key, failure) if failure else ai_object("model", choice, key)
    return redact(out, choice.key)


def redact(obj, secret):
    """[S4] Every string in the reply with the key cut out. Nothing puts the key there; this is the last gate."""
    if not secret or len(secret) < MIN_SECRET:
        return obj
    if isinstance(obj, str):
        return obj.replace(secret, REDACTED)
    if isinstance(obj, dict):
        return {redact(k, secret): redact(v, secret) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, secret) for v in obj]
    return obj
