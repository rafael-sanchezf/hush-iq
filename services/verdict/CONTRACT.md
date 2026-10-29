# Verdict writer contract

`services/verdict`, hackathon work (Oct 28). The "what you'll hear" paragraph for one renter, written by Muse Spark
Open and checked in code against the evidence it was sent, with a template fallback. The website and the eval code
against this file; the shapes below are what the tests hold.

```
score (engine v2, or v1) + answers + fields
  -> evidence lines E1..En        one fact each, no decibels               verdict/evidence.py
  -> the model drafts             cites limited to the ids sent            verdict/writer.py
  -> the checks                   ids, numbers, names, kinds, no dB        verdict/validate.py
  -> pass: the model's sentences | fail: one retry, then the template      verdict/template.py
```

## Run it

```bash
cd services/verdict
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/uvicorn verdict.api:app --port 8030
```

With no key in `services/verdict/.env` (copy `.env.example`), every paragraph comes from the template. Set
`BASETEN_API_KEY` and the same request goes to Muse Spark Open; nothing else changes.

## POST /verdict

Request body:

```json
{
  "score":   { "...": "an engine v2 /v2/score response, or a v1 /v1/score response, as returned" },
  "answers": { "sleep_from": 23, "sleep_until": 7, "day_bothers": true, "bothers": ["sirens"] },
  "fields":  { "address": {}, "unit": {}, "floor": {}, "side": {} }
}
```

| Field | Required | Notes |
|---|---|---|
| `score` | yes | Engine v2 (`engine: "v2"`) is the main input. A v1 response (has `score` and `ingredients`) is accepted and gives fewer lines: no per-source ranks, weights or range. Anything else is a 422. |
| `answers` | no | The three taps in the v2 query names. `bothers` items are `traffic`, `people`, `neighbors`, `sirens`, `construction`; anything else is a 422. For a v2 score the answers the engine echoes win, because its numbers came from them; these fill in for a v1 score. |
| `fields` | no | The listing reader's fields (`services/agent` CONTRACT): each `{value, status: "read" \| "cant_tell", evidence: [{source: "text", quote} \| {source: "photo:<i>", what}]}`. A read floor or side brings its quote into the evidence line; a read `unit` gets its own line. `observed` and anything else is ignored. |

Query: `?writer=template` forces the template (the eval uses it to compare); the default `auto` uses the configured
model.

Response:

```json
{
  "evidence": [
    {"id": "E1", "text": "Verdict for you: Very loud, quieter than 15% of Manhattan apartments.", "kind": "verdict", "source": null},
    {"id": "E3", "text": "Street: Loud, quieter than 24% of Manhattan apartments for street noise.", "kind": "rank", "source": "street"},
    {"id": "E4", "text": "Street weight: 47% of the verdict, counted three times because you said traffic bothers you.", "kind": "weight", "source": "street"}
  ],
  "sentences": [
    {"text": "For the way you sleep, this apartment is very loud: quieter than 15% of Manhattan apartments.", "cites": ["E1", "E25"]},
    {"text": "You said traffic bothers you, so street noise counts for 47% of the verdict; here it is loud, quieter than 24% of Manhattan apartments.", "cites": ["E4", "E3"]}
  ],
  "writer": "template",
  "trace": [{"writer": "template", "ok": true, "why": "no model configured"}]
}
```

(Abridged from the real response for 1 E 101st St, floor 2 facing the street; the full one has 31 lines and six
sentences.)

| Field | Shape |
|---|---|
| `evidence` | Every line sent to the writer, in order, ids `E1..En` with no gaps. `kind` and `source` let the page group them. |
| `sentences` | 1 to 6 sentences. Every `cites` is non-empty and every id is in `evidence`. Render each sentence with its cites as chips that open the line. |
| `writer` | `"muse-spark-open"` (Baseten), `"muse-spark-1.3"` (Meta Model API, the second backend) or `"template"`. |
| `trace` | What each attempt drew, so a fallback is never silent: `{writer, attempt, ok, errors: [...], ms}` per model call, then `{writer: "template", ok: true, why}` if the template wrote. The website can show "the checks refused the first draft: it cited E41". |

Errors: 422 for a body that is not a score this service can read, or answers outside the shape above. A model that
fails, times out or errors never fails the request: the template answers.

### Evidence kinds

