"""The Meta Model API client, when a key is set. (Hackathon work, Oct 28.)

Muse Spark through the OpenAI Python SDK at https://api.meta.ai/v1. The key lives in services/adjust/.env (gitignored)
or the environment; with no key there is no client and the permit reader uses its rules.
"""
import os
from pathlib import Path

from noise_score import config as model_config

from . import config as A

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
