"""Which model reads a listing, decided per request. (AI switch and caller keys: hackathon work, Oct 29.)

    plan = make_client(provider=None, key=None, model=None, ai="on")
    loop.read(listing, plan=plan, scorer=scorer)

The four arguments are the request headers X-HushIQ-Provider, X-HushIQ-Key, X-HushIQ-Model and X-HushIQ-AI, and
the eval calls the same function in process. A Plan is the client the loop talks to (always the OpenAI SDK's
Responses API: Meta and OpenAI directly, Anthropic through anthropic_adapter.py, the basic reader through
mock.py), the model id, and the result's `ai` object.

    ai off                          the basic reader (mock.HeuristicModel), no model call at all
    a caller's key                  that provider, at its fixed base URL, for this request only
    no key, provider meta           the house key (MODEL_API_KEY), unless HOUSE_AI=off
    no key, provider openai/claude  the basic reader, reason no_key

There is no path from a caller's key to the house key: if the caller's key fails, the loop runs the basic reader
and says why (loop.py). A key is held only by the client built here and by the plan, which drops it with the
request; failures.scrub() takes it out of everything the request returns.
"""
import os
from dataclasses import dataclass, field

import anthropic
import httpx
import openai
from openai import OpenAI

from . import anthropic_adapter, failures, mock, settings, tools

MAX_RETRIES = 3      # the SDK retries 429 and 5xx on its own, waiting as long as the API asks
TIMEOUT_S = 90
CALLER_RETRIES = 1   # a caller's key that is rate-limited runs basic soon, rather than waiting minutes
CALLER_TIMEOUT_S = 60
# OpenAI's Responses API keeps nothing with store=False, so a reasoning model's reasoning has to travel with the
# conversation (include encrypted_content); and its function tools are strict by default, which our optional
# fields do not satisfy. Meta's API needs neither, so its requests stay as they were.
OPENAI_OPTIONS = {"include": ["reasoning.encrypted_content"],
                  "tools": [dict(t, strict=False) for t in tools.DEFINITIONS]}

MESSAGES = {
    "switched_off": "AI reading is off in your settings, so the basic reader read this listing.",
    "house_off": "AI reading is off. Add your own key in settings to turn it on.",
    "no_key": "{name} needs your own API key: add it in settings. The basic reader read this listing.",
    "no_house_key": "This server has no AI key, so the basic reader read this listing.",
    "key_rejected": "{name} rejected {whose} key, so the basic reader read this listing.",
    "provider_busy": "{name} is busy or rate-limiting {whose} key, so the basic reader read this listing. "
                     "Try again in a minute.",
    "provider_error": "{name} did not answer, so the basic reader read this listing.",
}


class BadChoice(ValueError):
    """A header value the reader does not accept: a 400."""


@dataclass
class Plan:
    client: object
    model: str
    ai: dict
    options: dict = field(default_factory=dict)              # extra arguments for each agent turn
    secrets: tuple = field(default=(), repr=False)           # what failures.scrub() takes out of the output

    @property
    def mode(self):
        """The result's older field: "live" when a model reads, "mock" for the basic reader."""
        return "live" if self.ai["mode"] == "model" else "mock"


def make_client(provider=None, key=None, model=None, ai=None, *, transport=None):
    """The plan for one request. transport replaces the provider's HTTP transport (tests only: an httpx transport
    for meta and openai, an httpx2 one for anthropic)."""
    ai = _one_of((ai or "on").strip().lower(), ("on", "off"), "X-HushIQ-AI")
    provider = _one_of((provider or "meta").strip().lower(), tuple(settings.PROVIDERS), "X-HushIQ-Provider")
    model = _model(provider, model)
    key = (key or "").strip() or None
    house = settings.api_key()

    if ai == "off":
        return basic("switched_off")
    if key:
        return Plan(_provider_client(provider, key, transport), model, _model_ai(provider, model, "caller"),
                    options=OPENAI_OPTIONS if provider == "openai" else {}, secrets=(key, house))
    if provider != "meta":
        return basic("no_key", provider=provider)
    if not settings.house_on():
        return basic("house_off", provider="meta", key="house")
    if not house:
        return basic("no_key", provider="meta", key="house")
    client = OpenAI(api_key=house, base_url=settings.base_url(), max_retries=MAX_RETRIES, timeout=TIMEOUT_S,
                    http_client=httpx.Client(transport=transport) if transport else None)
    return Plan(client, model, _model_ai("meta", model, "house"), secrets=(house,))


def basic(reason, provider=None, key=None):
    """The basic reader: regular expressions on the text, photos unread. Labelled mode "mock" in the old field."""
    return Plan(mock.client(mock.HeuristicModel()), settings.model(),
                {"mode": "basic", "provider": provider, "model": None, "key": key, "reason": reason,
                 "message": message(reason, provider, key)}, secrets=(settings.api_key(),))


