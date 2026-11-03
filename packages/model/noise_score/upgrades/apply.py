"""Apply every built source upgrade to one location's facade-neutral levels, and to the Manhattan sample.

The renter and the sample must be scored the same way, or the ranks mean nothing. So upgraded levels are used
only when manhattan_upgraded.json was built with exactly the modules, artifacts and research numbers available now;
otherwise the engine falls back to today's levels for everyone. Each source starts from the research numbers on the
same pulls (recal.py, [V10]), the sample from recal_sample.json.
"""
import hashlib
import importlib
import json
from pathlib import Path

from . import DATA, SLOTS, passthrough

SOURCES = ("street", "nightlife", "building", "sirens", "construction")
UPGRADED = DATA / "manhattan_upgraded.json"
_mods = {}


def module(name):
    if name not in _mods:
        try:
            _mods[name] = importlib.import_module(f"{__package__}.{name}")
        except ImportError:
            _mods[name] = None
    return _mods[name]


def _code_sha():
    """The upgrade modules' and recal.py's source, so an edited rule is caught as surely as a rebuilt artifact."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha1()
    for f in sorted(here.glob("*.py")) + [here.parent / "recal.py"]:
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def fingerprint():
    """Which sources have a module and a built artifact, with the artifact's size, the research numbers the sample
    was recomputed with [V10] and the code, so a stale sample is caught."""
    from .. import recal
    out = {}
    for n in SOURCES:
        art = DATA / f"{n}.json.gz"
        if module(n) is not None and art.exists():
            out[n] = art.stat().st_size
    if out and recal.sample():
        out["recal"] = recal.numbers_sha()
        out["code"] = _code_sha()
    return out


def apply(lat, lng, neutral, facts):
    """{source: {slot: level}} after upgrades, and {source: Upgrade}. A module that fails passes today through."""
    levels, ups = {}, {}
    for n in SOURCES:
        today = {s: float(neutral[n][s]) for s in SLOTS}
        m = module(n)
        try:
            up = m.upgrade(lat, lng, today, facts) if m is not None else passthrough(n, today)
        except Exception:   # an upgrade must never take the score down
            up = passthrough(n, today)
        levels[n] = {s: float(up.levels[s]) for s in SLOTS}
        ups[n] = up
    return levels, ups


def build_sample(b=None):
    """Upgraded levels for every Manhattan sample building, written next to the artifacts. Starts from the research
    numbers on the baseline's own pulls (recal.build_sample first)."""
    from .. import baseline, recal
    b = b or baseline.load()
    start = recal.sample()
    if start is None:
        raise RuntimeError("recal_sample.json is missing or built with other numbers: run python -m noise_score.recal")
    rows = []
    for s in b["samples"]:
        lv, _ = apply(s["lat"], s["lng"], start[s["bbl"]], s)
        rows.append({"bbl": s.get("bbl"), "levels": {n: {k: round(v, 3) for k, v in lv[n].items()} for n in SOURCES}})
    doc = {"fingerprint": fingerprint(), "as_of": b.get("as_of"), "samples": rows}
    DATA.mkdir(parents=True, exist_ok=True)
    UPGRADED.write_text(json.dumps(doc, separators=(",", ":")))
    return doc


_ready = None


def ready():
    """The upgraded sample, when it matches the modules and artifacts on disk; else None."""
    global _ready
    if _ready is None:
        doc = None
        if UPGRADED.exists():
            doc = json.loads(UPGRADED.read_text())
            if doc.get("fingerprint") != fingerprint() or not doc.get("fingerprint"):
                doc = None
        _ready = doc or False
    return _ready or None


if __name__ == "__main__":
    d = build_sample()
    print(f"upgraded sample built for {len(d['samples'])} buildings with sources "
          f"{sorted(n for n in d['fingerprint'] if n in SOURCES)}, research numbers {d['fingerprint'].get('recal')}")
