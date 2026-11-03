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

`adjust` finds `packages/model` by itself when run from the monorepo. The house key is `MODEL_API_KEY`, in the
environment or in `services/adjust/.env` (gitignored). Optional: `MODEL_NAME` (default `muse-spark-1.3`),
`MODEL_BASE_URL` (default `https://api.meta.ai/v1`) and `HOUSE_AI=off`, which turns the house key off. A request
can turn AI reading off, or bring its own Meta, OpenAI or Anthropic key, with four headers: see
[The AI switch and caller keys](#the-ai-switch-and-caller-keys). In process, `read_permits(rows, as_of)` with no
client reads with keyword rules through the same checks, and the response says `"reader": "rules"`.

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

`reader` is `auto` (the model the headers pick, else no adjustment), `model` (503 when no model can run for the
request) or `rules` (the keyword rules, for tests and the eval; `X-HushIQ-AI: off` still wins). `as_of` is the date
a permit must not have expired by, default today. With `address`, the service geocodes and pulls the tax block's
permits through the frozen fetch, and a failed pull is a 502. A header outside its list is a 400.

Response (55 Bethune Street, `reader: rules`, `permits` and `readings` cut to their first entries):

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
  "ai": {"mode": "rules", "provider": null, "model": null, "key": null, "reason": null, "message": null},
  "address": {"query": "55 Bethune Street, Manhattan", "label": "55 BETHUNE STREET, New York, NY, USA", "bbl": "1006397501", "bin": "1012047", "borough": "Manhattan"}
}
```

- `permits`: what was sent, so the page can show each description with its quote marked.
- `not_read`: permits sent that have no accepted reading.
- `why_none`: when `adjustment` is null, why.
- `refusals`: every refused call, `{tool, id?, why}`, so the page can show the model being corrected.
- `trace`: one entry per tool call with the turn, what was accepted and what was refused.
- `usage`: model reader only. `{calls, prompt_tokens, completion_tokens, reasoning_tokens}` for the pull.
  Claude reports no separate reasoning count; its thinking is inside `completion_tokens`.
- `ai`: on every reply; see below. `reader` is `null` when no model ran.
- `address`: only when the request sent an address.

`router` in `adjust/api.py` is what the main API mounts; `app` serves it alone.

## The AI switch and caller keys

Hackathon work, Oct 29 (HIQ-77, epic HIQ-74). The Meta-model reading may be removed when the credits end, so it sits
behind a switch, and off still works. A caller can also bring a Claude or OpenAI key and run the same prompt and the
same checks. This is the permit reader's part of the shared AI switch contract.

Four optional headers on `POST /adjust/permits`. They are headers, never query parameters, so a key never lands in
a URL, a log line or browser history:

| Header | Values | Absent means |
|---|---|---|
| `X-HushIQ-AI` | `on`, `off` | `on` |
| `X-HushIQ-Provider` | `meta`, `openai`, `anthropic` | `meta` with the house key |
| `X-HushIQ-Key` | the caller's API key for that provider | the house key (Meta only) |
| `X-HushIQ-Model` | a model id from that provider's list | the provider's default |

- **S1 Lists.** Every value is checked in `switch.choose`, and a value outside its list is a 400 whose message
  never repeats the value. The lists and the fixed base URLs are in `config.PROVIDERS`:

  | Provider | Base URL | API | Models (default first) |
  |---|---|---|---|
  | `meta` | `https://api.meta.ai/v1` | Chat Completions, OpenAI SDK | `muse-spark-1.3` |
  | `openai` | `https://api.openai.com/v1` | Responses, OpenAI SDK | `gpt-6.1-sol`, `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6-astra` |
  | `anthropic` | `https://api.anthropic.com` | Messages, Anthropic SDK | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` |

  The defaults are a first pick, not a measured one: the eval decides and Rafa confirms.
- **S2 Off, and the house key.** `X-HushIQ-AI: off` makes no model call and no adjustment. The reply lists the
  permits with none read, `adjustment: null`, and the permit count stands. Cost zero. The house key is Meta's only
  (`MODEL_API_KEY`). `HOUSE_AI=off` on the server turns it off. With the house key off or missing and no caller key,
  an `on` request gets the same reply, with the reason. That is not an error.
- **S3 Caller keys.** A caller's key is used for that one request with the provider named. The client is built for
  the request with a 50 s timeout and no retries, and dropped after it. A key that is refused, rate-limited or
  times out gives no adjustment and says why. The server never falls back from a caller's key to the house key, so
  a stranger's failure never spends the house credits.
- **S4 One set of checks.** The same prompt, the same three tools and the same checks (P2, A1 to A4, the cap of 2)
  run for every provider. Only the wire format differs (`adjust/backends.py`):
  - **openai:** the Responses API, because function tools on OpenAI's current models need it; Chat Completions
    takes them only at reasoning effort `none`. `store` is off, and reasoning items go back encrypted.
  - **anthropic:** the Messages API, with `tool_choice: auto`. The current Claude models refuse a forced tool call
    with a 400. The prompt names the tools, and the loop nudges a reply without a tool call, as it does for Muse
    Spark. Thinking is adaptive, at effort `medium`, and its blocks go back unchanged on each turn. Opus and Sonnet
    requests carry the server-side refusal fallback (`fallbacks: "default"`); a request Claude still declines gives
    no adjustment.
- **S5 The key, on the server.**
  - The key is never logged, traced, returned or put in an error message.
  - A failed call keeps only its kind and status code (`{"error": "key_rejected", "status": 401}`). The provider's
    own error text is dropped, because a 401 can quote the key.
  - Before the reply leaves, `switch.redact` cuts the key out of every string as a last gate.
  - Tests send a fake key through success, 401, 429, a timeout and a bad model id for all three providers. They
    check that the key is not in the body, the trace or the captured logs. They also check `read_permits` before
    redaction, so a leak the last gate would hide still fails a test.

Every reply carries one `ai` object:

```json
"ai": {"mode": "model" | "basic" | "rules", "provider": "meta" | "openai" | "anthropic" | null,
       "model": "<id>" | null, "key": "house" | "caller" | null,
       "reason": null | "switched_off" | "house_off" | "no_key" | "key_rejected" | "provider_busy" | "provider_error",
       "message": "<one plain sentence for the panel>" | null}
