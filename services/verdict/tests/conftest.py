"""Shared test pieces: the score fixtures, reader fields, and a scripted stand-in for the OpenAI client.

The fixtures are real responses for real Manhattan addresses, scored on 2026-10-29 from the hosted /v1/raw pulls
(engine v2 run locally, v1 from the hosted /v1/score), with liquor licensee names replaced by LICENSEE.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"

from verdict import evidence, mock  # noqa: E402

SCORES = {
    "claremont": "v2_claremont_floor4_rear.json",      # floor 4, rear, both from the listing; sirens ticked
    "ludlow": "v2_ludlow_silent.json",                 # a silent listing: expected floor, side unknown, a range
    "east101": "v2_east101_floor2_front.json",         # floor 2 facing the street, next to a hospital
    "claremont_v1": "v1_claremont_floor4_rear.json",   # the v1 fallback, decibels and all in its raw shape
}

# Reader fields in the CONTRACT shape of services/agent. The quotes are made up for the tests.
FIELDS = {
    "claremont": {
        "address": {"value": "140 Claremont Ave", "status": "read",
                    "evidence": [{"source": "text", "quote": "140 Claremont Ave, Apt 4C"}]},
        "unit": {"value": "4C", "status": "read", "evidence": [{"source": "text", "quote": "Apt 4C"}]},
        "floor": {"value": 4, "status": "read", "evidence": [{"source": "text", "quote": "4th floor, elevator building"}]},
        "side": {"value": "rear", "status": "read", "evidence": [{"source": "photo:2", "what": "bedroom window onto a courtyard"}]},
    },
    "ludlow": {
        "address": {"value": "151 Ludlow St", "status": "read",
                    "evidence": [{"source": "text", "quote": "151 Ludlow St, Lower East Side"}]},
        "unit": {"value": None, "status": "cant_tell", "evidence": []},
        "floor": {"value": None, "status": "cant_tell", "evidence": []},
        "side": {"value": None, "status": "cant_tell", "evidence": []},
    },
    "east101": {
        "floor": {"value": 2, "status": "read", "evidence": [{"source": "text", "quote": "second floor, facing Fifth Avenue"}]},
        "side": {"value": "front", "status": "read", "evidence": [{"source": "text", "quote": "facing Fifth Avenue"}]},
    },
}


def load(name):
    return json.loads((FIXTURES / SCORES[name]).read_text())


@pytest.fixture
def lines():
    """lines(name) -> the evidence lines for a fixture, with its reader fields."""
    def make(name, answers=None):
        return evidence.build(load(name), answers, FIELDS.get(name.replace("_v1", ""), {}))
    return make


@pytest.fixture
def backend():
    """backend(*script, mode=...) -> a Backend that plays the script instead of calling a host (verdict.mock)."""
    return mock.backend


def ids(lines, kind, source=None):
    return [l.id for l in lines if l.kind == kind and (source is None or l.source == source)]
