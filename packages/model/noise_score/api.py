"""HTTP surface: /v1/score (same shape as the CLI) [T1] and /v2/score (engine v2, hackathon).

    GET /v1/score?address=158 Bedford Ave, Brooklyn&floor=4&position=front&sleep=light&wfh=1&bothers=neighbors,traffic
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import __version__, baseline, model, sources, v2

app = FastAPI(title="Hush IQ", version=__version__)
# Read-only public API; any site may call it from the browser. [hackathon]
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


@app.get("/")
def index():
    return FileResponse(WEB)


@app.get("/v1/score")
def score(
    address: str = Query(..., min_length=3),
    floor: int | None = Query(None, ge=1, le=120),
    position: str = Query("unknown", pattern="^(front|rear|unknown)$"),
    sleep: str | None = Query(None, pattern="^(light|normal|heavy)$"),
    wfh: bool | None = None,
    bothers: str | None = Query(None, description="comma list of traffic,people,neighbors,sirens,construction"),
    fresh: bool = False,
):
    try:
        inputs = sources.pull_all(address, fresh=fresh)
    except sources.SourceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    unit = model.Unit(floor=floor, position=position)
    profile = None
    if sleep is not None or wfh is not None or bothers:
        profile = model.Profile(
            sleep=sleep or "normal",
            wfh=bool(wfh),
            bothers=[b.strip() for b in (bothers or "").split(",") if b.strip()],
        )
    res = model.score(inputs, unit, profile)
    try:
        res["manhattan"] = baseline.rank(res["internal_level"], unit, profile)   # [M12]
    except FileNotFoundError:
        res["manhattan"] = None
    return res


@app.get("/v2/score")
def score_v2(
    address: str = Query(..., min_length=3),
    floor: int | None = Query(None, ge=1, le=120, description="from the listing; omit when it does not say"),
    position: str = Query("unknown", pattern="^(front|rear|unknown)$", description="street side or rear, from the listing"),
    sleep_from: int = Query(23, ge=0, le=23, description="hour the renter falls asleep"),
    sleep_until: int = Query(7, ge=0, le=23, description="hour the renter wakes up"),
    day_bothers: bool = Query(True, description="does noise during the day bother the renter"),
    bothers: str | None = Query(None, description="comma list of traffic,people,neighbors,sirens,construction"),
    fresh: bool = False,
):
    """Engine v2 (hackathon): each source ranked against Manhattan, ranks averaged with the renter's weights.
    Every number is a rank; no decibels. Rules in ENGINE_V2.md."""
    try:
        inputs = sources.pull_all(address, fresh=fresh)
    except sources.SourceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    answers = v2.Answers(sleep=(sleep_from, sleep_until), day_bothers=day_bothers,
                         ticks=[b.strip() for b in (bothers or "").split(",") if b.strip()])
    return v2.score(inputs, model.Unit(floor=floor, position=position), answers)


@app.get("/v1/raw")
def raw(address: str = Query(..., min_length=3), fresh: bool = False):
    """The untouched pulls behind a score, for checking the ingredients by hand."""
    try:
        return sources.pull_all(address, fresh=fresh)
    except sources.SourceError as e:
        raise HTTPException(status_code=502, detail=str(e))
