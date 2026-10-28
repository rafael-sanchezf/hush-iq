"""noise-score "158 Bedford Ave, Brooklyn" --floor 4 --position front --sleep light --bothers neighbors"""
import argparse
import json
import sys

from . import baseline, model, sources


def render(res):
    a = res["address"]
    u = res["unit"]
    lines = []
    lines.append(f"{a['label']}")
    where = f"floor {u['floor']}" if u["floor"] else "floor unknown"
    if u["top_floor"]:
        where += " (top)"
    where += f", {u['position']}"
    lines.append(f"Unit: {where}")
    lines.append("")
    lines.append(f"PERSONAL NOISE SCORE  {res['score']:>3}   (0 loud .. 100 quiet)")
    bt = res["by_time"]
    lines.append(f"  night {bt['night']:>3}   early {bt['early']:>3}   day {bt['day']:>3}")
    lines.append(f"  street-only, HowLoud-style: {res['street_only_score']}")
    m = res.get("manhattan")
    if m:
        lines.append(f"  VERDICT: {m['verdict']} for Manhattan (quieter than {m['quieter_than']:.0f}% of {m['n']} sampled "
                     f"apartments for this renter, pulled {m['as_of']})")
        for w in model.WINDOWS:
            r = baseline.window_rank(res, w, model.Unit(u["floor"], u["position"]))
            lines.append(f"    {w:<5} {r['level_db']:.0f} dB at the window, {r['verdict'].lower()} "
                         f"(Manhattan typical {r['median_db']:.0f}, middle half {r['p25_db']:.0f} to {r['p75_db']:.0f})")
    if res["profile"]:
        p = res["profile"]
        lines.append(f"  profile: {p['sleep']} sleeper, {'works from home' if p['wfh'] else 'out by day'}, bothered by {', '.join(p['bothers']) or 'nothing named'}")
    lines.append("")
    for ing in res["ingredients"]:
        s = ing["scores"]
        tag = "  (temporary)" if ing["temporary"] else ""
        up = "  (weighted up)" if ing.get("weighted_up") else ""
        lines.append(f"{ing['label'].upper():<13} night {s['night']:>3}  early {s['early']:>3}  day {s['day']:>3}{tag}{up}")
        for e in ing["evidence"]:
            lines.append(f"    - {e}")
    lines.append("")
    lines.append(f"as of {res['as_of']}, {res['lookback_months']} months of 311")
    return "\n".join(lines)


def _manhattan(res, unit, profile):
    """Rank against the Manhattan baseline [M12] when the file exists. Other boroughs get it too, read as
    'compared with Manhattan'."""
    try:
        return baseline.rank(res["internal_level"], unit, profile)
    except FileNotFoundError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="noise-score")
    ap.add_argument("address")
    ap.add_argument("--floor", type=int)
    ap.add_argument("--position", choices=["front", "rear", "unknown"], default="unknown")
    ap.add_argument("--sleep", choices=["light", "normal", "heavy"])
    ap.add_argument("--wfh", action="store_true")
    ap.add_argument("--bothers", default="", help="comma list: traffic,people,neighbors,sirens,construction")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="ignore the disk cache")
    args = ap.parse_args(argv)
    try:
        inputs = sources.pull_all(args.address, fresh=args.fresh)
    except sources.SourceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    unit = model.Unit(floor=args.floor, position=args.position)
    profile = None
    if args.sleep or args.wfh or args.bothers:
        profile = model.Profile(sleep=args.sleep or "normal", wfh=args.wfh,
                                bothers=[b.strip() for b in args.bothers.split(",") if b.strip()])
    res = model.score(inputs, unit, profile)
    res["manhattan"] = _manhattan(res, unit, profile)
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
