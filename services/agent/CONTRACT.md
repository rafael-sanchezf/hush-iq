# Listing reader contract: `POST /read` and `POST /key-check`

What the website, the extension and the eval code against. Changes to this shape are additive only: new keys
may appear, existing keys keep their name, type and meaning. Hackathon work, Oct 28; the AI switch and caller
keys, Oct 29 (HIQ-75).

## Run it

```bash
cd services/agent
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn reader.app:app --port 8100
```

Who reads a listing is decided per request (below, [The AI switch and caller keys](#the-ai-switch-and-caller-keys)).
With no headers it is Muse Spark (`muse-spark-1.3`) on the house key, `MODEL_API_KEY` in `services/agent/.env`.
With no house key, with `HOUSE_AI=off`, or with AI switched off, it is the **basic reader**: regular
expressions on the text, no model call, photos unread. Every result carries `ai` (and the older `mode`:
`live` or `mock`), so a basic result is never shown as the model's. `GET /` says what the house runs and which
providers and models a caller may ask for.

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
many photos, a bad `answers`, a bad `X-HushIQ-` header (an unknown provider, a model not on the list).

Four optional headers choose the model; see [The AI switch and caller keys](#the-ai-switch-and-caller-keys).

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

- `turn`: one per agent turn as it happens, then one per code step after the reading (`locate`, `floors` when
  the listing says PH, penthouse or top floor, `score`).
- `result`: exactly once, last. It repeats every turn in `trace`.
- `error`: only on a server bug, instead of `result`: `{"error": "<type>: <message>"}`. Refusals, a model that
  runs out of turns and a Model API outage are not errors; they end in a `result`.

Measured live (Oct 28, seven fixtures): a model turn takes 2 to 7 s (a submit_listing turn 4 to 7 s, mostly
reasoning); reading two photos in parallel takes 8 to 10 s; text-only listings finished in one turn and the
photo listing in two. Then about 0.2 s to locate and up to 8 s to score (the first score of an address pulls eight datasets; repeats are cached).
End to end: 7 to 11 s for text, about 20 s with two photos.

### A turn

```json
{"n": 2, "by": "model", "tool": "submit_listing", "args": {...}, "result": {...}, "ok": false,
 "ms": 6320, "model_ms": 6316, "tool_ms": 4, "tokens": {"input": 3268, "output": 1795, "reasoning": 1466},
 "retries": 0}
```

| Key | Meaning |
|---|---|
| `n` | 1, 2, 3, ... across model turns and code steps |
| `by` | `model`: the model chose this tool. `code`: a fixed step after the reading |
| `tool` | `read_photo`, `submit_listing`, `locate`, `floors`, `score`, or `null` when the model replied in plain text or the provider failed |
| `args` | what the tool was called with. Never photo bytes: `read_photo` args are `{"indexes": [0, 1]}` |
| `result` | what the tool returned. A refusal has `error`; a refused `submit_listing` also has `refused: {field: why}` and `accepted: [field names]`. A failed provider call has `error` and `reason` (as in `ai.reason`) |
| `ok` | false when `result` has `error` |
| `ms` | the whole turn; `model_ms` the model's decision; `tool_ms` the tool. `tokens` from the Model API, reasoning included in output (mock: fixed numbers) |
| `retries` | times the model was asked again in this turn because its reply was empty (cut off at the token cap) |
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
               "bbl": "1004110021", "bin": "1005354", "borough": "Manhattan",
               "borough_from": {"how": "only match"}, "alternatives": []},
  "score": {"engine": "v2", "verdict": "Very loud", "quieter_than": 0.0, "range": null, "...": "the full v2 response"},
  "score_engine": "v2",
  "answers": {"sleep_from": 23, "sleep_until": 7, "day_bothers": true, "bothers": []},
  "needs": [],
  "notes": [],
  "trace": [{"n": 1, "...": "every turn, as streamed"}],
  "turns": {"used": 1, "budget": 8},
  "model": "muse-spark-1.3",
  "mode": "mock",
  "ai": {"mode": "basic", "provider": null, "model": null, "key": null, "reason": "switched_off",
         "message": "AI reading is off in your settings, so the basic reader read this listing."}
}
```

### A field

Every entry of `fields` and `observed` has the same three keys. **Read `status`, not `value`.**

| `status` | `value` | `evidence` |
|---|---|---|
| `read` | the value, typed as below | one or more items, every one checked |
| `cant_tell` | `null`; for `side` the string `"unknown"` | `[]` |

A field may also carry `note`, a sentence for the UI, and `derived`, when the value was not in the listing as
written. Today only `floor` does: "PH", "penthouse" or "top floor" with no number becomes the building's floor
count from the city's PLUTO data, with
`"derived": {"from": "top", "floors": 18, "source": "NYC PLUTO numfloors"}` and a note that says so, while the
evidence keeps the listing's own words. If the address cannot be placed, or PLUTO has no floor count, the floor
is `cant_tell`, with a note saying why. The note is repeated in `notes`.

Evidence items:

- `{"source": "text", "quote": "...", "start": 52, "end": 69}`: `quote` is exactly `text[start:end]` of the
  text as sent, line breaks included. Highlight with the offsets.
- `{"source": "photo:0", "what": "cars parked on the street below"}`: what in photo 0 shows it, in the photo
  reader's words.

| Field | Type when read | Notes |
|---|---|---|
| `fields.address` | string | house number and street as written in the listing |
| `fields.unit` | string | as written, without "Apt" or "#" |
| `fields.floor` | integer, 1 to 120 | stated next to the word floor; garden level is 1; PH, penthouse or top floor is the building's floor count (`derived`). A unit number like 12F is not a floor |
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
| `stopped` | `submitted`, or `budget` (turns ran out). A provider that keeps failing no longer stops the reading: the basic reader reads it again (see `ai`). `model_error` stays in the vocabulary but is not expected |
| `position` | what the engine gets from `side`: `street` and `corner` are `front`, `rear` and `courtyard` are `rear`, otherwise `unknown` |
| `photo_readings` | one per photo read, by index: `{"index", "fields": {floor, side, view, windows, ac_units, wall_material}, "note", "dropped": [why], "tokens"}`; each field is `{value, status, what}`. `dropped` lists what the photo model said that failed its type and became cant_tell |
| `location` | the building GeoSearch has at that house number on that street, or `null`. `borough_from` says how the borough was chosen when the address exists in more than one: `{"how": "only match"}`, `{"how": "text", "borough", "said"}` (a borough, ZIP or neighborhood in the listing), or `{"how": "default", "borough": "Manhattan"}` with a note. `alternatives` lists the other boroughs' labels |
| `score` | the score API's response, untouched: engine v2 (`/v2/score`), or v1 (`/v1/score`) until v2 is deployed. `null` when there is no address, it could not be placed, or scoring failed (`notes` says which) |
| `score_engine` | `v2`, `v1` or `null`. v2 has `verdict` and `quieter_than` at the top level and a `range` when floor or side is unknown; v1 has them under `manhattan` |
| `answers` | the answers the score used, defaults filled in |
| `needs` | what the renter must add for a score; today only `"address"` |
| `notes` | plain sentences for the UI: why a result is partial, why there is no score |
| `turns` | model turns used and the budget (`READER_TURNS`, default 8). After a provider failure, `used` counts the failed turns and the basic reader's |
| `model`, `mode` | kept for older clients: the model asked for, and `live` (a model read) or `mock` (the basic reader). Read `ai` instead |
| `ai` | who read the listing and, for the basic reader, why. Below |

## The AI switch and caller keys

The Meta-model reading may be removed when the hackathon credits end, so it sits behind a switch, and a caller
may bring their own OpenAI or Anthropic key to run the same prompt and the same checks. The shared contract for
every service is `AI_SWITCH.md` (HIQ-74); this is the reader's part.

### Headers

On `POST /read` and `POST /key-check`. Headers, never query parameters, so a key never lands in a URL, a log
line or browser history. Names are case-insensitive.

| Header | Values | Absent means |
|---|---|---|
| `X-HushIQ-AI` | `on`, `off` | `on` |
| `X-HushIQ-Provider` | `meta`, `openai`, `anthropic` | `meta` |
| `X-HushIQ-Key` | the caller's API key for that provider | the house key (Meta only) |
| `X-HushIQ-Model` | a model id from the provider's list below | the provider's default |

| Request | Who reads | `ai.reason` |
|---|---|---|
| `X-HushIQ-AI: off` | the basic reader; no model call at all, cost zero | `switched_off` |
| a key | that provider with that key, for this request only | |
| no key, `meta` | Muse Spark on the house key | |
| no key, `meta`, server has `HOUSE_AI=off` (or `READER_MODE=mock`) | the basic reader | `house_off` |
| no key, `meta`, server has no `MODEL_API_KEY` | the basic reader | `no_key` |
| no key, `openai` or `anthropic` | the basic reader | `no_key` |
| the provider rejects the key (401, 402, 403) | the basic reader, from the start | `key_rejected` |
| the provider rate-limits or is overloaded (429, 529) | the basic reader, from the start | `provider_busy` |
| the provider fails otherwise (timeout, 5xx, 404) | the basic reader, from the start | `provider_error` |

A provider failure is caught on the model's turn: the failed turn stays in the trace (`ok: false`, `result`
has `error` and `reason`), and the basic reader then reads the listing from the start, numbering its turns on
from there. Fields the model had read before the failure are not kept. **There is no path from a caller's key to
the house key**: a stranger's failing key never spends the house credits. A photo the provider fails to read
comes back unread (`failed: true`) and the reading goes on.

### Providers and models

| Provider | Base URL (fixed on the server) | Models | Default |
|---|---|---|---|
| `meta` | `https://api.meta.ai/v1` | `muse-spark-1.3` | `muse-spark-1.3` (the house sets it with `MODEL_API_MODEL`) |
| `openai` | `https://api.openai.com/v1` | `gpt-6-luna`, `gpt-6.1-terra`, `gpt-6.1-sol` | `gpt-6-luna` |
| `anthropic` | `https://api.anthropic.com` | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` | `claude-opus-5-5` |

The caller cannot set a base URL, so a key only ever goes to its own provider. An id not on the list is a 400.
Ids were checked against each provider's docs on 2026-10-29. The OpenAI and Anthropic defaults stand until the
eval compares the models (HIQ-79); `gpt-6-luna` is OpenAI's cheapest current model and takes images and
function tools in the Responses API.

- **meta**: today's path, unchanged: the OpenAI SDK at api.meta.ai, Responses API.
- **openai**: the same SDK at api.openai.com. Two request differences: `include:
  ["reasoning.encrypted_content"]`, because with `store: false` a reasoning model's reasoning must travel with
  the conversation, and `strict: false` on both tools, because OpenAI's function tools are strict by default and
  our optional fields do not fit strict mode.
- **anthropic**: the Anthropic Python SDK, Messages API, behind an adapter (`reader/anthropic_adapter.py`) that
  answers the loop's Responses calls: tools, images (base64), tool results, and Claude's thinking blocks
  replayed unchanged on the next turn. `max_tokens` is at least 16,000 because thinking counts against it.
  Anthropic takes images up to 5 MB, under the reader's 8 MB limit: a larger photo comes back unread.
- Every provider gets the same prompt (`reader/instructions.md`), the same tools and the same checks in code.
  A provider's reply is held to exactly the checks Muse is held to.

Not verified live: no OpenAI or Anthropic key exists yet, so both paths are tested against in-process fakes of
their APIs only. Whether `gpt-6-luna` honours the photo reader's JSON mode is unverified; if it does not, its
photos come back unread.

### The `ai` object

On every result, next to `model` and `mode`:

```json
"ai": {"mode": "model" | "basic", "provider": "meta" | "openai" | "anthropic" | null,
       "model": "<id>" | null, "key": "house" | "caller" | null,
       "reason": null | "switched_off" | "house_off" | "no_key" | "key_rejected" | "provider_busy" | "provider_error",
       "message": "<one plain sentence for the panel>" | null}
```

- `mode: "model"`: `provider`, `model` and `key` say who read it; `reason` and `message` are `null`.
- `mode: "basic"`: `reason` and `message` are set; `model` is `null`; `provider` and `key` say what was asked for
  and did not run (`null` when the caller switched AI off).
- Show `message` in the panel, for example "AI reading is off. Add your own key in settings to turn it on." or
  "OpenAI rejected your key, so the basic reader read this listing."

### The key, on the server

1. Never logged, never in a trace, never in a response, never in an error message: every event passes through
   `failures.scrub()`, which replaces the caller's key and the house key wherever they appear, and an error from a
   provider is described with anything key-shaped (`sk-...`, long tokens) masked as `[redacted]`.
2. Never stored or cached: the client is built for the request and dropped with it.
3. Sent only to its provider's fixed base URL.
4. `tests/test_keys.py` sends a fake key through every path (success, 401, 429, timeout, a model the provider
   does not have, a model id not on the list), for each provider, on both endpoints, with every logger at DEBUG,
   and asserts the key appears in none of the body, the trace, the logs or the console. The fake providers quote
   the key in full in their errors.

### `POST /key-check`

Same headers, no body. One call to the provider's models list, which spends no tokens. Always `200` unless a
header is bad (`400`):

```json
{"ok": true, "provider": "openai", "message": "OpenAI accepted the key, and gpt-6-luna is available."}
```

`ok` is false when no key was sent, when the provider rejects the key, rate-limits it or cannot be reached, or
when the key works but the chosen model is not in its list. `message` says which, in one sentence. The
extension's "Test key" button uses it.

### In process (the eval)

```python
from reader import loop
from reader.client import from_env, make_client

plan = make_client(provider="anthropic", key=..., model=None, ai="on")   # the four headers, as arguments
plan = from_env("openai")          # the key from OPENAI_API_KEY or ANTHROPIC_API_KEY, never a tracked file
result = loop.read(listing, plan=plan, scorer=scorer)
```

The command line takes the same choice: `python -m reader listing.txt --ai off` and `scripts/run_fixtures.py
--provider anthropic --model claude-haiku-5-5`.

## What the checks guarantee

These run in code inside the tools (`reader/evidence.py`), so no prompt or model can skip them:

1. A field marked `read` has evidence. A text quote is in the listing text, exact except for whitespace, and
   states the value: the floor number next to the word floor (or garden level, PH, penthouse, top floor), a
   side word ("rear", "courtyard", "corner unit", "faces Ludlow Street"), every token of the address and the
   unit. Adjectives such as "quiet" or "sun-drenched" never pass. A quote under 4 characters is refused as too
   short, with its length, so the model quotes more rather than hunting for a different span.
2. A photo citation names a photo that exists, that `read_photo` looked at, and whose reading shows the same
   value. The `what` is copied from that reading.
3. `read_photo` refuses an index that does not exist; the photo reader's own output is typed, and anything
   off-type becomes `cant_tell`.
4. The model gets the refusal and the reason, and tries again within its turns. When the turns run out the
   result is still clean: nothing unchecked is ever returned.
5. All of this holds for every provider and for the basic reader: they answer the same tools, and the tools do
   the checking.
