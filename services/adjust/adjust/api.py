"""HTTP surface: POST /adjust/permits. (Hackathon work, Oct 28.) The shape is in CONTRACT.md.

    uvicorn adjust.api:app --port 8030        (from services/adjust)

`router` is what the main API mounts once the engine is wired; `app` serves it alone.
"""
import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from . import __version__, llm
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


router = APIRouter()


@router.post("/adjust/permits")
def adjust_permits(req: PermitsRequest, client=Depends(get_client)):
    if req.reader == "model" and client is None:
        raise HTTPException(status_code=503, detail="no model key is set; use reader=rules or auto")
    use = None if req.reader == "rules" else client
    located = None
    rows = req.permits
    if req.address is not None:
        from noise_score import sources
        try:
            located, rows = block_permits(req.address, req.as_of)
        except sources.SourceError as e:
            raise HTTPException(status_code=502, detail=str(e))
    out = read_permits(rows, req.as_of, client=use, model=llm.model_name() if use else None)
    if located:
        out["address"] = {k: located.get(k) for k in ("query", "label", "bbl", "bin", "borough")}
    return out


app = FastAPI(title="Hush IQ adjustments", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])
app.include_router(router)
