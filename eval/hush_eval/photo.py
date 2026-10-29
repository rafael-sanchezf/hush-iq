"""The photo test: the reader's answers on hand-saved listings against Rafa's labels, field by field.

    eval/photo_test/<nn>/listing.txt    the listing text, pasted by hand
    eval/photo_test/<nn>/photos/        every photo, saved by hand
    eval/photo_test/<nn>/labels.json    Rafa's labels, written by eval/labeler.html
    eval/photo_test/<nn>/model.json     the reader's result, written by `python -m hush_eval photo run`
    eval/photo_test/<nn>/model.photos.json         the reader on the photos alone, no text (`photo run --photos-only`)
    eval/photo_test/<nn>/model.photos-clean.json   the same without the photos Rafa tagged as leaking the answer

Only template/ and the synthetic 00/ are tracked. Rafa's listings live outside git, in the folder HIQ_PHOTO_TEST
names, else ~/Documents/hush-iq/photo_test when it exists (the extension's Save writes there), else eval/photo_test,
whose .gitignore keeps them out of the public repo.

The text key (textkey.py, HIQ-80) scores the photos-only run against what the listing's own text states, so the
fields the text states need no photo labeling: a confirm click is the label.
"""
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import adapters as A
from . import checks as C
from . import shapes as S
from . import textkey as T

REPO_ROOT = Path(__file__).resolve().parents[1] / "photo_test"          # template/ and the synthetic 00/
HOME_ROOT = Path.home() / "Documents" / "hush-iq" / "photo_test"
ROOT = Path(os.environ.get("HIQ_PHOTO_TEST") or (HOME_ROOT if HOME_ROOT.is_dir() else REPO_ROOT)).expanduser()
SCHEMA = "hush-iq/photo-labels/1"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".avif"}
READER_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}   # what the reader accepts (services/agent listing.py)
READER_MAX_PHOTOS = 12                                     # and how many per listing

# The threshold rule (README): a field reaches the score when, on the labeled set,
MIN_ACCURACY = 0.85     # it is right on at least 85% of the listings where Rafa could tell,
MAX_WRONG = 0.05        # wrong (a wrong value, or a value where Rafa could not tell) on under 5% of all listings,
MIN_ANSWERABLE = 10     # and Rafa could tell on at least 10, so 2 of 2 does not pass.

# Photos that print the answer: a floor plan with the unit number or a compass, a photo of a sign or a door
# number. Rafa tags them in the labeler; the photos-only run is scored with them and without them.
LEAK_TAGS = ("floor_plan", "printed_text")
# A window view gives a height, not a number, so the photos-only floor is scored as a band.
FLOOR_BANDS = (("low", 1, 4), ("mid", 5, 12), ("high", 13, S.FLOOR_MAX))
PHOTOS_ONLY = {"all": "model.photos.json", "clean": "model.photos-clean.json"}


def listing_dirs(root=ROOT, include_example=False):
    out = []
    for d in sorted(Path(root).iterdir() if Path(root).is_dir() else []):
        if d.is_dir() and re.fullmatch(r"\d{2}", d.name) and (include_example or d.name != "00"):
            out.append(d)
    if include_example and not (Path(root) / "00").is_dir() and (REPO_ROOT / "00").is_dir():
        out.insert(0, REPO_ROOT / "00")                    # Rafa's folder is outside git: the example stays in it
    return out


def reader_photos(paths):
    """The photos the reader can take, in order, and why any others are left out."""
    sent = [p for p in paths if p.suffix.lower() in READER_EXT]
    why = [f"{p.name} is a format the reader refuses" for p in paths if p.suffix.lower() not in READER_EXT]
    if len(sent) > READER_MAX_PHOTOS:
        why.append(f"{len(sent)} photos: the reader takes the first {READER_MAX_PHOTOS}")
        sent = sent[:READER_MAX_PHOTOS]
    return sent, why


