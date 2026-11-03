"""HTTP surface: POST /verdict and GET /health. The shape is in CONTRACT.md.

    uvicorn verdict.api:app --port 8030
"""
import dataclasses
import functools
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__, evidence, switch, writer

app = FastAPI(title="Hush IQ verdict writer", version=__version__)
# Called from the website in the browser; it stores nothing, and a caller's key is used once and dropped. [hackathon]
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


class Answers(BaseModel):
    """The renter's three taps, in the engine v2 query names."""
    sleep_from: int = Field(23, ge=0, le=23, description="hour the renter falls asleep")
    sleep_until: int = Field(7, ge=0, le=23, description="hour the renter wakes up")
    day_bothers: bool = Field(True, description="does noise during the day bother the renter")
    bothers: list[Literal["traffic", "people", "neighbors", "sirens", "construction"]] = []


class VerdictIn(BaseModel):
    score: dict = Field(..., description="an engine v2 /v2/score response, or a v1 /v1/score response")
    answers: Answers | None = None
    fields: dict | None = Field(None, description="the listing reader's fields: address, unit, floor, side")


@functools.lru_cache(maxsize=1)
def get_backend():
    """Read once per process: the house backend the env and services/verdict/.env configure, or None."""
    return writer.from_env()


def get_http_client():
    """None: each caller's SDK client makes its own connection. The tests put a mock transport here."""
    return None


@app.post("/verdict")
def verdict(body: VerdictIn, writer_choice: Literal["auto", "template"] = Query("auto", alias="writer"),
            x_ai: str | None = Header(None, alias="X-HushIQ-AI"),
            x_provider: str | None = Header(None, alias="X-HushIQ-Provider"),
            x_key: str | None = Header(None, alias="X-HushIQ-Key"),
            x_model: str | None = Header(None, alias="X-HushIQ-Model"),
            backend=Depends(get_backend), http_client=Depends(get_http_client)):
    try:
        req = switch.request(x_ai, x_provider, x_key, x_model)
    except switch.RequestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if writer_choice == "template":
        req = dataclasses.replace(req, ai="off")
    try:
        lines = evidence.build(body.score, body.answers.model_dump() if body.answers else None, body.fields)
    except evidence.EvidenceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    out = switch.run(lines, req, house=backend, http_client=http_client)
    return {"evidence": [l.public() for l in lines], **out}


@app.get("/health")
def health(backend=Depends(get_backend)):
    return {"ok": True, "version": __version__, "writer": backend.name if backend else "template",
            "model": backend.model if backend else None, "house_ai": "on" if switch.house_on() else "off",
            "providers": {p: {"models": list(v["models"]), "default": v["models"][0]} for p, v in writer.PROVIDERS.items()}}
