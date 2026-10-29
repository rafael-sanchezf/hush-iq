# services/adjust: bounded adjustments

Hackathon work, Oct 28 (cards HIQ-16 and HIQ-18, epic HIQ-3). The frozen model counts what the city's data
can count. This service lets a Meta model read what the count cannot, and lets code decide how far that
reading may move the score. Built now: the construction source, from DOB NOW permit descriptions. The
adjustment object and its refusals are generic, so the 311-text and venue-hours adjustments reuse them.

Nothing here changes `packages/model`. The permit rows come from the frozen `sources.dob_permits`, and the
engine is not wired yet; [How the engine applies it](#how-the-engine-applies-it) shows the call.

## Run it

```bash
cd services/adjust
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # mock mode: no network, no key
.venv/bin/uvicorn adjust.api:app --port 8030       # POST /adjust/permits
```

`adjust` finds `packages/model` by itself when run from the monorepo. Live mode turns on when
`MODEL_API_KEY` is in the environment or in `services/adjust/.env` (gitignored). Optional: `MODEL_NAME`
(default `muse-spark-1.3`) and `MODEL_BASE_URL` (default `https://api.meta.ai/v1`). With no key, the
reader uses keyword rules through the same checks, and the response says `"reader": "rules"`.

## The adjustment object

```json
{"source": "construction", "direction": "louder", "size": 1, "cap": 2,
 "cites": ["M01113570-I1-GC"], "reason": "Heavier or longer work than the permit count shows: a facade job (months) on this tax block."}
```

| Field | What it is |
|---|---|
| `source` | one of the engine's five: `street`, `nightlife`, `building`, `sirens`, `construction` |
| `direction` | `louder` or `quieter` |
| `size` | whole steps, at least 1. Never decibels: the step's size lives in the engine's config |
| `cap` | the most steps this source takes, from `adjust/config.py`; a caller cannot set it |
| `cites` | the ids of the rows the adjustment rests on, all from the rows sent to the model |
| `reason` | one sentence a renter can read, at most 300 characters |

An adjustment is `null` when nothing moves.

Rules, all in code (`adjust/adjustment.py`), every number in `adjust/config.py`:

- **A1 Shape.** The six fields above. `submit_adjustment` returns the normalised object or raises `Refused`
  with the reason, which goes back to the model as the tool result.
- **A2 Caps.** One `CAPS` table. A source with no cap takes no adjustment: today only `construction: 2`.
  A size over the cap is refused ("size 3 exceeds the construction cap of 2").
- **A3 Citations.** Every cited id must be among the rows sent ("cites X, which is not among the rows sent")
  and, when the caller passes the accepted readings, must have one ("cites X, which has no accepted reading").
- **A4 Evidence bound.** The caller may pass `bound(direction, cites)`: the most steps the cited rows support.
  A size over it is refused, and a direction none of them supports is refused.
- **A5 Apply.** `apply(neutral, adjustments)` moves one source's per-window levels by `size × STEP_LEVEL`
  and returns a copy for the engine to rank. A quieter adjustment never takes a source below an empty
  block's level, and `apply` checks the cap again so a hand-built object cannot skip it. One construction
  step is 2 level units: on engine v2's construction ranks, between the 20th and 80th percentile of
  Manhattan, a step moves the rank about 10 points and the cap about 20.

## The permit reader

`read_permits(rows, as_of, client=None, model=None)` in `adjust/permits.py`. `rows` are permit rows as
`sources.dob_permits` returns them (the `permits` list of `/v1/raw`). `client` is an OpenAI-SDK client
for the Meta Model API, or a scripted stand-in in tests; `None` reads with the rules.

- **P1 What is sent.** Unexpired permits whose work type the frozen construction ingredient counts as loud,
  plus supported and suspended scaffolds (which it skips but which usually mean facade work). One row per
  permit id: a renewal repeats the id and the latest expiry wins. The costliest 20. Each row is cut to nine
  fields (`work_permit`, `work_type`, `job_description`, `house_no`, `street_name`, `bin`, `issued_date`,
  `expired_date`, `estimated_job_costs`), and any email or phone number in the description is removed.
  Owner, applicant and filing-representative fields never reach the model, the response or a fixture.
- **P2 One reading.** Per permit: `kind` (`facade`, `interior_renovation`, `new_building`, `demolition`,
  `scaffold_shed`, `other`, or `cant_tell`) and `duration` (`weeks` under 3 months, `months` 3 to 12, `years`
  over 12, or `cant_tell`), each with the quoted words of that permit's own job description. A quote not in
  that description is refused, including a real quote from a different permit. Case and runs of spaces are
  forgiven; nothing else. A quote under 4 characters is refused. `cant_tell` needs no quote.
- **P3 Pressure.** Each reading supports a signed number of steps by kind and duration (`PRESSURE` in
  config): a new building or a demolition up to 2 louder, facade work running months 1 louder, interior work
  1 quieter, a scaffold or shed alone 0, because the count already has them. A louder adjustment may not
  exceed the largest pressure among its citations. A quieter one also needs half the permits sent to read
  quieter and none to read louder.
- **P4 Rules reader.** With no key: keyword patterns give the kind and its quote, the duration follows from
  the kind, and the adjustment follows from the pressure table. The rules pass through the same checks.
- **P5 Model reader.** Muse Spark gets the permits and three tools: `read_permits` (a list of readings, each
  accepted or refused on its own), `submit_adjustment`, and `no_adjustment`. Each call is checked by P2 and
  A1 to A4, a refusal goes back as the tool result, and the model corrects it, for at most 8 turns. A model
  that stops, runs out of turns, or returns an API error gives no adjustment, so the frozen count stands.
  Reasoning tokens count against `max_tokens`, and a reply cut short comes back empty with no error, so each
  call gets 6,000 and an empty reply is sent again, at most twice per pull.

Live, 2026-10-28, `muse-spark-1.3` on the three fixtures: 8 calls, 2 to 4 per block, 14 to 44 seconds each,
about 90% of completion tokens spent on reasoning. All 22 readings were accepted on the first try. One
adjustment was refused (2 steps quieter where the cited permits support 1) and corrected on the next turn.
The recorded tool calls are in `tests/fixtures/live/`, and a test replays them through the checks.

Readings use the same field shape as the listing reader (`services/agent`):
`{value, status: "read" | "cant_tell", evidence: [{source: "permit:<id>", quote}]}`.

## POST /adjust/permits

Request, one of `address` or `permits`:

```json
{"address": "55 Bethune Street, Manhattan"}
{"permits": [ ...rows from /v1/raw... ], "as_of": "2026-10-28", "reader": "auto"}
```

`reader` is `auto` (the model when a key is set, else the rules), `model` (503 with no key) or `rules`.
`as_of` is the date a permit must not have expired by, default today. With `address`, the service geocodes
and pulls the tax block's permits through the frozen fetch, and a failed pull is a 502.

Response (55 Bethune Street, rules reader, `permits` and `readings` cut to their first entries):

```json
{
  "source": "construction",
  "as_of": "2026-10-28",
  "reader": "rules",
  "permits": [
    {"id": "M01113570-I1-GC", "work_type": "General Construction",
     "job_description": "EXTERIOR MASONRY RESTORATION, ROOF REPLACEMENTS, INSTALLATION OF NEW GREEN ROOFING, ...",
     "address": "155 Bank Street", "issued_date": "2026-03-02", "expired_date": "2027-02-28",
     "estimated_job_costs": "20390875"}
  ],
  "readings": [
    {"id": "M01113570-I1-GC", "address": "155 Bank Street", "work_type": "General Construction",
     "kind": {"value": "facade", "status": "read",
              "evidence": [{"source": "permit:M01113570-I1-GC", "quote": "EXTERIOR MASONRY RESTORATION"}]},
     "duration": {"value": "months", "status": "read",
                  "evidence": [{"source": "permit:M01113570-I1-GC", "quote": "EXTERIOR MASONRY RESTORATION"}]}}
  ],
  "not_read": [],
  "adjustment": {"source": "construction", "direction": "louder", "size": 1, "cap": 2,
                 "cites": ["M01113570-I1-GC"],
                 "reason": "Heavier or longer work than the permit count shows: a facade job (months) on this tax block."},
  "why_none": null,
  "refusals": [],
  "trace": [{"turn": 0, "tool": "rules", "accepted": ["M01113570-I1-GC", "M01265075-I1-PMM", "M01255421-S1-SH", "M01181311-I1-SC"]}],
  "address": {"query": "55 Bethune Street, Manhattan", "label": "55 BETHUNE STREET, New York, NY, USA", "bbl": "1006397501", "bin": "1012047", "borough": "Manhattan"}
}
```

- `permits`: what was sent, so the page can show each description with its quote marked.
- `not_read`: permits sent that have no accepted reading.
- `why_none`: when `adjustment` is null, why.
- `refusals`: every refused call, `{tool, id?, why}`, so the page can show the model being corrected.
- `trace`: one entry per tool call with the turn, what was accepted and what was refused.
- `usage`: model reader only. `{calls, prompt_tokens, completion_tokens, reasoning_tokens}` for the pull.
- `address`: only when the request sent an address.

`router` in `adjust/api.py` is what the main API mounts; `app` serves it alone.

## How the engine applies it

The adjustment moves the construction levels; engine v2 ranks them as usual. No change to `v2.py`:

```python
from noise_score import baseline, sources, v2
from adjust.adjustment import apply
from adjust.permits import read_permits

inputs = sources.pull_all(address)
neutral = baseline.neutral_levels(inputs)                # per source, per window, before floor and side
facts = baseline.building_facts(inputs["pluto"])
read = read_permits(inputs["permits"], inputs["as_of"], client)
before = v2.score_levels(neutral, facts, unit, answers)
after = v2.score_levels(apply(neutral, [read["adjustment"]]), facts, unit, answers)
```

`python -m adjust.demo_v2 "<address>" ...` prints the construction rank and the verdict before and after.
The Manhattan sample it ranks against is not adjusted: the reader has not read the 300 sample buildings'
permits, so an adjusted apartment is compared with unadjusted neighbours. Reading the sample once and
storing its adjustments is the next step if the shift turns out systematic.

## Reusing it for 311 text and venue hours

A new source needs three things: a cap in `CAPS` and a step in `STEP_LEVEL` (and `LEVEL_FLOOR` if a quieter
move needs a floor), a reader that sends rows with ids and checks its own quotes, and a `bound` for its
evidence. `submit_adjustment` and `apply` stay as they are.

## Files

| File | What |
|---|---|
| `adjust/config.py` | every cap and table |
| `adjust/adjustment.py` | the object, `submit_adjustment`, `apply` |
| `adjust/permits.py` | the pull, P1 to P5, the prompt and tools |
| `adjust/llm.py` | the Meta Model API client, when a key is set |
| `adjust/api.py` | `POST /adjust/permits` |
| `adjust/pull_fixtures.py` | re-pulls the fixtures through the frozen fetch |
| `adjust/demo_v2.py` | the before and after through engine v2 |
| `tests/fixtures/` | real DOB NOW rows for three Manhattan blocks, pulled 2026-10-28, nine fields each |
| `tests/fixtures/live/` | Muse Spark's tool calls on those blocks, recorded 2026-10-28, replayed in mock mode |