| `kind` | `source` | What the line says |
|---|---|---|
| `verdict` | | the verdict for this renter and its rank, always `E1` when the score has one |
| `cap` | the source | a cap (V6) and the source that set it, and whether it held the verdict down |
| `rank` | the source | that source's rank: "quieter than X% of Manhattan apartments for street noise" (v2 only) |
| `weight` | the source | the share of the verdict the source got and why: the default from the health department surveys, or tripled because the renter ticked it |
| `detail` | the source | one record behind the source: a road and its distance, a bar's address, a hospital, 311 counts, a permit |
| `temporary` | `construction` | construction is temporary |
| `bothers`, `hours`, `daytime`, `time_split` | | the renter's answers and the time-of-day split they produced |
| `floor`, `side`, `unit` | | the floor and side the score used, read from the listing (with its quote) or expected |
| `commercial` | | commercial ground floor, so apartments start on floor 2 |
| `range` | | for a silent listing, the loudest and the quietest case (V7), one line each |
| `method`, `address` | | the Manhattan sample behind every rank; the address scored |

Every number in a line is a rank, a weight, a floor, a count, a distance in metres, an hour or a date. No line holds
a decibel; a listing quote that has one loses it (`[sound level removed]`).

## The checks

In `verdict/validate.py`, on every model reply, before anything reaches a renter. A reply that fails gets one retry
with the errors listed; a second failure gets the template. The template passes the same checks (the tests run it
on every fixture).

| | Rule |
|---|---|
| C1 | every sentence cites at least one id, and every id it cites was sent |
| C2 | every number in a sentence is in a line it cites: digits, "1,670", number words and "fourth floor" all count |
| C3 | no decibel unit anywhere (`dB`, `dBA`, `decibel`) |
| C4 | every name in a sentence (a street, a building, a hospital, a borough) is in a line it cites; "Ludlow Street" matches "Ludlow St" |
| C5 | every kind of source a sentence mentions (subway, highway, bar, hospital, police, construction, school, park...) is in a line it cites |
| C6 | no evidence id in the text, at most 6 sentences, each under 320 characters |

Names and numbers are checked against the sentence's own cited lines, not the whole evidence: a citation has to back
the sentence it sits on. The one exception is the baseline itself ("Manhattan", "NYC"), which may appear in any
sentence once a line says it.

## Backends

| `writer` | Model | Host | Key | How the shape is held |
|---|---|---|---|---|
| `muse-spark-open` | `meta-models/muse-spark-open-1026` | `https://inference.baseten.co/v1` | `BASETEN_API_KEY` | one forced tool call, `submit_verdict`, whose parameters are the schema. Baseten's docs say this model accepts a `json_schema` response format but does not enforce it, so the tool call is used instead. |
| `muse-spark-1.3` | `muse-spark-1.3` | `https://api.meta.ai/v1` | `MODEL_API_KEY` | `response_format: {type: "json_schema", json_schema: {strict: true}}`, `reasoning_effort: "low"`, `max_completion_tokens` |

Both go through the OpenAI Python SDK, and in both `cites` is an enum of the ids sent. `VERDICT_BACKEND` picks
(`auto`, `muse-spark-open`, `muse-spark-1.3`, `template`); `auto` takes Baseten when its key is set, then Meta, then
the template. `VERDICT_TIMEOUT_S` (default 25) is per call; a timeout or an API error goes straight to the template.

Reasoning tokens count against the token ceiling (`VERDICT_MAX_TOKENS`, default 6000): live, Muse Spark 1.3 at effort
low spent 1,300 to 3,500 of them per draft. A spent budget comes back as empty content with `finish_reason:
"length"` and no error; the writer treats it as a refused draft and retries once with twice the room.

Measured live on Oct 28 (Muse Spark 1.3, the three example addresses, 17 drafts): one call takes 6 to 13 s, median
8 s, so a paragraph that needs its retry takes about 20 s. One draft in 17 was refused (a sentence over the length
limit) and its retry passed.

The checks prove each fact a sentence states is in a line it cites. They do not prove the links between facts: a
live draft said "you sleep from 1 am to 9 am, when sirens stay very loud", and both halves are cited, but no line ties
sirens to those hours.

## GET /health

`{"ok": true, "version": "0.1.0", "writer": "template", "model": null}`: which writer this process would use.

## Defaults taken

Small calls made while building, for Rafa to override:

1. Liquor licensee names are dropped from the evidence. The license's legal name is rarely the bar's name, and some
   are people; the line keeps the kind and the address ("a bar at 152 Ludlow Street, 15 m away").
2. `writer` has a third value, `"muse-spark-1.3"`, for the second backend.
3. Each evidence line carries `kind` and `source` beside `id` and `text`, and the response carries `trace`.
4. The paragraph is capped at six sentences; the prompt asks for three to five.
