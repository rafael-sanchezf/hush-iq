# Listing reader contract: `POST /read`

What the website and the eval code against. Changes to this shape are additive only: new keys may appear,
existing keys keep their name, type and meaning. Hackathon work, Oct 28.

## Run it

```bash
cd services/agent
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn reader.app:app --port 8100
```

`GET /` says the mode. **mock**: no `MODEL_API_KEY`, an offline stand-in made of regular expressions answers
instead of the model; it cannot see photos (every photo reads as cant_tell). **live**: `MODEL_API_KEY` is set
in `services/agent/.env`, Muse Spark (`muse-spark-1.3`) answers through the Meta Model API. Every result
carries `mode`, so a mock result is never shown as the model's.

## Request

`POST /read`, either encoding:

| Encoding | `text` | `photos` | `answers` |
|---|---|---|---|
| `application/json` | string | array of data URLs, `"data:image/jpeg;base64,..."` | object |
| `multipart/form-data` | form field | file parts named `photos` (or `photos[]`), repeated | form field holding JSON |

- `text`: the listing as pasted, up to 20,000 characters. May be empty when photos are sent.
- `photos`: up to 12, each up to 8 MB, JPEG, PNG, WebP or GIF (checked by their bytes, not their declared
  type). Index `i` in every response is the i-th photo as sent, from 0.
- `answers`: optional, the renter's three taps, with engine v2's names. Missing keys take the defaults.

```json
{"sleep_from": 23, "sleep_until": 7, "day_bothers": true, "bothers": ["traffic", "people", "neighbors", "sirens", "construction"]}
```

`sleep_from` and `sleep_until` are hours, 0 to 23. `bothers` is any subset of those five.

A bad request is `400 {"error": "<what to fix>"}`: no text and no photos, a file that is not an image, too
many photos, a bad `answers`.

## Response: server-sent events

`200`, `content-type: text/event-stream`. Each event is one JSON object on its `data:` line.

```
event: turn
data: {"n": 1, "by": "model", "tool": "read_photo", ...}

event: turn
data: {"n": 2, "by": "model", "tool": "submit_listing", ...}

event: turn
data: {"n": 3, "by": "code", "tool": "locate", ...}

event: turn
data: {"n": 4, "by": "code", "tool": "score", ...}

event: result
data: {"status": "complete", "fields": {...}, ...}
```

- `turn`: one per agent turn as it happens, then one per code step after the reading (`locate`, `score`).
- `result`: exactly once, last. It repeats every turn in `trace`.
- `error`: only on a server bug, instead of `result`: `{"error": "<type>: <message>"}`. Refusals, a model that
  runs out of turns and a Model API outage are not errors; they end in a `result`.

A read takes 1 to 8 model turns, then about 0.2 s to locate and up to 8 s to score (the first score of an
address pulls eight datasets; repeats are cached). Live turn times are not measured yet: no Meta key has been
on the build machine.

### A turn

```json
{"n": 2, "by": "model", "tool": "submit_listing", "args": {...}, "result": {...}, "ok": false,
 "ms": 2140, "model_ms": 2100, "tool_ms": 40, "tokens": {"input": 1830, "output": 210}}
```

| Key | Meaning |
|---|---|
| `n` | 1, 2, 3, ... across model turns and code steps |
| `by` | `model`: the model chose this tool. `code`: a fixed step after the reading |
| `tool` | `read_photo`, `submit_listing`, `locate`, `score`, or `null` when the model replied in plain text |
| `args` | what the tool was called with. Never photo bytes: `read_photo` args are `{"indexes": [0, 1]}` |
| `result` | what the tool returned. A refusal has `error`; a refused `submit_listing` also has `refused: {field: why}` and `accepted: [field names]` |
| `ok` | false when `result` has `error` |
| `ms` | the whole turn; `model_ms` the model's decision; `tool_ms` the tool. `tokens` from the Model API (mock: fixed numbers) |
| `said` | only when the model replied in plain text instead of calling a tool: the first 500 characters |

For `score`, `result` is `{"engine", "verdict", "quieter_than", "range"}`; the full score is in the final
result.

## The result