def photos_of(d):
    p = Path(d) / "photos"
    return sorted(f for f in p.iterdir() if f.suffix.lower() in PHOTO_EXT) if p.is_dir() else []


# ---------------------------------------------------------------- labels.json
def validate_labels(doc):
    """Problems with a labels.json, as strings. Empty means valid. Unlabeled fields (null) are allowed here;
    `complete()` says whether every field has an answer."""
    errs = []
    if not isinstance(doc, dict):
        return ["labels.json is not an object"]
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema is {doc.get('schema')!r}, expected {SCHEMA!r}")
    labels = doc.get("labels")
    if not isinstance(labels, dict):
        return errs + ["no labels object"]
    for name in labels:
        if name not in S.PHOTO_FIELDS:
            errs.append(f"unknown field {name!r}")
    for name in S.PHOTO_FIELDS:
        v = labels.get(name)
        if v is None or v == S.CANT_TELL:
            continue
        if name == "floor":
            if isinstance(v, bool) or not isinstance(v, int) or not S.FLOOR_MIN <= v <= S.FLOOR_MAX:
                errs.append(f"floor {v!r} is not an integer from {S.FLOOR_MIN} to {S.FLOOR_MAX} or cant_tell")
        elif name == "side":
            if v not in S.SIDES:
                errs.append(f"side {v!r} is not front, rear or cant_tell")
        elif v not in S.OBSERVED_VALUES[name]:
            errs.append(f"{name} {v!r} is not one of {', '.join(S.OBSERVED_VALUES[name] + (S.CANT_TELL,))}")
    pre = doc.get("prefilled", [])
    if not isinstance(pre, list) or any(p not in S.PHOTO_FIELDS for p in pre):
        errs.append(f"prefilled {pre!r} is not a list of field names")
    tags = doc.get("photo_tags", {})
    if not isinstance(tags, dict) or any(not isinstance(v, list) or any(t not in LEAK_TAGS for t in v) for v in tags.values()):
        errs.append(f"photo_tags {tags!r} is not {{photo file: [{', '.join(LEAK_TAGS)}]}}")
    return errs


def complete(doc):
    labels = doc.get("labels") or {}
    return all(labels.get(n) is not None for n in S.PHOTO_FIELDS) and not doc.get("prefilled")


def blank_labels(listing_id, link=""):
    return {"schema": SCHEMA, "listing": listing_id, "link": link,
            "labels": {n: None for n in S.PHOTO_FIELDS}, "prefilled": [], "photo_tags": {}, "notes": "", "labeled_at": None}


def load_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- check: is the set ready to score
def check(root=ROOT, include_example=False):
    """One line per listing: photos, text, labels state. Returns (lines, ready_count, problems)."""
    lines, ready, problems = [], 0, 0
    for d in listing_dirs(root, include_example):
        text = (d / "listing.txt").read_text().strip() if (d / "listing.txt").exists() else ""
        n = len(photos_of(d))
        doc = load_json(d / "labels.json")
        errs = validate_labels(doc) if doc is not None else ["no labels.json"]
        state = "invalid: " + "; ".join(errs) if errs else ("labeled" if complete(doc) else "partly labeled")
        if not text:
            state += "; listing.txt is empty"
        if not errs and complete(doc) and text:
            ready += 1
        else:
            problems += 1
        model = "model.json" if (d / "model.json").exists() else "not run"
        _, left_out = reader_photos(photos_of(d))
        lines.append(f"{d.name}  {n:2d} photos  {len(text):5d} chars  {state}  ({model})"
                     + "".join(f"; {w}" for w in left_out))
    return lines, ready, problems


# ---------------------------------------------------------------- score
def model_answers(result):
    """The reader's answer per photo-test field, from its result."""
    out = {n: C.field_value(result, n) for n in S.PHOTO_FIELDS}
    if out.get("side") is None and result.get("position") in ("front", "rear"):
        out["side"] = result["position"]
    return out


