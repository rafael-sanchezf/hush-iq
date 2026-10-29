"""Run settings, read from the environment. services/agent/.env is loaded by the app and the CLI; a variable
already set in the environment wins over the file."""
import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
DEFAULT_SCORE_URL = "https://hush-iq-api.vercel.app"
DEFAULT_TURNS = 8


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


def score_url():
    """The score API: the hosted one by default, or a local packages/model server (HUSH_SCORE_URL)."""
    return (os.environ.get("HUSH_SCORE_URL") or DEFAULT_SCORE_URL).rstrip("/")


def turns():
    return int(os.environ.get("READER_TURNS") or DEFAULT_TURNS)
