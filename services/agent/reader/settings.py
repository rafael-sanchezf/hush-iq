"""Run settings, read from the environment. services/agent/.env is loaded by the app and the CLI; a variable
already set in the environment wins over the file."""
import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_SCORE_URL = "https://hush-iq-api.vercel.app"
DEFAULT_TURNS = 8

# The providers a request may name (X-HushIQ-Provider). Base URLs are fixed here, so a key only ever goes to its
# own provider. Model ids checked against each provider's docs on 2026-10-29; an id not listed is a 400. The
# OpenAI and Anthropic defaults stand until the eval compares them (HIQ-79).
PROVIDERS = {
    "meta": {"name": "Meta", "base_url": DEFAULT_BASE_URL, "models": ("muse-spark-1.3",), "default": DEFAULT_MODEL},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1",
               "models": ("gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol"), "default": "gpt-6-luna"},
    "anthropic": {"name": "Anthropic", "base_url": "https://api.anthropic.com",
                  "models": ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"), "default": "claude-opus-5-5"},
}


def load_env(path=AGENT_DIR / ".env"):
    """KEY=VALUE lines into os.environ, without overwriting. No dependency on python-dotenv."""
    if not Path(path).is_file():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key():
    return os.environ.get("MODEL_API_KEY", "").strip()


def base_url():
    return os.environ.get("MODEL_API_BASE_URL") or DEFAULT_BASE_URL


def model():
    return os.environ.get("MODEL_API_MODEL") or DEFAULT_MODEL


def house_on():
    """The server switch for the house Meta key: HOUSE_AI=off when the credits end. READER_MODE=mock, the older
    name for the same thing, still turns it off."""
    return (os.environ.get("HOUSE_AI", "on").strip().lower() != "off"
            and os.environ.get("READER_MODE", "").strip().lower() != "mock")


def score_url():
    """The score API: the hosted one by default, or a local packages/model server (HUSH_SCORE_URL)."""
    return (os.environ.get("HUSH_SCORE_URL") or DEFAULT_SCORE_URL).rstrip("/")


def turns():
    return int(os.environ.get("READER_TURNS") or DEFAULT_TURNS)
