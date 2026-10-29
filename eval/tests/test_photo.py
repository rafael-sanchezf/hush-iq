"""The photo test: labels.json validation, the scorer on the synthetic 00/, the folder helpers."""
import json
import shutil

from hush_eval import checks as C
from hush_eval import photo

EXAMPLE = photo.REPO_ROOT / "00"


def test_template_and_example_labels_are_valid():
    template = json.loads((photo.REPO_ROOT / "template" / "labels.json").read_text())
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
    res = photo.score(photo.REPO_ROOT, include_example=True)
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
    shutil.copytree(photo.REPO_ROOT / "template", tmp_path / "template")
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


# ---------------------------------------------------------------- photos only, against the text key (HIQ-80)
def test_photo_tags_are_validated():
    doc = photo.blank_labels("05")
    doc["photo_tags"] = {"03.jpg": ["floor_plan", "printed_text"]}
    assert photo.validate_labels(doc) == []
    doc["photo_tags"] = {"03.jpg": ["selfie"]}
    assert any("photo_tags" in e for e in photo.validate_labels(doc))


def test_floor_is_compared_as_a_band():
    assert [photo.band(n) for n in (1, 4, 5, 12, 13, 60)] == ["low", "low", "mid", "mid", "high", "high"]
    assert photo.compared("floor", 3) == photo.compared("floor", 2) == "low"
    assert photo.compared("floor", "top") == "cant_tell"                      # no floor count, no height
    assert photo.compared("side", "corner") == "front" and photo.compared("side", "airshaft") == "rear"


def test_the_example_scores_the_photos_against_its_text_with_and_without_the_floor_plan():
    res = photo.score_text_key(photo.REPO_ROOT, include_example=True)
    [ex] = res["listings"]
    assert set(ex["keys"]) == {"floor", "ac_units", "wall_material"} and ex["tagged"] == ["04.png"]
    assert set(ex["corrected"]) == {"view"}                    # the text's air shaft is the kitchen; Rafa labeled the street
    every, clean = ex["runs"]["all"], ex["runs"]["clean"]
    assert every["floor"]["outcome"] == "agrees"               # the plan prints APT 3C
    assert clean["floor"]["outcome"] == "cant_tell"            # without it, nothing shows the height
    assert every["wall_material"]["outcome"] == clean["wall_material"]["outcome"] == "disagrees"
    assert every["side"] == {"outcome": "no_key", "photos": "front", "label": "front"}
    table = res["table"]["clean"]["fields"]
    assert table["floor"]["keys"] == 1 and table["floor"]["cant_tell"] == 1
    assert table["side"]["claimed"] == {"front": 1} and table["side"]["label_agrees"] == 1
    report = photo.text_key_report(res)
    assert "floor (band)" in report and "Without the tagged photos (1 tagged)" in report


def test_the_key_never_comes_from_the_model(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "00")
    before = photo.score_text_key(tmp_path, include_example=True)["listings"][0]["keys"]
    for name in ("model.photos.json", "model.photos-clean.json"):
        out = json.loads((tmp_path / "00" / name).read_text())
        out["fields"]["floor"] = {"value": 40, "status": "read", "evidence": [{"source": "photo:0", "what": "a skyline"}]}
        (tmp_path / "00" / name).write_text(json.dumps(out))
    res = photo.score_text_key(tmp_path, include_example=True)
    assert res["listings"][0]["keys"] == before
    assert res["listings"][0]["runs"]["all"]["floor"]["outcome"] == "disagrees"


def test_a_photos_only_run_sends_no_text_and_drops_the_tagged_photos(tmp_path, monkeypatch):
    shutil.copytree(EXAMPLE, tmp_path / "00")
    for name in ("model.photos.json", "model.photos-clean.json"):
        (tmp_path / "00" / name).unlink()
    text_run = (tmp_path / "00" / "model.json").read_text()
    sent = []
    real = photo.A.Service.call

    def spy(self, case, **inputs):
        sent.append((inputs["text"], len(inputs["photos"])))
        return real(self, case, **inputs)
    monkeypatch.setattr(photo.A.Service, "call", spy)
    lines = photo.run(tmp_path, "mock", "auto", include_example=True, photos_only=True)
    assert sent == [("", 4), ("", 3)], lines
    every = json.loads((tmp_path / "00" / "model.photos.json").read_text())
    clean = json.loads((tmp_path / "00" / "model.photos-clean.json").read_text())
    assert every["fields"]["floor"]["value"] == 3 and clean["fields"]["floor"]["status"] == "cant_tell"
    assert (tmp_path / "00" / "model.json").read_text() == text_run          # the text run's output is left alone


def test_the_folder_is_outside_git_when_rafa_names_one(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("HIQ_PHOTO_TEST", str(tmp_path))
    try:
        assert importlib.reload(photo).ROOT == tmp_path
        assert [d.name for d in photo.listing_dirs(tmp_path, include_example=True)] == ["00"]   # the example stays in the repo
    finally:
        monkeypatch.delenv("HIQ_PHOTO_TEST")
        importlib.reload(photo)


def test_check_and_run_name_what_the_reader_cannot_take(tmp_path):
    d = photo.new_listing(tmp_path, "https://example.test/1")
    (d / "listing.txt").write_text("Third floor.")
    for i in range(1, 15):
        shutil.copy(EXAMPLE / "photos" / "01.png", d / "photos" / f"{i:02d}.png")
    (d / "photos" / "15.heic").write_bytes(b"not read")
    sent, why = photo.reader_photos(photo.photos_of(d))
    assert len(sent) == 12 and sent[-1].name == "12.png"
    assert why == ["15.heic is a format the reader refuses", "14 photos: the reader takes the first 12"]
    lines, _, _ = photo.check(tmp_path)
    assert "the reader takes the first 12" in lines[0] and "15.heic" in lines[0]
