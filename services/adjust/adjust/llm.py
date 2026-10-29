"""Model clients. (Hackathon work, Oct 28; caller keys Oct 29, HIQ-77.)

client_from_env: the house client, Muse Spark through the OpenAI Python SDK at https://api.meta.ai/v1. The key lives
in services/adjust/.env (gitignored) or the environment; with no key there is no client.

client_for: a backend for one request with the caller's own key, for Meta, OpenAI or Anthropic. The base URL is fixed
per provider in config.PROVIDERS, so a key can only go to its own provider. The key is used for that request and
dropped with the client; nothing here keeps, logs or prints it.
"""
import os
from pathlib import Path

from noise_score import config as model_config

from . import backends, config as A

ENV = Path(__file__).resolve().parents[1] / ".env"


def load_env(path=ENV):
    """KEY=VALUE lines into os.environ, without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def model_name():
    return os.environ.get("MODEL_NAME") or A.MODEL_DEFAULT


def client_from_env():
    load_env()
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=os.environ.get("MODEL_BASE_URL") or A.MODEL_BASE_URL,
                  default_headers={"User-Agent": model_config.USER_AGENT})


def client_for(provider, key, model=None, http_client=None):
    """A backend for `provider` with the caller's `key`: fixed base URL, a short timeout and no retries.
    `http_client` is for tests (a mock transport); the eval and the API leave it out."""
    spec = A.PROVIDERS[provider]
    model = model or spec["default"]
    common = {"api_key": key, "base_url": spec["base_url"], "timeout": A.CALLER_TIMEOUT,
              "max_retries": A.CALLER_RETRIES, "default_headers": {"User-Agent": model_config.USER_AGENT}}
    if http_client is not None:
        common["http_client"] = http_client
    if spec["api"] == "messages":
        import anthropic
        return backends.MessagesBackend(anthropic.Anthropic(**common), model)
    from openai import OpenAI
    backend = backends.ResponsesBackend if spec["api"] == "responses" else backends.ChatBackend
    return backend(OpenAI(**common), model)
