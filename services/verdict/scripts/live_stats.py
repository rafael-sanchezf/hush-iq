"""The live model, several runs per example address: how often the checks refuse a draft, why, how long it takes.

    .venv/bin/python scripts/live_stats.py --runs 3

Needs a key in services/verdict/.env (MODEL_API_KEY or BASETEN_API_KEY); each run is one or two calls.
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from examples import EXAMPLES  # noqa: E402
from verdict import evidence, writer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    live = writer.from_env()
    if not live:
        sys.exit("no key in services/verdict/.env")
    runs, refused, outcomes, reasons, ms, completion, reasoning = 0, 0, Counter(), Counter(), [], [], []
    for ex in EXAMPLES:
        score = json.loads((ROOT / "tests" / "fixtures" / ex["score"]).read_text())
        lines = evidence.build(score, None, ex["fields"])
        for _ in range(args.runs):
            out = writer.write(lines, live)
            runs += 1
            attempts = [t for t in out["trace"] if t.get("attempt")]
            outcomes[("first draft passed" if attempts[0]["ok"] else "passed on the retry" if out["writer"] != "template"
                      else "template fallback")] += 1
            for t in attempts:
                ms.append(t["ms"])
                refused += not t["ok"]
                u = t.get("usage") or {}
                completion += [u["completion_tokens"]] if "completion_tokens" in u else []
                reasoning += [u["reasoning_tokens"]] if "reasoning_tokens" in u else []
                for e in t["errors"]:
                    reasons[e.split(": ", 1)[-1].split(" (")[0][:90]] += 1
            print(f"{ex['score']}: {out['writer']}, " + "; ".join(
                f"attempt {t['attempt']} {'ok' if t['ok'] else 'refused'} {t['ms'] / 1000:.1f} s" for t in attempts))
    calls = len(ms)
    print(f"\n{live.name} ({live.model}), {runs} runs, {calls} calls, reasoning effort {live.reasoning_effort}")
    for k, v in outcomes.most_common():
        print(f"- {k}: {v} of {runs}")
    print(f"- drafts refused: {refused} of {calls}")
    for k, v in reasons.most_common():
        print(f"  - {v} x {k}")
    print(f"- latency per call: median {statistics.median(ms) / 1000:.1f} s, max {max(ms) / 1000:.1f} s")
    if completion:
        print(f"- completion tokens per call: median {int(statistics.median(completion))}, max {max(completion)}"
              + (f"; reasoning median {int(statistics.median(reasoning))}, max {max(reasoning)}" if reasoning else ""))


if __name__ == "__main__":
    main()
