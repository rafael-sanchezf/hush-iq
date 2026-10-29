# Listing reader

Hackathon work, Oct 28. A renter pastes a listing and its photos; Muse Spark reads them for the apartment
itself (address, unit, floor, side, and what the photos show), every fact tied to a quoted line or a photo, and
"can't tell" when the listing does not say. Then the code places the address with NYC GeoSearch and scores it
with the Hush IQ API (engine v2, v1 until v2 is deployed). Each turn streams as it happens.

The contract the website and the eval use: [`CONTRACT.md`](CONTRACT.md).

## How it works

An agent loop on the OpenAI Python SDK, pointed at the Meta Model API (`https://api.meta.ai/v1`,
`muse-spark-1.3`), modelled on the AgentKit pattern in
[meta-models/legal-agent-workshop](https://github.com/meta-models/legal-agent-workshop): the model picks one
tool per turn, the code runs it and sends back the result, and the checks live inside the tools.

| Tool | What the model gets | What the code checks |
|---|---|---|
| `read_photo` | per photo, each field it shows with what shows it, or cant_tell (one Muse Spark multimodal call per photo) | the index exists; every value has its type and a description, else cant_tell |
| `submit_listing` | accepted, or each refused field with the reason | every quote is in the text (whitespace aside) and states the value; adjectives and unit numbers never count; every photo citation was read and shows that value |

The loop stops when a submission is accepted, when the turn budget (8) runs out, or when the Model API keeps
failing, and every way out gives a clean result. The floor and the side (as `front`, `rear` or `unknown`)
go to the score; a silent listing gets the engine's expected floor and a range.

```
reader/
  loop.py          the agent loop and the steps after it; a generator, so the app can stream
  tools.py         read_photo and submit_listing: definitions and what they do
  evidence.py      every check on a field
  photos.py        one photo, one Muse Spark multimodal call
  scoring.py       GeoSearch and the score API (v2, falling back to v1)
  client.py        the Meta Model API client, or the offline mock when there is no key
  mock.py          the offline Model API: a real OpenAI client answered locally
  app.py           FastAPI, POST /read as server-sent events
  instructions.md  the system prompt
fixtures/          five synthetic listings for real Manhattan buildings, and what a correct reading returns
scripts/           run_fixtures.py: the five fixtures, live or mock, against expected.json
tests/             mock mode, offline, about a second
```

## Run it

```bash
cd services/agent
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env              # add MODEL_API_KEY for live; leave it empty for mock
.venv/bin/python -m pytest -q     # offline
.venv/bin/python -m reader fixtures/01-stated-rear.txt          # one listing, turn by turn
.venv/bin/python scripts/run_fixtures.py                        # all five against expected.json
.venv/bin/uvicorn reader.app:app --port 8100                    # POST /read
```

```bash
curl -N -X POST localhost:8100/read -F "text=<fixtures/03-street-front.txt" -F "photos=@kitchen.jpg"
```

`HUSH_SCORE_URL` points scoring at a local `packages/model` server instead of the hosted API;
`READER_SCORE=off` skips it.
