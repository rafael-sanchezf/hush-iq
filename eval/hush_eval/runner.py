"""The 20-case run: read each listing, check the reader's grounding and its fields against gold, write the
verdict and check its citations, read the permit pull and check the adjustments. Mock mode by default."""
import json
import os
from pathlib import Path

from . import adapters as A
from . import checks as C
from . import shapes as S

EVAL = Path(__file__).resolve().parents[1]
CASES = EVAL / "cases"
GATED_FIELDS = ("address", "floor", "side")   # the gold labels every case carries
MIN_ACCURACY, MAX_WRONG = 0.85, 0.05          # the same rule as the photo test, README "The threshold rule"
# Mock mode replays recorded model output through the services' own checks, which may only accept or refuse it.
# So in mock mode a refusal (cant_tell) is allowed and a wrong or invented value is not; live mode, where a real
# model answers, gets the full rule.


def load_cases(cases_dir=CASES, only=None):
    cases = []
    for p in sorted(Path(cases_dir).glob("*.json")):
        case = json.loads(p.read_text())
        case["_path"] = str(p)
        if only and not any(case["id"].startswith(o) or p.stem.startswith(o) for o in only):
            continue
        cases.append(case)
    return cases


def run_case(case, services, cases_dir=CASES):
    """One case through the three services. Returns a record with problems, outcomes and meta."""
    rec = {"id": case["id"], "problems": [], "extraction": {}, "meta": {}, "outputs": {}}
    listing = case["listing"]

    def fail(where, e):
        rec["problems"].append(C.Problem("service", where, f"{type(e).__name__}: {e}"))

    # 1. the listing reader
    reader = None
    try:
        reader, meta = services["reader"].call(case, **A.reader_inputs(case, cases_dir))
        rec["meta"]["reader"] = meta
        rec["outputs"]["reader"] = reader
        _notes(rec, "reader", reader)
    except Exception as e:   # a service that crashes is a failed case, not a crashed run
        fail("reader", e)
    if reader is not None:
        rec["problems"] += C.reader_grounding(reader, listing)
        rec["extraction"] = C.extraction(reader, case["gold"])

    # 2. the verdict writer, on the score the reader produced (or the recorded one)
    score = (reader or {}).get("score") or (case.get("fixtures") or {}).get("score")
    fields = (reader or {}).get("fields") or {}
    if score is None:
        rec["problems"].append(C.Problem("verdict_citations", "verdict",
                                         "no score: the reader could not place the listing, so there is no verdict", hard=False))
    else:
        try:
            verdict, meta = services["verdict"].call(case, score=score, answers=case["answers"], fields=fields)
            rec["meta"]["verdict"] = meta
            rec["outputs"]["verdict"] = verdict
            rec["problems"] += C.verdict_citations(verdict, score)
        except Exception as e:
            fail("verdict", e)

    # 3. the permit reader, when the case carries a permit pull
    pull = case.get("pull") or {}
    rows = pull.get("permits") or []
    if rows:
        try:
            adj, meta = services["adjust"].call(case, rows=rows, as_of=pull.get("as_of"))
            rec["meta"]["adjust"] = meta
            rec["outputs"]["adjust"] = adj
            _notes(rec, "adjust", adj)
            caps, caps_from = services["adjust"].caps()
            rec["meta"]["caps_from"] = caps_from
            rec["problems"] += C.adjustments(adj, rows, caps)
        except Exception as e:
            fail("adjust", e)
    return rec


def _notes(rec, service, out):
    for where, why in A.refusals(out):
        rec["problems"].append(C.Problem("refused", f"{service} {where}", why, hard=False))


def run(mode="mock", transport="auto", cases_dir=CASES, only=None, record=False):
    if mode == "live" and not (os.environ.get("MODEL_API_KEY") or os.environ.get("BASETEN_API_KEY")):
        raise SystemExit("live mode needs MODEL_API_KEY or BASETEN_API_KEY in the environment")
    services = {n: A.Service(n, mode, transport) for n in ("reader", "verdict", "adjust")}
    cases = load_cases(cases_dir, only)
    records = [run_case(c, services, cases_dir) for c in cases]
    if record:
        _record(cases, records)
    table = C.tally([r["extraction"] for r in records], _fields_seen(records))
    prices = A.load_prices()
    for r in records:
        usage = {}
        for m in r["meta"].values():
            if isinstance(m, dict):
                for model, u in (m.get("usage") or {}).items():
                    d = usage.setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0})
                    d["prompt_tokens"] += u["prompt_tokens"]
                    d["completion_tokens"] += u["completion_tokens"]
        r["usage"] = usage
        r["cost_usd"] = A.cost_of(usage, prices) if usage else None
        r["latency_s"] = round(sum(m.get("latency_s", 0) for m in r["meta"].values() if isinstance(m, dict)), 3)
    gate = _gate(table, mode)
    hard = [p for r in records for p in r["problems"] if p.hard]
    return {
        "mode": mode,
        "transports": {n: s.why for n, s in services.items()},
        "cases": len(records),
        "records": records,
        "accuracy": table,
        "gate": gate,
        "ok": not hard and all(g["ok"] for g in gate.values()),
    }


def _fields_seen(records):
    seen = []
    for name in S.TEXT_FIELDS + S.OBSERVED_FIELDS:
        if any(name in r["extraction"] for r in records):
            seen.append(name)
    return seen


