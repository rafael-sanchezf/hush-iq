"""HTTP surface: POST /adjust/permits. (Hackathon work, Oct 28; the AI switch and caller keys Oct 29, HIQ-77.)
The shape is in CONTRACT.md.

    uvicorn adjust.api:app --port 8030        (from services/adjust)

Four optional headers pick the AI path (switch.py): X-HushIQ-AI, X-HushIQ-Provider, X-HushIQ-Key, X-HushIQ-Model.
Headers, never query parameters, so a key never lands in a URL or a log line. `router` is what the main API mounts
once the engine is wired; `app` serves it alone.
"""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from . import __version__, llm, switch
from .permits import block_permits, read_permits


class PermitsRequest(BaseModel):
    address: str | None = Field(None, min_length=3, description="pull the tax block's permits for this address")
    permits: list[dict] | None = Field(None, description="or send the permit rows yourself, as /v1/raw returns them")
    as_of: dt.date | None = Field(None, description="the date permits must not have expired by; default today")
    reader: Literal["auto", "model", "rules"] = "auto"

    @model_validator(mode="after")
    def one_of(self):
        if (self.address is None) == (self.permits is None):
            raise ValueError("send exactly one of address or permits")
        return self


def get_client():
    return llm.client_from_env()


def get_connect():
    return llm.client_for


router = APIRouter()


@router.post("/adjust/permits")
def adjust_permits(req: PermitsRequest, client=Depends(get_client), connect=Depends(get_connect),
                   x_hushiq_ai: str | None = Header(None), x_hushiq_provider: str | None = Header(None),
                   x_hushiq_key: str | None = Header(None), x_hushiq_model: str | None = Header(None)):
    try:
        choice = switch.choose(x_hushiq_ai, x_hushiq_provider, x_hushiq_key, x_hushiq_model)
    except switch.BadSwitch as e:
        raise HTTPException(status_code=400, detail=str(e))
    if req.reader == "model" and switch.blocked(choice, client):
        raise HTTPException(status_code=503, detail="no model can run for this request; use reader=auto")
    located = None
    rows = req.permits
    if req.address is not None:
        from noise_score import sources
        try:
            located, rows = block_permits(req.address, req.as_of)
        except sources.SourceError as e:
            raise HTTPException(status_code=502, detail=str(e))
    if req.reader == "rules" and choice.on:   # tests and the eval: the keyword rules, no model call
        out = read_permits(rows, req.as_of)
        out["ai"] = {"mode": "rules", "provider": None, "model": None, "key": None, "reason": None, "message": None}
    else:
        out = switch.run(rows, req.as_of, choice, house=client, connect=connect)
    if located:
        out["address"] = {k: located.get(k) for k in ("query", "label", "bbl", "bin", "borough")}
    return out


app = FastAPI(title="Hush IQ adjustments", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])
app.include_router(router)