def given(client, model, mode="live"):
    """A plan around a client made elsewhere (the tests' scripted models): the house key's provider, as before."""
    if mode == "live":
        return Plan(client, model, _model_ai("meta", model, "house"), secrets=(settings.api_key(),))
    return Plan(client, model, basic("house_off", "meta", "house").ai)


def fallback(plan, error):
    """The basic plan to run after the plan's model failed, saying why."""
    return basic(failures.reason(error), provider=plan.ai["provider"], key=plan.ai["key"])


def message(reason, provider=None, key=None):
    if reason == "no_key" and key == "house":
        reason = "no_house_key"
    name = settings.PROVIDERS[provider]["name"] if provider else "The AI provider"
    return MESSAGES[reason].format(name=name, whose="your" if key == "caller" else "this server's")


def check_key(provider=None, key=None, model=None, *, transport=None):
    """{"ok", "provider", "message"}: is this key accepted, and can it use the model? One models-list call, which
    spends no tokens."""
    provider = _one_of((provider or "meta").strip().lower(), tuple(settings.PROVIDERS), "X-HushIQ-Provider")
    spec = settings.PROVIDERS[provider]
    model = _model(provider, model)
    key = (key or "").strip()
    name = spec["name"]
    if not key:
        return {"ok": False, "provider": provider, "message": "No key sent: put it in the X-HushIQ-Key header."}
    try:
        ids = _model_ids(provider, key, transport)
    except (openai.APIError, anthropic.APIError) as e:
        why = failures.reason(e)
        text = {"key_rejected": f"{name} rejected this key.",
                "provider_busy": f"{name} is rate-limiting this key right now. Try again in a minute.",
                "provider_error": f"Could not reach {name} to check the key. Try again later."}[why]
        return {"ok": False, "provider": provider, "message": text}
    if model not in ids:
        return {"ok": False, "provider": provider, "message": f"{name} accepted the key, but {model} is not available "
                                                              f"to it."}
    return {"ok": True, "provider": provider, "message": f"{name} accepted the key, and {model} is available."}


def from_env(provider=None, model=None, ai=None):
    """make_client() for the command line and the eval: a caller key for openai or anthropic comes from
    OPENAI_API_KEY or ANTHROPIC_API_KEY, never from a tracked file; meta uses the house key."""
    env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get((provider or "meta").lower())
    return make_client(provider, os.environ.get(env) if env else None, model, ai)


def providers():
    """What GET / tells a client it may ask for."""
    return {name: {"models": list(spec["models"]), "default": spec["default"]}
            for name, spec in settings.PROVIDERS.items()}


def _provider_client(provider, key, transport):
    base_url = settings.PROVIDERS[provider]["base_url"]
    if provider == "anthropic":
        return anthropic_adapter.client(key, base_url, transport=transport, max_retries=CALLER_RETRIES,
                                        timeout=CALLER_TIMEOUT_S)
    return OpenAI(api_key=key, base_url=base_url, max_retries=CALLER_RETRIES, timeout=CALLER_TIMEOUT_S,
                  http_client=httpx.Client(transport=transport) if transport else None)


def _model_ids(provider, key, transport):
    base_url = settings.PROVIDERS[provider]["base_url"]
    if provider == "anthropic":
        c = anthropic.Anthropic(api_key=key, base_url=base_url, max_retries=CALLER_RETRIES, timeout=CALLER_TIMEOUT_S,
                                http_client=anthropic.DefaultHttpxClient(transport=transport) if transport else None)
        return {m.id for m in c.models.list(limit=100)}
    c = OpenAI(api_key=key, base_url=base_url, max_retries=CALLER_RETRIES, timeout=CALLER_TIMEOUT_S,
               http_client=httpx.Client(transport=transport) if transport else None)
    return {m.id for m in c.models.list()}


def _model_ai(provider, model, key):
    return {"mode": "model", "provider": provider, "model": model, "key": key, "reason": None, "message": None}


def _model(provider, model):
    """The model asked for, or the provider's default (for meta, MODEL_API_MODEL when set)."""
    spec = settings.PROVIDERS[provider]
    default = settings.model() if provider == "meta" else spec["default"]
    model = (model or "").strip() or default
    if model not in spec["models"] and model != default:
        raise BadChoice(f"X-HushIQ-Model {model[:60]!r} is not one of {provider}'s models: {', '.join(spec['models'])}")
    return model


def _one_of(value, allowed, header):
    if value not in allowed:
        raise BadChoice(f"{header} must be one of {', '.join(allowed)}")
    return value