```

- `mode` is `basic` whenever no adjustment could come from a model. `reason` says why, and `message` is the sentence
  to show, for example "AI reading is off, so the permit count stands as the city's data has it."
- `mode: rules` appears only for `reader: rules`.
- `key_rejected` is a 401 or 403. `provider_busy` is a 429, a 529 or a timeout. `provider_error` is anything else,
  including a model id the provider does not serve, and a model that sends only empty replies.
- A model that runs but leaves the count alone (`no_adjustment`, stopping, declining) is still `mode: model`, with
  `why_none` saying why.

In process, for the eval:

```python
from adjust import llm, switch
from adjust.permits import read_permits

off = switch.run(rows, as_of, switch.choose(ai="off"))                       # --ai off: no call, no cost
key = os.environ["ANTHROPIC_API_KEY"]
on = switch.run(rows, as_of, switch.choose(provider="anthropic", key=key))    # the reply with `ai`
bare = read_permits(rows, as_of, client=llm.client_for("anthropic", key))    # the reader alone, with `failure`
```

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
| `adjust/llm.py` | the house client (`client_from_env`) and a caller-key backend per request (`client_for`) |
| `adjust/backends.py` | the three wire formats: Chat Completions, Responses, Messages |
| `adjust/switch.py` | the four headers, the house key, the `ai` object, redaction |
| `adjust/api.py` | `POST /adjust/permits` |
| `adjust/pull_fixtures.py` | re-pulls the fixtures through the frozen fetch |
| `adjust/demo_v2.py` | the before and after through engine v2 |
| `tests/fixtures/` | real DOB NOW rows for three Manhattan blocks, pulled 2026-10-28, nine fields each |
| `tests/fixtures/live/` | Muse Spark's tool calls on those blocks, recorded 2026-10-28, replayed in mock mode |
| `tests/wire.py` | the three providers on a mock transport, through the real SDKs, for the switch and key tests |
