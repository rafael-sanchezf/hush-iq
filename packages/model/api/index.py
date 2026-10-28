"""Vercel entry: the FastAPI app from noise_score, with the disk cache moved to /tmp (the only
writable path on a serverless function). The shim strips a /api/index prefix if the router adds one."""
import os
import sys
from pathlib import Path

os.environ.setdefault("NOISE_SCORE_CACHE", "/tmp/noise-score-cache")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from noise_score.api import app as _app  # noqa: E402

PREFIX = "/api/index"


async def app(scope, receive, send):
    if scope["type"] == "http" and scope.get("path", "").startswith(PREFIX):
        scope = dict(scope)
        scope["path"] = scope["path"][len(PREFIX):] or "/"
        scope["raw_path"] = scope["path"].encode()
    await _app(scope, receive, send)
