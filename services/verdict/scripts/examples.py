"""Three real addresses through the verdict writer: the template, a scripted model, and the live model when a key is set.

    .venv/bin/python scripts/examples.py > examples.md

Scores are the engine v2 fixtures in tests/fixtures (real pulls for real Manhattan addresses). The listing fields
and the scripted model drafts are written by hand; the second and third drafts break a rule on purpose, so the
output shows the checks refusing them and the retry.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from verdict import evidence, mock, writer  # noqa: E402


def s(text, *cites):
    return {"text": text, "cites": list(cites)}


EXAMPLES = [
    {
        "title": "140 Claremont Ave, floor 4 at the rear, both read from the listing; sirens bother this renter",
        "score": "v2_claremont_floor4_rear.json",
        "fields": {"floor": {"value": 4, "status": "read", "evidence": [{"source": "text", "quote": "4th floor, elevator building"}]},
                   "side": {"value": "rear", "status": "read", "evidence": [{"source": "photo:2", "what": "bedroom window onto a courtyard"}]}},
        "drafts": [{"sentences": [
            s("For the way you sleep, from 11 pm to 7 am, this apartment is very quiet: quieter than 99% of Manhattan "
              "apartments.", "E1", "E29"),
            s("Sirens, which you said bother you, count for 43% of the verdict and rank very quiet here; the nearest "
              "source is the NYPD 26th Precinct, a police station 417 m away.", "E2", "E3", "E5"),
            s("The loudest thing you are likely to hear is your neighbors, and even they are quiet: 4 residential noise "
              "complaints reached 311 from this building in 24 months, across 61 apartments.", "E12", "E14"),
            s("This is for floor 4 at the rear, from the listing and a photo of the bedroom window.", "E32", "E33"),
        ]}],
    },
    {
        "title": "151 Ludlow St, a silent listing (no floor, no side); asleep 1 am to 9 am, people and nightlife bother this renter",
        "score": "v2_ludlow_silent.json",
        "fields": {"floor": {"value": None, "status": "cant_tell", "evidence": []},
                   "side": {"value": None, "status": "cant_tell", "evidence": []}},
        "drafts": [
            {"sentences": [
                s("For a renter asleep from 1 am to 9 am, this apartment is very loud: quieter than 5% of Manhattan "
                  "apartments.", "E1", "E29"),
                s("Bar crowds spilling over from Broadway push nights past 70 dB.", "E5"),
                s("The listing gives no floor or side, so this assumes floor 4.", "E32", "E33"),
            ]},
            {"sentences": [
                s("For a renter asleep from 1 am to 9 am, this apartment is very loud: quieter than 5% of Manhattan "
                  "apartments.", "E1", "E29"),
                s("Nightlife is the reason, and you said it bothers you: there are 86 licensed venues within 150 m, the "
                  "nearest a bar at 152 Ludlow Street, 15 m away.", "E3", "E4", "E5", "E6"),
                s("311 logged 1,670 party, music or loud-talking complaints within 150 m in 24 months, 916 of them "
                  "between 10 pm and 5 am.", "E8"),
                s("The listing gives no floor or side, so this assumes floor 4; depending on the unit it runs from very "
                  "loud on floor 2 facing the street to loud on floor 5 at the rear.", "E32", "E33", "E35", "E36"),
            ]},
        ],
    },
    {
        "title": "1 E 101st St, floor 2 facing Fifth Avenue, read from the listing; sirens and traffic bother this renter",
        "score": "v2_east101_floor2_front.json",
        "fields": {"floor": {"value": 2, "status": "read", "evidence": [{"source": "text", "quote": "second floor, facing Fifth Avenue"}]},
                   "side": {"value": "front", "status": "read", "evidence": [{"source": "text", "quote": "facing Fifth Avenue"}]}},
        "drafts": [
            {"sentences": [
                s("For the way you sleep, this apartment is very loud: quieter than 15% of Manhattan apartments.", "E1", "E25"),
                s("Sirens are the main problem: Mount Sinai Hospital is 87 m away, and its ambulances pass all night.",
                  "E10", "E40"),
            ]},
            {"sentences": [
                s("For the way you sleep, this apartment is very loud: quieter than 15% of Manhattan apartments.", "E1", "E25"),
                s("Sirens, which you said bother you, are among the loudest in Manhattan here, and Mount Sinai Hospital "
                  "is 87 m away.", "E7", "E8", "E10"),
                s("Traffic counts for 47% of the verdict and ranks loud: 5 Ave and E 101 St are both 25 m away, and both "
                  "are bus or truck routes.", "E3", "E4", "E5", "E6"),
                s("This is for floor 2 facing Fifth Avenue, as the listing says.", "E28", "E29"),
            ]},
        ],
    },
]


def paragraph(out):
    return " ".join(f"{x['text']} [{', '.join(x['cites'])}]" for x in out["sentences"])


def main():
    live = writer.from_env()
    print(f"Live model: {live.name + ' (' + live.model + ')' if live else 'none (no key in services/verdict/.env)'}\n")
    for ex in EXAMPLES:
        score = json.loads((ROOT / "tests" / "fixtures" / ex["score"]).read_text())
        lines = evidence.build(score, None, ex["fields"])
        print(f"### {ex['title']}\n")
        print(f"Verdict from engine v2: **{score['verdict']}**, quieter than {score['quieter_than']}% of Manhattan "
              f"apartments; {len(lines)} evidence lines.\n")
        print("<details><summary>Evidence sent</summary>\n\n" + "\n".join(f"- {l.id}: {l.text}" for l in lines)
              + "\n\n</details>\n")
        print(f"**Template** (no key; also the fallback):\n\n> {paragraph(writer.write(lines, None))}\n")
        out = writer.write(lines, mock.backend(*ex["drafts"]))
        rejected = [t for t in out["trace"] if t.get("attempt") and not t["ok"]]
        print(f"**Mock model** (scripted drafts through the checks, writer: `{out['writer']}`):\n")
        for t in rejected:
            print(f"- draft {t['attempt']} refused: " + "; ".join(t["errors"]))
        print(f"\n> {paragraph(out)}\n")
        if live:
            out = writer.write(lines, live)
            print(f"**Live, {live.name}** (writer: `{out['writer']}`):\n")
            for t in out["trace"]:
                if t.get("attempt"):
                    u = t.get("usage") or {}
                    tokens = (f", {u['completion_tokens']} completion tokens, {u.get('reasoning_tokens', '?')} of them "
                              f"reasoning" if "completion_tokens" in u else "")
                    print(f"- attempt {t['attempt']}: {'passed' if t['ok'] else 'refused: ' + '; '.join(t['errors'])} "
                          f"({t['ms'] / 1000:.1f} s{tokens})")
            print(f"\n> {paragraph(out)}\n")


if __name__ == "__main__":
    main()
