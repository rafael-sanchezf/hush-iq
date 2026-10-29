"""Run the synthetic listings through the reader and compare with fixtures/expected.json.

    .venv/bin/python scripts/run_fixtures.py [--only 06,07] [--no-score] [--turns 8] [--save results.json]

Live when MODEL_API_KEY is set (services/agent/.env), mock otherwise. Mock skips the fixtures with photos (it
cannot see). Exits 1 if any score field differs; observed fields from photos are printed, not counted.
"""
import argparse
import json
import sys
import time
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT))

from reader import loop, settings  # noqa: E402
from reader.client import make_client  # noqa: E402
from reader.listing import Listing, Photo  # noqa: E402
from reader.scoring import HostedScorer  # noqa: E402

KEYS = ("address", "unit", "floor", "side", "position")
FIXTURES = AGENT / "fixtures"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", default=None, help="comma list of fixture name prefixes, e.g. 06,07")
    p.add_argument("--no-score", action="store_true")
    p.add_argument("--turns", type=int, default=None)
    p.add_argument("--save", default=None, help="write every result here as JSON")
    a = p.parse_args()

    settings.load_env()
    expected = {k: v for k, v in json.loads((FIXTURES / "expected.json").read_text()).items() if not k.startswith("_")}
    if a.only:
        expected = {k: v for k, v in expected.items() if any(k.startswith(o) for o in a.only.split(","))}
    scorer = None if a.no_score else HostedScorer()
    ran = misses = 0
    saved = {}
    for name, want in expected.items():
        client, mode = make_client()
        if want.get("photos") and mode == "mock":
            print(f"skip {name:<28} mock cannot see photos")
            continue
        photos = [Photo.from_bytes((FIXTURES / f).read_bytes(), Path(f).name) for f in want.get("photos", [])]
        started = time.perf_counter()
        result = loop.read(Listing(text=(FIXTURES / name).read_text(), photos=photos), client=client, scorer=scorer,
                           turns=a.turns, mode=mode)
        seconds = time.perf_counter() - started
        got = {k: result["fields"][k]["value"] for k in KEYS[:-1]}
        got["position"] = result["position"]
        refusals = sum(len(t["result"].get("refused", {})) for t in result["trace"] if t["by"] == "model")
        wrong = [k for k in KEYS if got[k] != want[k]]
        ran += 1
        misses += bool(wrong)
        verdict = loop.headline(result["score"])["verdict"] if result["score"] else None
        print(f"{'ok  ' if not wrong else 'MISS'} {name:<28} {mode} {result['status']:<8} "
              f"turns {result['turns']['used']}/{result['turns']['budget']}  refusals {refusals}  {seconds:5.1f} s"
              f"  score {result['score_engine']} {verdict}")
        for k in wrong:
            print(f"       {k}: got {got[k]!r}, expected {want[k]!r}")
        for k, v in want.get("observed", {}).items():
            seen = result["observed"][k]["value"]
            ok = seen in v if isinstance(v, list) else seen == v
            print(f"       observed {k}: {'ok  ' if ok else 'diff'} got {seen!r}, expected {v!r}")
        saved[name] = result
    if a.save:
        Path(a.save).write_text(json.dumps(saved, indent=1))
    print(f"{ran - misses} of {ran} fixtures match")
    sys.exit(1 if misses else 0)


if __name__ == "__main__":
    main()
