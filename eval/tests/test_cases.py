"""The 20 cases are well formed, cover the hard listings the brief names, and the mock run passes on them."""
import re
from pathlib import Path

import pytest

from hush_eval import runner
from hush_eval import shapes as S

CASES = runner.load_cases()
REQUIRED_TAGS = {"silent", "misleading-adjective", "top-floor", "contradiction", "courtyard", "corner", "walk-up"}


def test_there_are_twenty_cases_with_unique_ids():
    assert len(CASES) == 20
    assert len({c["id"] for c in CASES}) == 20
    for c in CASES:
        assert Path(c["_path"]).stem == c["id"]


def test_the_hard_listings_are_covered():
    tags = {t for c in CASES for t in c["tags"]}
    assert REQUIRED_TAGS <= tags, REQUIRED_TAGS - tags
    assert sum("silent" in c["tags"] for c in CASES) >= 2


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_shape(case):
    assert case["about"] and case["listing"]["text"].strip()
    gold = case["gold"]
    for name in ("address", "floor", "side"):
        assert name in gold
    assert gold["floor"] is None or gold["floor"] == "top" or S.FLOOR_MIN <= gold["floor"] <= S.FLOOR_MAX
    assert gold["side"] in (None,) + S.SIDES
    if gold["floor"] == "top":
        assert gold.get("building_floors"), "a top-floor case needs the building's floor count"
    for name, v in (gold.get("observed") or {}).items():
        assert v in S.OBSERVED_VALUES[name]
    a = case["answers"]
    assert 0 <= a["sleep_from"] <= 23 and 0 <= a["sleep_until"] <= 23 and isinstance(a["day_bothers"], bool)
    assert set(a["bothers"]) <= set(S.BOTHERS)
    for p in case["listing"]["photos"]:
        assert (runner.CASES / p).is_file(), p


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_nothing_personal_in_a_case(case):
    blob = Path(case["_path"]).read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", blob), "an email address"
    assert not re.search(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b", blob), "a phone number"
    assert not re.search(r"https?://", blob), "a link to a listing site"
    assert "MODEL_API_KEY" not in blob and "sk-" not in blob


def test_the_mock_run_passes():
    res = runner.run("mock", "fixture")
    hard = [(r["id"], p.message) for r in res["records"] for p in r["problems"] if p.hard]
    assert hard == []
    assert res["ok"]
    for name in ("address", "floor", "side"):
        assert res["accuracy"][name]["n"] == 20


def test_a_bad_fixture_fails_the_run(tmp_path):
    src = runner.CASES / "11-courtyard-facing-rear.json"
    doc = src.read_text().replace('"quote": "7th fl"', '"quote": "7th floor"')
    (tmp_path / "11.json").write_text(doc)
    (tmp_path / "photos").mkdir()
    res = runner.run("mock", "fixture", cases_dir=tmp_path)
    assert not res["ok"]
    [p] = [p for r in res["records"] for p in r["problems"] if p.hard]
    assert p.where == "fields.floor" and "7th floor" in p.message


def test_reports_render():
    res = runner.run("mock", "fixture", only=["04", "19"])
    text = runner.text_report(res, live=True)
    assert "04-quiet-block-faces-street" in text and "PASS" in text and "latency" in text
    md = runner.markdown_report(res)
    assert md.startswith("### Hush IQ eval: PASS")
    assert '"cases": 2' in runner.json_report(res)
