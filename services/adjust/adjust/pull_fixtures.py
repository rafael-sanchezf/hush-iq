"""Pull the permit rows behind the tests, once, through the frozen model's own fetch. (Hackathon work, Oct 28.)

    python -m adjust.pull_fixtures "55 Bethune Street, Manhattan" "350 East 86th Street, Manhattan"

Writes tests/fixtures/permits_<slug>.json: the rows the reader would send (unexpired loud-work or scaffold permits on
the tax block), scrubbed to the allowed fields. The repo is public, so a row with any other field fails the write.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

from noise_score import sources

from . import config as A
from .permits import block_permits, permits_to_read

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def pull(address, today=None):
    today = today or dt.date.today()
    a, rows = block_permits(address, today)
    sent = permits_to_read(rows, today.isoformat())
    for r in sent:
        extra = set(r) - set(A.PERMIT_FIELDS)
        if extra:
            raise SystemExit(f"refusing to write {sorted(extra)}: not an allowed permit field")
    return {"address": {"query": address, "label": a.get("label"), "bbl": a.get("bbl"), "borough": a.get("borough")},
            "as_of": today.isoformat(), "source": sources.DATASETS["permits"],
            "rows_on_block": len(rows), "permits": sent}


def slug(address):
    return re.sub(r"[^a-z0-9]+", "_", address.split(",")[0].lower()).strip("_")


def main(argv=None):
    addresses = (argv if argv is not None else sys.argv[1:])
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for address in addresses:
        doc = pull(address)
        path = FIXTURES / f"permits_{slug(address)}.json"
        path.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"{path.name}: {len(doc['permits'])} of {doc['rows_on_block']} rows on the block")


if __name__ == "__main__":
    main()
