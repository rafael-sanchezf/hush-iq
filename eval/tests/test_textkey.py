"""The text key: strict rules, never a sales claim, Rafa's click as the confirm, and the labeler keying the same."""
import json
import re
import shutil
import subprocess

import pytest

from hush_eval import photo
from hush_eval import textkey as T
from hush_eval import runner

CASE_TEXTS = [c["listing"]["text"] for c in runner.load_cases()]
EXAMPLE_TEXT = (photo.REPO_ROOT / "00" / "listing.txt").read_text()


def values(text):
    return {f: k["value"] for f, k in T.key(text).items()}


def test_what_the_text_states_becomes_a_key_with_its_words():
    k = T.key("Sunny 4th-floor walk-up at 12 West 9th Street. The bedroom faces the courtyard. Exposed brick, "
              "floor-to-ceiling windows and central air.")
    assert {f: v["value"] for f, v in k.items()} == {"floor": 4, "side": "rear", "view": "courtyard",
                                                      "windows": "floor_to_ceiling", "ac_units": "no", "wall_material": "brick"}
    assert k["floor"]["quote"] == "4th-floor" and k["side"]["quote"] == "faces the courtyard"
    assert values("Top floor of a five-story walk-up") == {"floor": 5}
    assert values("Garden-level floor-through") == {"floor": 1}
    assert values("Apt 12F, river views") == {"floor": 12, "view": "open"}
    assert values("Apt 12F on the 14th floor") == {"floor": 14}                  # the unit number only when nothing else says


@pytest.mark.parametrize("claim", [
    "Quiet one-bedroom, no street noise at all!", "Peaceful, tranquil and full of light.", "Super quiet block, sunny and bright.",
    "Silent nights, a calm retreat from the city.", "Building amenities: a landscaped courtyard, a gym and a roof deck.",
    "Floor-to-ceiling bookshelves.", "Laundry in the basement, bike room."])
def test_a_sales_claim_or_an_amenity_never_becomes_a_key(claim):
    assert T.key(claim) == {}


def test_a_text_that_points_two_ways_gives_no_key():
    assert "floor" not in values("3rd floor one-bedroom. This sixth-floor home gets afternoon sun.")
    assert "side" not in values("The bedroom faces the quiet rear of the building. All windows overlook 14th Street.")
    assert "ac_units" not in values("Central air in the living room, a window unit in the bedroom.")


def test_rafas_click_confirms_a_key_and_his_correction_drops_it():
    text = "Third floor. The bedroom faces the street. The kitchen looks onto the air shaft."
    doc = photo.blank_labels("01")
    doc["labels"].update(floor=3, view="street")
    doc["prefilled"] = ["floor"]
    ok, waiting, corrected = T.confirmed(doc, text)
    assert ok == {} and set(waiting) == {"floor"} and corrected["view"]["label"] == "street"
    doc["prefilled"] = []
    ok, _, _ = T.confirmed(doc, text)
    assert set(ok) == {"floor"}                                               # side points two ways: no key at all


def test_the_labeler_carries_the_same_rules():
    assert T.labeler_rules() == json.loads(T.rules_json()), "run: python -m hush_eval photo sync-rules"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_labeler_keys_every_text_the_way_python_does():
    html = T.LABELER.read_text()
    js = re.search(r"// <text-key>.*?\n(.*?)// </text-key>", html, re.S).group(1)
    corpus = CASE_TEXTS + [EXAMPLE_TEXT, "Apt 12F, river views", "Third‑floor walk‑up, it’s floor–to–ceiling glass",
                           "Top floor of a 6-story building; window units; exposed concrete ceilings; corner unit"]
    script = f"const TK = {T.rules_json()};\n{js}\nconsole.log(JSON.stringify({json.dumps(corpus)}.map(textKey)));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    assert json.loads(out) == [T.key(t) for t in corpus]
