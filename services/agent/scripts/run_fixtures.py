"""Run the five synthetic listings through the reader and compare with fixtures/expected.json.

    .venv/bin/python scripts/run_fixtures.py [--no-score] [--turns 8] [--save results.json]

Live when MODEL_API_KEY is set (services/agent/.env), mock otherwise. Exits 1 if any field differs.
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
from reader.listing import Listing  # noqa: E402
from reader.scoring import HostedScorer  # noqa: E402

KEYS = ("address", "unit", "floor", "side", "position")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-score", action="store_true")
    p.add_argument("--turns", type=int, default=None)
    p.add_argument("--save", default=None, help="write every result here as JSON")
    a = p.parse_args()

    settings.load_env()
    expected = json.loads((AGENT / "fixtures" / "expected.json").read_text())
    scorer = None if a.no_score else HostedScorer()
    misses, saved = 0, {}
    for name, want in ((k, v) for k, v in expected.items() if not k.startswith("_")):
        client, mode = make_client()
        started = time.perf_counter()
        result = loop.read(Listing(text=(AGENT / "fixtures" / name).read_text()), client=client, scorer=scorer,
                           turns=a.turns, mode=mode)
        seconds = time.perf_counter() - started
        got = {k: result["fields"][k]["value"] for k in KEYS[:-1]}
        got["position"] = result["position"]
        refusals = sum(len(t["result"].get("refused", {})) for t in result["trace"] if t["by"] == "model")
        wrong = [k for k in KEYS if got[k] != want[k]]
        misses += bool(wrong)
        verdict = (result["score"] or {}) and loop.headline(result["score"])["verdict"]
        print(f"{'ok  ' if not wrong else 'MISS'} {name:<28} {mode} {result['status']:<8} "
              f"turns {result['turns']['used']}/{result['turns']['budget']}  refusals {refusals}  {seconds:5.1f} s"
              f"  score {result['score_engine']} {verdict}")
        for k in wrong:
            print(f"       {k}: got {got[k]!r}, expected {want[k]!r}")
        saved[name] = result
    if a.save:
        Path(a.save).write_text(json.dumps(saved, indent=1))
    print(f"{5 - misses} of 5 fixtures match")
    sys.exit(1 if misses else 0)


if __name__ == "__main__":
    main()
