"""python -m hush_eval <command>, run from eval/.

    run                    the 20 cases, mock mode (no model, no key, no cost)
    run --live             the same against the real models; per-field accuracy, cost and latency per case
    run --live --record    and save the real outputs into the cases, so mock mode replays them
    run --ai off           the product with AI off: the reader's rules, the template verdict, no permit adjustment (free)
    run --provider openai  live through a caller's key (OPENAI_API_KEY or ANTHROPIC_API_KEY, environment or eval/.env)
    photo new [--link URL] make the next photo_test/<nn>/ folder from the template
    photo check            is every listing saved and labeled
    photo run              the reader on every listing, model.json beside labels.json (live by default)
    photo run --photos-only  the reader on the photos alone, with and without the photos tagged as leaking
    photo score            per-field accuracy against the labels, and which fields reach the score
    photo textkey          the photos-only runs against what each listing's text states
    photo sync-rules       copy the text-key rules from hush_eval/textkey.py into labeler.html
    photo collect DIR      move labels-<nn>.json downloads (the labeler's Safari fallback) into their folders
"""
import argparse
import json
import sys
from pathlib import Path

from . import adapters as A
from . import photo, runner, textkey


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hush_eval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="the 20-case eval")
    r.add_argument("--live", action="store_true", help="real models; needs MODEL_API_KEY or BASETEN_API_KEY")
    r.add_argument("--ai", choices=["on", "off"], default="on",
                   help="off: no model call at all (AI_SWITCH.md): the reader's rules, the template verdict, no adjustment")
    r.add_argument("--provider", choices=["meta", "openai", "anthropic"],
                   help="a live run through this provider; meta uses the house key, the others the caller's key")
    r.add_argument("--model", help="that provider's model id (default: the service's default for it)")
    r.add_argument("--transport", default="auto", choices=["auto", "inproc", "http", "fixture"])
    r.add_argument("--cases", default=str(runner.CASES))
    r.add_argument("--only", nargs="*", help="case ids or prefixes, e.g. 04 11")
    r.add_argument("--record", action="store_true", help="live only: save real outputs into the case files")
    r.add_argument("--json", help="write the full report as JSON here")
    r.add_argument("--markdown", help="append a Markdown summary here (CI: $GITHUB_STEP_SUMMARY)")
    r.add_argument("--quiet", action="store_true")

    p = sub.add_parser("photo", help="the photo test")
    p.add_argument("action", choices=["new", "check", "run", "score", "textkey", "sync-rules", "collect"])
    p.add_argument("dir", nargs="?", help="collect: the folder the labeler downloaded into")
    p.add_argument("--root", default=str(photo.ROOT))
    p.add_argument("--link", default="")
    p.add_argument("--example", action="store_true", help="include the synthetic 00/")
    p.add_argument("--mock", action="store_true", help="run: replay model.fixture.json instead of the live reader")
    p.add_argument("--transport", default="auto", choices=["auto", "inproc", "http", "fixture"])
    p.add_argument("--force", action="store_true", help="run: overwrite model.json")
    p.add_argument("--photos-only", action="store_true", help="run: send the photos and no text")
    p.add_argument("--json", help="score, textkey: write the table as JSON here")

    a = ap.parse_args(argv)
    if a.cmd == "run":
        if a.ai == "off" and (a.live or a.provider or a.model or a.record):
            ap.error("--ai off makes no model call: it takes none of --live, --provider, --model or --record")
        live = a.live or bool(a.provider) or bool(a.model)
        if a.record and (not live or a.provider not in (None, "meta") or a.model):
            ap.error("--record needs --live on the house model: the recordings are what mock mode replays")
        mode = "off" if a.ai == "off" else "live" if live else "mock"
        ai = A.AI("off") if mode == "off" else A.AI.for_provider(a.provider, a.model) if mode == "live" else None
        res = runner.run(mode, a.transport, a.cases, a.only, a.record, ai)
        if not a.quiet:
            print(runner.text_report(res, live=mode != "mock"))
        if a.json:
            Path(a.json).write_text(runner.json_report(res))
        if a.markdown:
            with open(a.markdown, "a") as f:
                f.write(runner.markdown_report(res))
        return 0 if res["ok"] else 1

    root = Path(a.root)
    if a.action == "new":
        print(photo.new_listing(root, a.link))
        return 0
    if a.action == "check":
        lines, ready, problems = photo.check(root, a.example)
        print("\n".join(lines) or "no listing folders yet: open eval/labeler.html, or run `photo new`")
        print(f"\n{ready} ready, {problems} need work")
        return 0 if problems == 0 and ready else 1
    if a.action == "run":
        print("\n".join(photo.run(root, "mock" if a.mock else "live", a.transport, a.example, a.force, a.photos_only)))
        return 0
    if a.action == "score":
        res = photo.score(root, a.example)
        print(photo.score_report(res))
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=2))
        return 0
    if a.action == "textkey":
        res = photo.score_text_key(root, a.example)
        print(photo.text_key_report(res))
        if a.json:
            Path(a.json).write_text(json.dumps(res, indent=2))
        return 0
    if a.action == "sync-rules":
        print("labeler.html updated" if textkey.sync_labeler() else "labeler.html already has these rules")
        return 0
    if a.action == "collect":
        if not a.dir:
            ap.error("collect needs the folder the labels were downloaded into, e.g. ~/Downloads")
        print("\n".join(photo.collect(a.dir, root)))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
