"""Shared test helpers. Every test runs offline: the model is scripted through reader.mock, the scorer is fake."""
import json
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT))

from reader import mock  # noqa: E402
from reader.listing import Answers, Listing, Photo  # noqa: E402

FIXTURES = AGENT / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64      # enough for the type sniff; the scripted model never looks


def fixture_text(name):
    return (FIXTURES / name).read_text()


def listing(text="", photos=0, answers=None):
    return Listing(text=text, photos=[Photo.from_bytes(PNG, f"p{i}.png") for i in range(photos)],
                   answers=answers or Answers())


def read(value, *quotes, photo=None):
    """A field marked read, with text quotes and/or one photo citation."""
    ev = [{"source": "text", "quote": q} for q in quotes]
    if photo is not None:
        ev.append({"source": f"photo:{photo}"})
    return {"status": "read", "value": value, "evidence": ev}


CANT = {"status": "cant_tell"}


class Scripted:
    """A scripted model: `turns` are the agent's tool calls in order, each (name, args) or a function of the
    request body; `photos` answers read_photo sub-calls by photo index. Records every request."""

    def __init__(self, turns, photos=None):
        self.turns = list(turns)
        self.photos = photos or {}
        self.agent_requests = []
        self.photo_requests = []

    def __call__(self, body):
        if "tools" not in body:
            self.photo_requests.append(body)
            i = mock.photo_index(body)
            return {"output_text": json.dumps(self.photos.get(i, {"fields": {}, "note": "nothing scripted"}))}
        self.agent_requests.append(body)
        if not self.turns:
            return {"output_text": "I am done."}
        step = self.turns.pop(0)
        if callable(step):
            return step(body)
        name, args = step
        return mock.tool_call(name, args, len(self.agent_requests))

    @property
    def client(self):
        return mock.client(self)


class FakeScorer:
    """Places any address with a house number, and answers like engine v2 (a range when floor or side is
    unknown). Records what it was asked."""

    def __init__(self, floors=18):
        self.located, self.scored, self.floor_counts = [], [], floors

    def floors(self, bbl):
        return self.floor_counts

    def locate(self, address, text=""):
        self.located.append(address)
        return {"label": address.upper() + ", New York, NY, USA", "lat": 40.78, "lng": -73.98, "bbl": "1012480022",
                "bin": "1033000", "borough": "Manhattan"}

    def score(self, address, floor, position, answers):
        self.scored.append({"address": address, "floor": floor, "position": position, "answers": answers.as_dict()})
        silent = floor is None or position == "unknown"
        rng = ({"loudest_case": {"verdict": "Loud", "quieter_than": 30.0},
                "quietest_case": {"verdict": "Quiet", "quieter_than": 70.0}} if silent else None)
        return {"engine": "v2", "url": "fake://v2/score",
                "body": {"engine": "v2", "verdict": "Typical", "quieter_than": 52.0, "range": rng}}


@pytest.fixture
def scorer():
    return FakeScorer()
