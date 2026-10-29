"""The Meta Model API client: the official OpenAI Python SDK, pointed at api.meta.ai.

make_client() returns (client, mode). Live when MODEL_API_KEY is set; otherwise the offline heuristic model in
mock.py, so the app and the website run without a key. READER_MODE=mock forces mock with a key present. The
key stays inside the client; traces never see it.
"""
import os

from openai import OpenAI

from . import mock, settings

MAX_RETRIES = 3      # the SDK retries 429 and 5xx on its own, waiting as long as the API asks
TIMEOUT_S = 90


def make_client():
    key = settings.api_key()
    if key and os.environ.get("READER_MODE", "").lower() != "mock":
        return OpenAI(api_key=key, base_url=settings.base_url(), max_retries=MAX_RETRIES, timeout=TIMEOUT_S), "live"
    return mock.client(mock.HeuristicModel()), "mock"