```json
{
  "status": "complete",
  "stopped": "submitted",
  "fields": {
    "address": {"value": "155 Ludlow Street", "status": "read",
                "evidence": [{"source": "text", "quote": "155 Ludlow Street", "start": 52, "end": 69}]},
    "unit":    {"value": "2A", "status": "read",
                "evidence": [{"source": "text", "quote": "Unit 2A", "start": 71, "end": 78}]},
    "floor":   {"value": 2, "status": "read",
                "evidence": [{"source": "text", "quote": "2nd floor", "start": 82, "end": 91}]},
    "side":    {"value": "street", "status": "read",
                "evidence": [{"source": "text", "quote": "Both bedrooms face Ludlow Street,\nwith tall windows and exposed brick", "start": 125, "end": 194}]}
  },
  "position": "front",
  "observed": {
    "view":          {"value": null, "status": "cant_tell", "evidence": []},
    "windows":       {"value": null, "status": "cant_tell", "evidence": []},
    "ac_units":      {"value": null, "status": "cant_tell", "evidence": []},
    "wall_material": {"value": null, "status": "cant_tell", "evidence": []}
  },
  "photo_readings": [],
  "location": {"label": "155 LUDLOW STREET, New York, NY, USA", "lat": 40.720952, "lng": -73.988157,
               "bbl": "1004110021", "bin": "1005354", "borough": "Manhattan"},
  "score": {"engine": "v2", "verdict": "Very loud", "quieter_than": 0.0, "range": null, "...": "the full v2 response"},
  "score_engine": "v2",
  "answers": {"sleep_from": 23, "sleep_until": 7, "day_bothers": true, "bothers": []},
  "needs": [],
  "notes": [],
  "trace": [{"n": 1, "...": "every turn, as streamed"}],
  "turns": {"used": 1, "budget": 8},
  "model": "muse-spark-1.3",
  "mode": "mock"
}
```

### A field

Every entry of `fields` and `observed` has the same three keys. **Read `status`, not `value`.**

| `status` | `value` | `evidence` |
|---|---|---|
| `read` | the value, typed as below | one or more items, every one checked |
| `cant_tell` | `null`; for `side` the string `"unknown"` | `[]` |

Evidence items:

- `{"source": "text", "quote": "...", "start": 52, "end": 69}`: `quote` is exactly `text[start:end]` of the
  text as sent, line breaks included. Highlight with the offsets.
- `{"source": "photo:0", "what": "cars parked on the street below"}`: what in photo 0 shows it, in the photo
  reader's words.

| Field | Type when read | Notes |
|---|---|---|
| `fields.address` | string | house number and street as written in the listing |
| `fields.unit` | string | as written, without "Apt" or "#" |
| `fields.floor` | integer, 1 to 120 | only when stated next to the word floor; a unit number like 3F is not a floor |
| `fields.side` | `street`, `rear`, `courtyard`, `corner` | |
| `observed.view` | `street`, `courtyard`, `rear_yards`, `airshaft`, `park`, `water`, `skyline` | photos only |
| `observed.windows` | `{"floor_to_ceiling": bool, "operable": bool or null}` | photos only |
| `observed.ac_units` | `window`, `through_wall`, `split`, `central` | photos only |
| `observed.wall_material` | `brick`, `concrete`, `plaster`, `glass`, `wood`, `stone` | photos only |

Only `floor` and `position` reach the score. `observed` is for the UI's "what the model saw"; no rule uses it
yet.

### The rest

| Key | Meaning |
|---|---|
| `status` | `complete`: a full submission passed every check. `partial`: the reader stopped first; fields that passed earlier are kept, the rest are `cant_tell` |
| `stopped` | `submitted`, `budget` (turns ran out), or `model_error` (the Model API kept failing) |
| `position` | what the engine gets from `side`: `street` and `corner` are `front`, `rear` and `courtyard` are `rear`, otherwise `unknown` |
| `photo_readings` | one per photo read, by index: `{"index", "fields": {floor, side, view, windows, ac_units, wall_material}, "note", "dropped": [why]}`; each field is `{value, status, what}`. `dropped` lists what the photo model said that failed its type and became cant_tell |
| `location` | GeoSearch's match for the address, or `null`. Refused unless its house number is the listing's |
| `score` | the score API's response, untouched: engine v2 (`/v2/score`), or v1 (`/v1/score`) until v2 is deployed. `null` when there is no address, it could not be placed, or scoring failed (`notes` says which) |
| `score_engine` | `v2`, `v1` or `null`. v2 has `verdict` and `quieter_than` at the top level and a `range` when floor or side is unknown; v1 has them under `manhattan` |
| `answers` | the answers the score used, defaults filled in |
| `needs` | what the renter must add for a score; today only `"address"` |
| `notes` | plain sentences for the UI: why a result is partial, why there is no score |
| `turns` | model turns used and the budget (`READER_TURNS`, default 8) |
| `model`, `mode` | the model name, and `live` or `mock` |

## What the checks guarantee

These run in code inside the tools (`reader/evidence.py`), so no prompt or model can skip them:

1. A field marked `read` has evidence. A text quote is in the listing text, exact except for whitespace, and
   states the value: the floor number next to the word floor, a side word ("rear", "courtyard", "corner unit",
   "faces Ludlow Street"), every token of the address and the unit. Adjectives such as "quiet" or
   "sun-drenched" never pass.
2. A photo citation names a photo that exists, that `read_photo` looked at, and whose reading shows the same
   value. The `what` is copied from that reading.
3. `read_photo` refuses an index that does not exist; the photo reader's own output is typed, and anything
   off-type becomes `cant_tell`.
4. The model gets the refusal and the reason, and tries again within its turns. When the turns run out the
   result is still clean: nothing unchecked is ever returned.
