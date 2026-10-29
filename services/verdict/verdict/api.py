"""HTTP surface: POST /verdict and GET /health. The shape is in CONTRACT.md.

    uvicorn verdict.api:app --port 8030
"""
import functools
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__, evidence, writer

app = FastAPI(title="Hush IQ verdict writer", version=__version__)
# Called from the website in the browser; it holds no secrets and writes nothing. [hackathon]
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
    """Read once per process: the model backend the env and services/verdict/.env configure, or None."""
    return writer.from_env()


@app.post("/verdict")
def verdict(body: VerdictIn, writer_choice: Literal["auto", "template"] = Query("auto", alias="writer"),
            backend=Depends(get_backend)):
    try:
        lines = evidence.build(body.score, body.answers.model_dump() if body.answers else None, body.fields)
    except evidence.EvidenceError as e:
        raise HTTPException(status_code=422, detail=str(e))
    out = writer.write(lines, None if writer_choice == "template" else backend)
    return {"evidence": [l.public() for l in lines], **out}


@app.get("/health")
def health(backend=Depends(get_backend)):
    return {"ok": True, "version": __version__, "writer": backend.name if backend else "template",
            "model": backend.model if backend else None}
