"""The photo test: labels.json validation, the scorer on the synthetic 00/, the folder helpers."""
import json
import shutil

from hush_eval import checks as C
from hush_eval import photo

EXAMPLE = photo.ROOT / "00"


def test_template_and_example_labels_are_valid():
    template = json.loads((photo.ROOT / "template" / "labels.json").read_text())
    assert photo.validate_labels(template) == []
    assert not photo.complete(template)
    example = json.loads((EXAMPLE / "labels.json").read_text())
    assert photo.validate_labels(example) == [] and photo.complete(example)


def test_bad_labels_are_named():
    doc = photo.blank_labels("05")
    doc["labels"].update(floor=0, side="north", view="sea", ac_units=True)
    doc["labels"]["glazing"] = "double"
    doc["prefilled"] = ["floor", "colour"]
    errs = " | ".join(photo.validate_labels(doc))
    for bit in ("floor 0", "side 'north'", "view 'sea'", "ac_units True", "unknown field 'glazing'", "prefilled"):
        assert bit in errs, bit


def test_prefilled_fields_are_not_complete_until_confirmed():
    doc = photo.blank_labels("05")
    doc["labels"] = {"floor": 3, "side": "front", "view": "cant_tell", "windows": "standard", "ac_units": "no",
                     "wall_material": "cant_tell"}
    doc["prefilled"] = ["floor"]
    assert photo.validate_labels(doc) == [] and not photo.complete(doc)
    doc["prefilled"] = []
    assert photo.complete(doc)


def test_the_scorer_counts_cant_tell_apart_from_wrong():
    res = photo.score(photo.ROOT, include_example=True)
    [only] = res["per_listing"]
    got = {k: v["outcome"] for k, v in only["outcomes"].items()}
    assert got == {"floor": C.CORRECT, "side": C.CORRECT, "view": C.ABSTAINED, "windows": C.CORRECT,
                   "ac_units": C.CORRECT, "wall_material": C.WRONG}
    view, wall = res["fields"]["view"], res["fields"]["wall_material"]
    assert view["accuracy"] == 0 and view["wrong_rate"] == 0
    assert wall["accuracy"] == 0 and wall["wrong_rate"] == 1
    assert not any(r["passes"] for r in res["fields"].values())   # one listing is under the minimum of ten
    assert "reaches the score" in photo.score_report(res)


def test_the_example_model_output_is_grounded():
    model = json.loads((EXAMPLE / "model.json").read_text())
    listing = {"text": (EXAMPLE / "listing.txt").read_text(), "photos": photo.photos_of(EXAMPLE)}
    assert [p for p in C.reader_grounding(model, listing) if p.hard] == []


def test_the_rule_needs_ten_listings_85_percent_and_no_wrong(tmp_path):
    for i in range(1, 21):
        d = tmp_path / f"{i:02d}"
        (d / "photos").mkdir(parents=True)
        (d / "listing.txt").write_text("x")
        labels = photo.blank_labels(d.name)
        labels["labels"].update(floor=4, side="front", view="street", windows="standard", ac_units="yes", wall_material="brick")
        (d / "labels.json").write_text(json.dumps(labels))
        model = json.loads((EXAMPLE / "model.json").read_text())
        model["fields"]["floor"]["value"] = 4
        # side: 18 right, 2 can't tell -> 90%, no wrong: passes. floor: 19 right, 1 wrong -> 5% wrong: fails.
        if i > 18:
            model["fields"]["side"] = {"value": None, "status": "cant_tell", "evidence": []}
            model["position"] = "unknown"
        if i == 20:
            model["fields"]["floor"]["value"] = 5
        (d / "model.json").write_text(json.dumps(model))
    res = photo.score(tmp_path)
    assert res["fields"]["side"]["passes"] and res["fields"]["side"]["accuracy"] == 0.9
    assert not res["fields"]["floor"]["passes"] and res["fields"]["floor"]["wrong_rate"] == 0.05
    assert res["fields"]["ac_units"]["passes"]
    assert not res["fields"]["view"]["passes"]


def test_new_check_and_collect(tmp_path):
    shutil.copytree(photo.ROOT / "template", tmp_path / "template")
    d = photo.new_listing(tmp_path, link="")
    assert d.name == "01" and (d / "photos").is_dir() and photo.validate_labels(json.loads((d / "labels.json").read_text())) == []
    lines, ready, problems = photo.check(tmp_path)
    assert ready == 0 and problems == 1 and "partly labeled" in lines[0]
    downloads = tmp_path / "dl"
    downloads.mkdir()
    labels = photo.blank_labels("01")
    labels["labels"].update(floor="cant_tell", side="rear", view="courtyard", windows="standard", ac_units="no", wall_material="brick")
    (downloads / "labels-01.json").write_text(json.dumps(labels))
    (downloads / "labels-02.json").write_text(json.dumps(labels))
    out = photo.collect(downloads, tmp_path)
    assert out[0] == "labels-01.json -> 01/labels.json" and "does not exist" in out[1]
    (d / "listing.txt").write_text("pasted text")
    lines, ready, problems = photo.check(tmp_path)
    assert ready == 1 and problems == 0
