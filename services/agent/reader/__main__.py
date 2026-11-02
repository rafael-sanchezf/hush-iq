"""Read one listing from the terminal, turn by turn.

    .venv/bin/python -m reader fixtures/01-stated-rear.txt [--photo kitchen.jpg ...] [--turns 8] [--no-score] [--json]
                               [--ai off] [--provider openai|anthropic] [--model ID]

The house Meta key when MODEL_API_KEY is set (services/agent/.env), the basic reader otherwise or with --ai off.
--provider openai or anthropic reads the key from OPENAI_API_KEY or ANTHROPIC_API_KEY.
"""
import argparse
import json
import sys
from pathlib import Path

from . import loop, settings
from .client import from_env
from .listing import Answers, Listing, Photo
from .scoring import HostedScorer


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m reader", description=__doc__.split("\n\n")[0])
    p.add_argument("text", nargs="?", help="a file with the listing text, or - for stdin; omit for photos only")
    p.add_argument("--photo", action="append", default=[], help="a listing photo; repeat for more")
    p.add_argument("--turns", type=int, default=None)
    p.add_argument("--answers", default=None, help='JSON, e.g. {"sleep_from": 0, "bothers": ["sirens"]}')
    p.add_argument("--no-score", action="store_true", help="skip GeoSearch and the score API")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    p.add_argument("--ai", choices=("on", "off"), default="on")
    p.add_argument("--provider", choices=("meta", "openai", "anthropic"), default=None)
    p.add_argument("--model", default=None)
    a = p.parse_args(argv)

    settings.load_env()
    text = sys.stdin.read() if a.text == "-" else Path(a.text).read_text() if a.text else ""
    photos = [Photo.from_bytes(Path(f).read_bytes(), Path(f).name) for f in a.photo]
    listing = Listing(text=text, photos=photos, answers=Answers.parse(json.loads(a.answers) if a.answers else None))
    plan = from_env(a.provider, a.model, a.ai)
    scorer = None if a.no_score else HostedScorer()
    print(f"ai {plan.ai['mode']}, provider {plan.ai['provider']}, model {plan.ai['model'] or 'basic'}"
          + (f" ({plan.ai['reason']})" if plan.ai["reason"] else ""), file=sys.stderr)
    for kind, data in loop.read_listing(listing, plan=plan, scorer=scorer, turns=a.turns):
        if kind == "turn":
            mark = "ok " if data["ok"] else "ERR"
            brief = json.dumps(data["result"])[:160]
            print(f"{data['n']:>3} {data['by']:<5} {str(data['tool']):<15} {mark} {data['ms']:>6} ms  {brief}",
                  file=sys.stderr)
        elif a.json:
            print(json.dumps(data, indent=2))
        else:
            print(summary(data))


def summary(result):
    lines = [f"{result['status']} ({result['stopped']}), {result['turns']['used']} of {result['turns']['budget']} turns"]
    for group in ("fields", "observed"):
        for name, f in result[group].items():
            cites = "; ".join(" ".join(e["quote"].split()) if "quote" in e else f"{e['source']}: {e['what']}"
                             for e in f["evidence"])
            lines.append(f"  {name:<14} {f['status']:<9} {json.dumps(f['value']):<26} {cites}")
    lines.append(f"  position       {result['position']}")
    s = result["score"]
    if s:
        h = loop.headline(s)
        lines.append(f"  score          {result['score_engine']}: {h['verdict']}, quieter than "
                     f"{h['quieter_than']}% of Manhattan")
    lines += [f"  note           {n}" for n in result["notes"]]
    if result["ai"]["message"]:
        lines.append(f"  ai             {result['ai']['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
