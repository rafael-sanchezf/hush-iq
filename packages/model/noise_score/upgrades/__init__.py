"""Source upgrades for engine v2: each noise source keeps today's estimate and adds what actually passes, and when.
(Hackathon work, Oct 28.)

One module per source (street.py, nightlife.py, building.py, sirens.py, construction.py), each with:

    NAME = "street"
    def build(out_dir: Path) -> None
        Offline. Pulls public data and writes data/upgrades/<NAME>.json.gz (Manhattan, under 8 MB).
    def upgrade(lat: float, lng: float, today: dict, facts: dict) -> Upgrade
        At request time. Pure Python, no network: reads the built file once and caches it.
        `today` is today's level for this source per slot at a facade-neutral unit, the frozen model's math with
        the research numbers of 2026-10-29 (recal.py, ENGINE_V2.md V10) ({"night": .., "early": .., "day": ..},
        decibel-shaped, internal). `facts` is baseline.building_facts.

Today and the upgrade are two estimates of the same sound, so a module combines them as a correction or an
average inside its own source, never as an energy sum that counts the same noise twice. Levels stay
decibel-shaped and internal: only ranks and verdicts reach a renter (ENGINE_V2.md, V8). The Step list is the
math board: every input and every rule as a box, wired by `feeds`.
"""
import gzip
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SLOTS = ("night", "early", "day")
DATA = Path(__file__).resolve().parent.parent / "data" / "upgrades"


@dataclass
class Step:
    """One box on the math board."""
    id: str                  # stable and unique within the source, e.g. "street.buses_per_hour"
    label: str               # "Buses per hour"
    kind: str                # "today_input" | "new_input" | "rule" | "result"
    value: object            # a number, a string, or a per-slot dict
    unit: str                # "buses/h", "m", "count", "index" (decibel-shaped internal), "" for text
    source: str              # dataset name and id ("MTA bus timetables (GTFS)"), "today's model", or "judgment"
    formula: str = ""        # plain words: "10 x log10(buses + 1), capped at 6"
    feeds: list = field(default_factory=list)   # ids of the steps this one feeds
    status: str = "live"     # "live" (in today's model) | "new" (this upgrade) | "judgment" (a number we chose)


@dataclass
class Upgrade:
    levels: dict             # {slot: level}, combined, facade-neutral, internal
    steps: list              # [Step]
    evidence: list = field(default_factory=list)   # renter-facing sentences, counts and distances only
    upgraded: bool = True    # False when the module passed today's level through: no data, or it failed

    def as_dict(self):
        return {"levels": self.levels, "steps": [asdict(s) for s in self.steps], "evidence": self.evidence}


def load(name):
    """The built artifact for one source, or None when it has not been built."""
    p = DATA / f"{name}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt") as f:
        return json.load(f)


def save(name, doc):
    DATA.mkdir(parents=True, exist_ok=True)
    with gzip.open(DATA / f"{name}.json.gz", "wt") as f:
        json.dump(doc, f, separators=(",", ":"))


def passthrough(name, today):
    """What a module returns when its data is missing: today's level, unchanged, said so on the board."""
    return Upgrade(upgraded=False, levels=dict(today), steps=[
        Step(id=f"{name}.today", label="Today's estimate", kind="today_input", value=dict(today), unit="index",
             source="today's model", feeds=[f"{name}.level"]),
        Step(id=f"{name}.level", label="Source level", kind="result", value=dict(today), unit="index",
             source="", formula="no upgrade data built, today's estimate unchanged"),
    ])
