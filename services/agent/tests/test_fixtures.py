"""The five synthetic listings against fixtures/expected.json, read by the offline heuristic model. This checks the
fixtures and the checks agree (every expected value can be quoted and passes); the live model is checked by
scripts/run_fixtures.py with a key."""
import pytest

from conftest import EXPECTED, FakeScorer, fixture_text, listing
from reader import loop, mock

NAMES = [k for k in EXPECTED if not k.startswith("_")]


def test_there_are_five():
    assert len(NAMES) == 5


@pytest.mark.parametrize("name", NAMES)
def test_fixture(name):
    result = loop.read(listing(fixture_text(name)), client=mock.client(mock.HeuristicModel()), scorer=FakeScorer())
    want = EXPECTED[name]
    got = {k: result["fields"][k]["value"] for k in ("address", "unit", "floor", "side")}
    got["position"] = result["position"]
    assert got == want
    assert result["status"] == "complete"