def score(root=ROOT, include_example=False):
    """Per-field accuracy of model.json against labels.json, "can't tell" counted apart from wrong."""
    per_listing = []
    for d in listing_dirs(root, include_example):
        labels, result = load_json(d / "labels.json"), load_json(d / "model.json")
        if labels is None or result is None or validate_labels(labels):
            continue
        got = model_answers(result)
        outcomes = {}
        for name in S.PHOTO_FIELDS:
            gold = labels["labels"].get(name)
            if gold is None:
                continue                                     # not labeled yet: not counted
            outcomes[name] = {"outcome": C.compare(name, gold, got.get(name)), "gold": gold, "got": got.get(name)}
        per_listing.append({"listing": d.name, "outcomes": outcomes})
    table = C.tally([p["outcomes"] for p in per_listing], S.PHOTO_FIELDS)
    for name, row in table.items():
        row["passes"] = passes(row)
    return {"listings": len(per_listing), "per_listing": per_listing, "fields": table}


def passes(row):
    return bool(row["answerable"] >= MIN_ANSWERABLE and row["accuracy"] is not None and row["accuracy"] >= MIN_ACCURACY
                and row["wrong_rate"] is not None and row["wrong_rate"] < MAX_WRONG)


def score_report(res):
    pct = lambda x: "  n/a" if x is None else f"{100 * x:4.0f}%"
    lines = [f"Photo test, {res['listings']} listings scored", "",
             f"{'field':14} {'labeled':>7} {'could tell':>10} {'correct':>8} {'wrong':>6} {'model cant_tell':>15}"
             f" {'invented':>8} {'accuracy':>9} {'wrong %':>8}  reaches the score"]
    for name, r in res["fields"].items():
        right = r["correct"] - r["silent_ok"]
        lines.append(f"{name:14} {r['n']:7d} {r['answerable']:10d} {right:8d} {r['wrong']:6d} {r['cant_tell']:15d}"
                     f" {r['invented']:8d} {pct(r['accuracy']):>9} {pct(r['wrong_rate']):>8}  {'yes' if r['passes'] else 'no'}")
    lines += ["", f"Rule: accuracy at least {MIN_ACCURACY:.0%} where Rafa could tell (at least {MIN_ANSWERABLE} listings),"
              f" wrong under {MAX_WRONG:.0%} of all labeled. Model cant_tell lowers accuracy but is never wrong."]
    return "\n".join(lines)


# ---------------------------------------------------------------- the text key: photos only, against the text
AGREES, DISAGREES, NO_KEY = "agrees", "disagrees", "no_key"


def band(floor):
    n = C._int(floor) if not isinstance(floor, bool) else None
    return next((name for name, lo, hi in FLOOR_BANDS if n is not None and lo <= n <= hi), None)


def compared(field, value):
    """A value as the text-key score compares it: the photo test's vocabulary, and the floor as a band. A floor of
    "top" with no floor count gives no height, so it counts as can't tell."""
    v = S.CANT_TELL if value is None else S.canonical(field, value)
    if field == "floor" and v != S.CANT_TELL:
        v = band(v) or S.CANT_TELL
    return v


