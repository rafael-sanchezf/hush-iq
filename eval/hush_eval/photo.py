"""The photo test: the reader's answers on hand-saved listings against Rafa's labels, field by field.

    eval/photo_test/<nn>/listing.txt    the listing text, pasted by hand
    eval/photo_test/<nn>/photos/        every photo, saved by hand
    eval/photo_test/<nn>/labels.json    Rafa's labels, written by eval/labeler.html
    eval/photo_test/<nn>/model.json     the reader's result, written by `python -m hush_eval photo run`

Only template/ and the synthetic 00/ are tracked; the real listings stay on Rafa's disk (photo_test/.gitignore).
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import adapters as A
from . import checks as C
from . import shapes as S

ROOT = Path(__file__).resolve().parents[1] / "photo_test"
SCHEMA = "hush-iq/photo-labels/1"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".avif"}

# The threshold rule (README): a field reaches the score when, on the labeled set,
MIN_ACCURACY = 0.85     # it is right on at least 85% of the listings where Rafa could tell,
MAX_WRONG = 0.05        # wrong (a wrong value, or a value where Rafa could not tell) on under 5% of all listings,
MIN_ANSWERABLE = 10     # and Rafa could tell on at least 10, so 2 of 2 does not pass.


def listing_dirs(root=ROOT, include_example=False):
    out = []
    for d in sorted(Path(root).iterdir() if Path(root).is_dir() else []):
        if d.is_dir() and re.fullmatch(r"\d{2}", d.name) and (include_example or d.name != "00"):
            out.append(d)
    return out


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
    return errs


def complete(doc):
    labels = doc.get("labels") or {}
    return all(labels.get(n) is not None for n in S.PHOTO_FIELDS) and not doc.get("prefilled")


def blank_labels(listing_id, link=""):
    return {"schema": SCHEMA, "listing": listing_id, "link": link,
            "labels": {n: None for n in S.PHOTO_FIELDS}, "prefilled": [], "notes": "", "labeled_at": None}


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
        lines.append(f"{d.name}  {n:2d} photos  {len(text):5d} chars  {state}  ({model})")
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


# ---------------------------------------------------------------- run the reader on the set
def run(root=ROOT, mode="live", transport="auto", include_example=False, force=False):
    """Call the reader on each listing folder and save model.json beside the labels."""
    svc = A.Service("reader", mode, transport)
    lines = [f"reader: {svc.why}"]
    for d in listing_dirs(root, include_example):
        if (d / "model.json").exists() and not force:
            lines.append(f"{d.name} skipped, model.json exists (use --force)")
            continue
        text = (d / "listing.txt").read_text() if (d / "listing.txt").exists() else ""
        photos = [A._photo_payload(p) for p in photos_of(d)]
        case = {"listing": {"text": text, "photos": photos},
                "fixtures": {"reader": load_json(d / "model.fixture.json")}}
        try:
            out, meta = svc.call(case, text=text, photos=photos)
        except Exception as e:
            lines.append(f"{d.name} FAILED {type(e).__name__}: {e}")
            continue
        if out is None:
            lines.append(f"{d.name} no output ({svc.why})")
            continue
        (d / "model.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        probs = C.reader_grounding(out or {}, {"text": text, "photos": photos})
        lines.append(f"{d.name} {meta['latency_s']:.1f} s, {len([p for p in probs if p.hard])} grounding problems")
    return lines


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
