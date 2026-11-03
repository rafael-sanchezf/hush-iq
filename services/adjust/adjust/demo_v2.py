"""How engine v2 would apply a permit adjustment, without touching v2.py. (Hackathon work, Oct 28.)

    python -m adjust.demo_v2 "55 Bethune Street, Manhattan" "350 East 86th Street, Manhattan"

For each address: the frozen pulls, the per-source levels v2 ranks (baseline.neutral_levels), the permit read, then
v2.score_levels before and after adjustment.apply moves the construction levels. Prints a Markdown table of the
construction rank and the verdict, for default answers and for a renter who ticks construction. Needs
noise_score.v2 (HIQ-43) on the path; the Manhattan sample it ranks against is not adjusted.
"""
import sys

from noise_score import baseline, model, sources

from . import llm
from .adjustment import apply
from .permits import read_permits


def run(address, client=None):
    from noise_score import v2
    inputs = sources.pull_all(address)
    neutral = baseline.neutral_levels(inputs)
    facts = baseline.building_facts(inputs.get("pluto"))
    read = read_permits(inputs.get("permits"), inputs["as_of"], client=client,
                        model=llm.model_name() if client else None)
    adjusted = apply(neutral, [read["adjustment"]])
    unit = model.Unit()   # a silent listing: expected floor, side unknown
    rows = []
    for label, answers in (("default answers", v2.Answers()),
                           ("construction ticked", v2.Answers(ticks=["construction"]))):
        before = v2.score_levels(neutral, facts, unit, answers)
        after = v2.score_levels(adjusted, facts, unit, answers)
        rows.append((label, before, after))
    return inputs["address"], read, rows


def main(argv=None):
    addresses = argv if argv is not None else sys.argv[1:]
    client = llm.client_from_env()
    print(f"reader: {llm.model_name() if client else 'rules (no MODEL_API_KEY)'}\n")
    print("| Address | Adjustment | Answers | Construction rank | Verdict |")
    print("|---|---|---|---|---|")
    for address in addresses:
        a, read, rows = run(address, client)
        adj = read["adjustment"]
        n = len(adj["cites"]) if adj else 0
        said = f"{adj['direction']} {adj['size']} of {adj['cap']}, {n} permit{'s' if n != 1 else ''}" if adj else "none"
        for label, before, after in rows:
            rank = f"{before['ranks']['construction']:g} → {after['ranks']['construction']:g}"
            verdict = f"{before['verdict']} ({before['quieter_than']:g}) → {after['verdict']} ({after['quieter_than']:g})"
            print(f"| {a['label'].split(',')[0].title()} | {said} | {label} | {rank} | {verdict} |")
    print("\nRanks are \"quieter than X% of Manhattan apartments\" for construction alone; the verdict's number is the "
          "same rank for all five sources weighted.")


if __name__ == "__main__":
    main()