def _gate(table, mode="mock"):
    out = {}
    for name in GATED_FIELDS:
        row = table.get(name)
        if not row or not row["n"]:
            continue
        acc, wrong = row["accuracy"], row["wrong_rate"]
        ok = wrong == 0 if mode == "mock" else (acc is None or acc >= MIN_ACCURACY) and wrong < MAX_WRONG
        out[name] = {"ok": ok, "accuracy": acc, "wrong_rate": wrong}
    return out


def _record(cases, records):
    """Live mode only: write each service's real output into its case, so mock mode replays it from now on."""
    for case, rec in zip(cases, records):
        changed = False
        for name, out in rec["outputs"].items():
            if out is not None and rec["meta"].get(name, {}).get("transport") != "fixture":
                case.setdefault("fixtures", {})[name] = out
                changed = True
        if changed:
            path = Path(case.pop("_path"))
            path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- reports
def _pct(x):
    return "  n/a" if x is None else f"{100 * x:4.0f}%"


def text_report(res, live=False):
    lines = [f"Hush IQ eval, {res['mode']} mode, {res['cases']} cases"]
    for n, why in res["transports"].items():
        lines.append(f"  {n:8} {why}")
    lines.append("")
    lines.append(f"{'case':34} {'checks':8} " + " ".join(f"{f[:8]:>8}" for f in GATED_FIELDS)
                 + ("   latency     cost" if live else ""))
    for r in res["records"]:
        hard = [p for p in r["problems"] if p.hard]
        cells = " ".join(f"{r['extraction'].get(f, {}).get('outcome', '-'):>8}" for f in GATED_FIELDS)
        tail = ""
        if live:
            cost = "n/a" if r["cost_usd"] is None else f"${r['cost_usd']:.4f}"
            tokens = sum(u["prompt_tokens"] + u["completion_tokens"] for u in r["usage"].values())
            tail = f"  {r['latency_s']:6.1f} s  {cost:>8}  {tokens} tok"
        lines.append(f"{r['id'][:34]:34} {'ok' if not hard else f'{len(hard)} FAIL':8} {cells}{tail}")
    lines.append("")
    lines.append(f"{'field':14} {'n':>3} {'correct':>8} {'wrong':>6} {'cant_tell':>9} {'invented':>8} {'accuracy':>9} {'wrong %':>8}")
    for name, row in res["accuracy"].items():
        lines.append(f"{name:14} {row['n']:3d} {row['correct']:8d} {row['wrong']:6d} {row['cant_tell']:9d} {row['invented']:8d}"
                     f" {_pct(row['accuracy']):>9} {_pct(row['wrong_rate']):>8}")
    lines.append("")
    problems = [(r["id"], p) for r in res["records"] for p in r["problems"]]
    for cid, p in problems:
        lines.append(f"{'FAIL' if p.hard else 'note'} {cid}: {p.check} {p.where}: {p.message}")
    for name, g in res["gate"].items():
        if not g["ok"]:
            need = "no wrong values in mock mode" if res["mode"] == "mock" else f"{MIN_ACCURACY:.0%} and under {MAX_WRONG:.0%} wrong"
            lines.append(f"FAIL gate {name}: accuracy {_pct(g['accuracy'])}, wrong {_pct(g['wrong_rate'])} (needs {need})")
    if live:
        costs = [r["cost_usd"] for r in res["records"]]
        lat = [r["latency_s"] for r in res["records"]]
        total = "n/a (fill eval/prices.json)" if any(c is None for c in costs) else f"${sum(costs):.4f}"
        lines.append(f"total cost {total}, mean latency {sum(lat) / max(len(lat), 1):.1f} s per case")
    lines.append("PASS" if res["ok"] else "FAIL")
    return "\n".join(lines)


def markdown_report(res):
    hard = sum(1 for r in res["records"] for p in r["problems"] if p.hard)
    soft = sum(1 for r in res["records"] for p in r["problems"] if not p.hard)
    out = [f"### Hush IQ eval: {'PASS' if res['ok'] else 'FAIL'} ({res['mode']} mode, {res['cases']} cases)", ""]
    out.append(f"{hard} hard problems, {soft} notes.")
    out.append("")
    out += ["| service | reached |", "|---|---|"] + [f"| {n} | {w} |" for n, w in res["transports"].items()]
    out += ["", "| field | n | correct | wrong | can't tell | invented | accuracy | wrong % |", "|---|---|---|---|---|---|---|---|"]
    for name, row in res["accuracy"].items():
        out.append(f"| {name} | {row['n']} | {row['correct']} | {row['wrong']} | {row['cant_tell']} | {row['invented']}"
                   f" | {_pct(row['accuracy']).strip()} | {_pct(row['wrong_rate']).strip()} |")
    problems = [(r["id"], p) for r in res["records"] for p in r["problems"]]
    if problems:
        out += ["", "| case | kind | check | where | problem |", "|---|---|---|---|---|"]
        for cid, p in problems:
            out.append(f"| {cid} | {'fail' if p.hard else 'note'} | {p.check} | {p.where} | {p.message.replace('|', '/')} |")
    return "\n".join(out) + "\n"


def json_report(res):
    def conv(o):
        if isinstance(o, C.Problem):
            return o.as_dict()
        raise TypeError(type(o))
    slim = dict(res, records=[{k: v for k, v in r.items() if k != "outputs"} for r in res["records"]])
    return json.dumps(slim, indent=2, default=conv)