def score_text_key(root=ROOT, include_example=False):
    """The photos-only runs against the confirmed text key, field by field. Where the text states nothing, what the
    photos claimed, and whether that matches a label Rafa gave from the photos."""
    listings = []
    for d in listing_dirs(root, include_example):
        labels = load_json(d / "labels.json")
        if labels is None or validate_labels(labels):
            continue
        text = (d / "listing.txt").read_text() if (d / "listing.txt").exists() else ""
        keys, waiting, corrected = T.confirmed(labels, text)
        tagged = sorted(n for n, t in (labels.get("photo_tags") or {}).items() if t)
        runs = {v: load_json(d / f) for v, f in PHOTOS_ONLY.items()}
        if runs["clean"] is None and not tagged:
            runs["clean"] = runs["all"]                    # nothing tagged: the clean run is the same run
        pre = set(labels.get("prefilled") or [])
        entry = {"listing": d.name, "keys": keys, "waiting": sorted(waiting), "corrected": corrected, "tagged": tagged,
                 "runs": {}}
        for variant, result in runs.items():
            if result is None:
                continue
            got = model_answers(result)
            per = {}
            for field in S.PHOTO_FIELDS:
                photos = compared(field, got.get(field))
                if field in keys:
                    said = compared(field, keys[field]["value"])
                    outcome = C.ABSTAINED if photos == S.CANT_TELL else AGREES if photos == said else DISAGREES
                    per[field] = {"outcome": outcome, "text": said, "photos": photos, "quote": keys[field]["quote"]}
                else:
                    label = labels["labels"].get(field)
                    label = None if label in (None, S.CANT_TELL) or field in pre else compared(field, label)
                    per[field] = {"outcome": NO_KEY, "photos": photos, "label": label}
            entry["runs"][variant] = per
        listings.append(entry)
    return {"listings": listings, "table": {v: _key_table(listings, v) for v in PHOTOS_ONLY},
            "keys": sum(len(e["keys"]) for e in listings), "waiting": sum(len(e["waiting"]) for e in listings),
            "corrected": sum(len(e["corrected"]) for e in listings),
            "tagged": sum(len(e["tagged"]) for e in listings)}


def _key_table(listings, variant):
    rows = {}
    for field in S.PHOTO_FIELDS:
        r = {"keys": 0, AGREES: 0, DISAGREES: 0, C.ABSTAINED: 0, "silent": 0, "claimed": {}, "labeled": 0, "label_agrees": 0}
        for e in listings:
            o = (e["runs"].get(variant) or {}).get(field)
            if not o:
                continue
            if o["outcome"] != NO_KEY:
                r["keys"] += 1
                r[o["outcome"]] += 1
                continue
            r["silent"] += 1
            if o["photos"] != S.CANT_TELL:
                r["claimed"][o["photos"]] = r["claimed"].get(o["photos"], 0) + 1
                if o["label"] is not None:
                    r["labeled"] += 1
                    r["label_agrees"] += o["label"] == o["photos"]
        rows[field] = r
    return {"listings": sum(1 for e in listings if variant in e["runs"]), "fields": rows}


def text_key_report(res):
    lines = [f"Photos only, against what the listing text states: {res['keys']} confirmed keys in "
             f"{len(res['listings'])} listings ({res['waiting']} waiting for a confirm click, {res['corrected']} corrected by Rafa)",
             "Floor is compared as a band: " + ", ".join(f"{n} {lo} to {hi}" if hi < S.FLOOR_MAX else f"{n} {lo} and up"
                                                         for n, lo, hi in FLOOR_BANDS) + "."]
    titles = {"all": "Every photo", "clean": f"Without the tagged photos ({res['tagged']} tagged)"}
    for variant, t in res["table"].items():
        lines += ["", f"{titles[variant]}: {t['listings']} listings",
                  f"{'field':14} {'text key':>8} {'agrees':>7} {'disagrees':>9} {'cant_tell':>9}   text silent: photos claimed"
                  f" (Rafa's photo label agrees)"]
        for field, r in t["fields"].items():
            claimed = ", ".join(f"{v} {n}" for v, n in sorted(r["claimed"].items())) or "-"
            agree = f" ({r['label_agrees']} of {r['labeled']} labeled)" if r["labeled"] else ""
            name = "floor (band)" if field == "floor" else field
            lines.append(f"{name:14} {r['keys']:8d} {r[AGREES]:7d} {r[DISAGREES]:9d} {r[C.ABSTAINED]:9d}   "
                         f"{claimed}{agree}")
    lines += ["", "A key is a sentence of the listing's own text, found by the rules in hush_eval/textkey.py and "
              "confirmed by Rafa's click. No model output is ever a key."]
    return "\n".join(lines)


