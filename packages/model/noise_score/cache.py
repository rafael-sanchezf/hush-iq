"""Disk cache for upstream pulls, keyed by a hash of the request. [T4]"""
import hashlib
import json
import os
import time
from pathlib import Path

from . import config

CACHE_DIR = Path(os.environ.get("NOISE_SCORE_CACHE", Path(__file__).resolve().parent.parent / ".cache"))


def _key(name, params):
    raw = json.dumps([name, params], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()


def get(name, params):
    p = CACHE_DIR / f"{_key(name, params)}.json"
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
    if time.time() - doc["t"] > config.CACHE_TTL_DAYS * 86400:
        return None
    return doc["v"]


def put(name, params, value):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{_key(name, params)}.json"
    p.write_text(json.dumps({"t": time.time(), "name": name, "params": params, "v": value}))
    return value
