"""HTTP surface of the listing reader. (Hackathon work, Oct 28.)

    POST /read       the listing in (multipart or JSON: text, photos, optional answers); server-sent events out,
                     one `turn` event per turn and then one `result` event. The shape is in CONTRACT.md.
    POST /key-check  is a caller's key accepted (one free models-list call)?

Both take four optional headers, never query parameters, so a key stays out of URLs and logs: X-HushIQ-AI
(on|off), X-HushIQ-Provider (meta|openai|anthropic), X-HushIQ-Key and X-HushIQ-Model. client.py decides what
they mean.

    .venv/bin/uvicorn reader.app:app --port 8100
"""
import json
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import client as model_client
from . import failures, loop, settings
from .listing import MAX_PHOTOS, Answers, BadInput, Listing, Photo
from .scoring import HostedScorer


def default_scorer():
    """The hosted score API, or none when READER_SCORE=off (offline work on the reader alone)."""
    return None if os.environ.get("READER_SCORE", "").lower() == "off" else HostedScorer()


HEADERS = {"ai": "x-hushiq-ai", "provider": "x-hushiq-provider", "key": "x-hushiq-key", "model": "x-hushiq-model"}


def choice(headers):
    """The four X-HushIQ headers as make_client's arguments."""
    return {arg: headers.get(name) for arg, name in HEADERS.items()}


def create_app(make_client=model_client.make_client, make_scorer=default_scorer, turns=None,
               check_key=model_client.check_key):
    app = FastAPI(title="Hush IQ listing reader", version="0.1.0")
    # Public, keyless, read-only for the caller: any site may call it from the browser.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
    scorer = make_scorer()

    @app.get("/")
    def index():
        house = make_client()
        return {"service": "hush-iq listing reader", "mode": house.mode, "model": settings.model(),
                "ai": {"house": house.ai, "providers": model_client.providers(), "headers": sorted(HEADERS.values())},
                "read": "POST /read (multipart or JSON: text, photos[], answers); streams turn events, then result",
                "contract": "https://github.com/rafael-sanchezf/hush-iq/blob/main/services/agent/CONTRACT.md"}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/read")
    async def read(request: Request):
        try:
            plan = make_client(**choice(request.headers))
            listing = await parse(request)
        except (BadInput, model_client.BadChoice) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        events = loop.read_listing(listing, plan=plan, scorer=scorer, turns=turns)
        return StreamingResponse(sse(events, plan.secrets), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/key-check")
    def key_check(request: Request):
        c = choice(request.headers)
        try:
            return check_key(c["provider"], c["key"], c["model"])
        except model_client.BadChoice as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    return app


async def parse(request):
    kind = request.headers.get("content-type", "")
    if kind.startswith("multipart/form-data"):
        form = await request.form(max_files=MAX_PHOTOS + 1)
        files = [f for f in form.getlist("photos") + form.getlist("photos[]") if hasattr(f, "read")]
        if len(files) > MAX_PHOTOS:
            raise BadInput(f"at most {MAX_PHOTOS} photos")
        photos = [Photo.from_bytes(await f.read(), f.filename or str(i)) for i, f in enumerate(files)]
        text = form.get("text") if isinstance(form.get("text"), str) else ""
        answers = _json_field(form.get("answers"))
    elif "json" in kind:
        try:
            body = await request.json()
        except ValueError:
            raise BadInput("the body is not valid JSON")
        if not isinstance(body, dict):
            raise BadInput("the body must be a JSON object")
        raw = body.get("photos") or []
        if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
            raise BadInput("photos must be a list of data URLs (data:image/jpeg;base64,...)")
        if len(raw) > MAX_PHOTOS:
            raise BadInput(f"at most {MAX_PHOTOS} photos")
        photos = [Photo.from_data_url(p, str(i)) for i, p in enumerate(raw)]
        text = body.get("text") if isinstance(body.get("text"), str) else ""
        answers = body.get("answers")
    else:
        raise BadInput("send multipart/form-data or application/json")
    return Listing(text=text, photos=photos, answers=Answers.parse(answers))


def _json_field(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except ValueError:
        raise BadInput("answers must be a JSON object")


def sse(events, secrets=()):
    try:
        for kind, data in events:
            yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"
    except Exception as e:   # a bug, not a refusal: the stream still ends with an event the client can read
        error = failures.scrub(f"{type(e).__name__}: {e}", secrets)
        yield f"event: error\ndata: {json.dumps({'error': error})}\n\n"


settings.load_env()
app = create_app()