# ---------------------------------------------------------------- run the reader on the set
def run(root=ROOT, mode="live", transport="auto", include_example=False, force=False, photos_only=False):
    """Call the reader on each listing folder and save model.json beside the labels. With photos_only, the reader
    gets no text: model.photos.json from every photo, and model.photos-clean.json without the tagged ones."""
    svc = A.Service("reader", mode, transport)
    lines = [f"reader: {svc.why}" + (", photos only: no listing text is sent" if photos_only else "")]
    for d in listing_dirs(root, include_example):
        text = (d / "listing.txt").read_text() if (d / "listing.txt").exists() else ""
        if not photos_only:
            lines.append(_read(svc, d, "model.json", text, photos_of(d), force))
            continue
        tags = (load_json(d / "labels.json") or {}).get("photo_tags") or {}
        clean = [p for p in photos_of(d) if not tags.get(p.name)]
        lines.append(_read(svc, d, PHOTOS_ONLY["all"], "", photos_of(d), force))
        if len(clean) == len(photos_of(d)):
            lines.append(f"{d.name} no photo tagged: the clean run is the same run")
        elif not clean:
            lines.append(f"{d.name} every photo is tagged: no clean run")
        else:
            lines.append(_read(svc, d, PHOTOS_ONLY["clean"], "", clean, force))
    return lines


def _read(svc, d, out_name, text, photo_paths, force):
    if (d / out_name).exists() and not force:
        return f"{d.name} skipped, {out_name} exists (use --force)"
    photo_paths, left_out = reader_photos(photo_paths)
    photos = [A._photo_payload(p) for p in photo_paths]
    case = {"listing": {"text": text, "photos": photos},
            "fixtures": {"reader": load_json(d / out_name.replace(".json", ".fixture.json"))}}
    try:
        out, meta = svc.call(case, text=text, photos=photos)
    except Exception as e:
        return f"{d.name} FAILED {type(e).__name__}: {e}"
    if out is None:
        return f"{d.name} no output ({svc.why})"
    (d / out_name).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    probs = C.reader_grounding(out or {}, {"text": text, "photos": photos})
    return (f"{d.name} {out_name}: {len(photos)} photos, {meta['latency_s']:.1f} s, {len([p for p in probs if p.hard])} grounding problems"
            + "".join(f"; {w}" for w in left_out))


# ---------------------------------------------------------------- the browser fallback
def collect(downloads, root=ROOT):
    """Move labels-<nn>.json files saved by the labeler's download fallback into <nn>/labels.json."""
    lines = []
    for f in sorted(Path(downloads).expanduser().glob("labels-[0-9][0-9]*.json")):
        m = re.match(r"labels-(\d{2})", f.name)
        doc = load_json(f)
        errs = validate_labels(doc) if doc is not None else ["not JSON"]
        if errs:
            lines.append(f"{f.name}: not moved, {'; '.join(errs)}")
            continue
        dest = Path(root) / m.group(1)
        if not dest.is_dir():
            lines.append(f"{f.name}: not moved, {dest} does not exist")
            continue
        shutil.move(str(f), dest / "labels.json")
        lines.append(f"{f.name} -> {dest.name}/labels.json")
    return lines or ["no labels-<nn>.json files found"]


def new_listing(root=ROOT, link=""):
    """Make the next <nn>/ folder from the template. Returns its path."""
    taken = {d.name for d in listing_dirs(root, include_example=True)}
    nn = next(f"{i:02d}" for i in range(1, 100) if f"{i:02d}" not in taken)
    d = Path(root) / nn
    (d / "photos").mkdir(parents=True)
    (d / "listing.txt").write_text("")
    doc = blank_labels(nn, link)
    doc["labeled_at"] = None
    (d / "labels.json").write_text(json.dumps(doc, indent=2) + "\n")
    return d


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
