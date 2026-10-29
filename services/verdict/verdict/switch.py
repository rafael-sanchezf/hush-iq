"""The AI switch and caller keys (AI_SWITCH contract, HIQ-76). [hackathon, Oct 29]

    request(ai, provider, key, model) -> Request         the four X-HushIQ-* headers, checked (RequestError is a 400)
    run(lines, req, house)            -> reply + "ai"    the writer on the house key, the caller's key, or no model

Off makes no model call: the template writes. On takes the caller's key for the provider it names, or else the house
key (Meta only, and only while HOUSE_AI is on). A caller's key that fails writes the template with a reason; it never
falls back to the house key, so a stranger's failure never spends the house credits. The key leaves this module in
no string: `run` removes it from the whole reply, trace included.
"""
import os
from dataclasses import dataclass, field

from . import writer

HEADERS = ("X-HushIQ-AI", "X-HushIQ-Provider", "X-HushIQ-Key", "X-HushIQ-Model")
REDACTED = "[key removed]"


class RequestError(ValueError):
    """A header the server cannot use. The message never quotes the key or the model header's value."""


@dataclass(frozen=True)
class Request:
    ai: str = "on"
    provider: str | None = None
    key: str | None = field(default=None, repr=False)
    model: str | None = None


def request(ai=None, provider=None, key=None, model=None):
    """The header values -> a Request. Absent or empty means the contract's default: on, meta, the house key, the
    provider's default model."""
    ai = (ai or "on").strip().lower()
    if ai not in ("on", "off"):
        raise RequestError("X-HushIQ-AI must be on or off")
    provider = (provider or "").strip().lower() or None
    if provider is not None and provider not in writer.PROVIDERS:
        raise RequestError(f"X-HushIQ-Provider must be one of {', '.join(writer.PROVIDERS)}")
    key = (key or "").strip() or None
    if key is not None and (len(key) > 512 or any(c.isspace() or not c.isprintable() for c in key)):
        raise RequestError("X-HushIQ-Key is not a key this server can send")
    model = (model or "").strip() or None
    allowed = writer.PROVIDERS[provider or "meta"]["models"]
    if model is not None and model not in allowed:
        raise RequestError(f"X-HushIQ-Model is not on the {provider or 'meta'} list: {', '.join(allowed)}")
    return Request(ai=ai, provider=provider, key=key, model=model)


def house_on(env=None):
    """HOUSE_AI=off turns the house key off, for when the credits end. Default on."""
    return (os.environ if env is None else env).get("HOUSE_AI", "on").strip().lower() != "off"


def message(reason, provider=None, key=None):
    """One plain sentence for the panel, or None when the model wrote."""
    who = writer.PROVIDERS[provider]["name"] if provider else "The AI provider"
    return {
        None: None,
        "switched_off": "AI reading is off, so this is the basic paragraph.",
        "house_off": "AI reading is off on this server; add your own key in settings to turn it on.",
        "no_key": (f"Add your {who} key in settings to use {who}; this is the basic paragraph."
                   if provider not in (None, "meta") else "No AI key is set up, so this is the basic paragraph."),
        "key_rejected": (f"{who} did not accept your key, so this is the basic paragraph; check the key in settings."
                         if key == "caller" else f"{who} did not accept the server's key, so this is the basic paragraph."),
        "provider_busy": f"{who} is busy or slow right now, so this is the basic paragraph; try again in a minute.",
        "provider_error": f"{who} did not answer, so this is the basic paragraph.",
        "checks_failed": "The AI draft did not pass the evidence checks, so this is the basic paragraph.",
    }[reason]


def _ai(mode, provider=None, model=None, key=None, reason=None):
    return {"mode": mode, "provider": provider, "model": model, "key": key, "reason": reason,
            "message": message(reason, provider, key)}


def choose(req, house=None, env=None, client=None, http_client=None):
    """-> (the backend for this request or None, its `ai` object, whether the backend was built here)."""
    if req.ai == "off":
        return None, _ai("basic", reason="switched_off"), False
    if req.key:
        provider = req.provider or "meta"
        b = writer.from_request(provider, req.key, req.model, env=env, client=client,
                                http_client=http_client(provider) if http_client else None)
        return b, _ai("model", provider, b.model, "caller"), client is None
    if req.provider not in (None, "meta"):
        return None, _ai("basic", req.provider, reason="no_key"), False
    if not house_on(env):
        return None, _ai("basic", reason="house_off"), False
    if house is None:
        return None, _ai("basic", reason="no_key"), False
    return house, _ai("model", "meta", house.model, "house"), False


def run(lines, req, house=None, env=None, client=None, http_client=None):
    """[Line] + a Request -> {sentences, writer, trace, ai}, with the caller's key removed from every string. `house` is
    the server's backend (writer.from_env); `client` and `http_client` are the tests' stand-ins for a caller backend."""
    backend, ai, built = choose(req, house, env, client, http_client)
    try:
        out = writer.write(lines, backend)
    finally:
        if built:
            backend.client.close()   # the caller's client is dropped with the request
    if backend is not None and out["writer"] == "template":
        last = [t for t in out["trace"] if t.get("attempt")][-1]
        ai = _ai("basic", ai["provider"], ai["model"], ai["key"], last.get("reason", "checks_failed"))
    return redact({**out, "ai": ai}, req.key)


def redact(obj, key):
    """Every string in obj with the key replaced. The checks above keep the key out; this makes sure."""
    if not key:
        return obj
    if isinstance(obj, str):
        return obj.replace(key, REDACTED)
    if isinstance(obj, dict):
        return {redact(k, key): redact(v, key) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, key) for v in obj]
    return obj
