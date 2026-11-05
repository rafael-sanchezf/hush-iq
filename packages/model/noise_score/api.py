"""HTTP surface: /v1/score (same shape as the CLI) [T1] and /v2/score (engine v2, hackathon).

    GET /v1/score?address=158 Bedford Ave, Brooklyn&floor=4&position=front&sleep=light&wfh=1&bothers=neighbors,traffic

Every route places the address through `locate` (HIQ-116): a blank address, one GeoSearch cannot place, or a
match on another house or street is a 422 with a short message, never a score for the wrong building, and an
upstream failure is a 502 that names the dataset, never its URL.
"""
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import __version__, baseline, config_v2, model, sources, v2

app = FastAPI(title="Hush IQ", version=__version__)
# Read-only public API; any site may call it from the browser. [hackathon]
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


@app.get("/")
def index():
    return FileResponse(WEB)


# ---------------------------------------------------------------- placing the address [HIQ-116]
EXAMPLE = "Give the building's number and street, like 140 Claremont Ave, Manhattan."
# Spelled out as GeoSearch spells them, as the listing reader does (services/agent/reader/scoring.py)
STREET_WORDS = {"E": "EAST", "W": "WEST", "N": "NORTH", "S": "SOUTH", "ST": "STREET", "AVE": "AVENUE", "AV": "AVENUE",
                "PL": "PLACE", "RD": "ROAD", "BLVD": "BOULEVARD", "DR": "DRIVE", "LN": "LANE", "SQ": "SQUARE",
                "TER": "TERRACE", "PKWY": "PARKWAY", "B'WAY": "BROADWAY", "BWAY": "BROADWAY",
                **{w: str(i) for i, w in enumerate(("FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH",
                                                    "EIGHTH", "NINTH", "TENTH", "ELEVENTH", "TWELFTH"), 1)}}
HOUSE = re.compile(r"\s*(\d+(?:-\d+)?[A-Za-z]?)\b(.*)")


def house_and_street(line):
    """("310", ["WEST", "47", "STREET"]) for "310 W. 47th St."; the house is None when the line has no number."""
    m = HOUSE.match(line or "")
    house, rest = (m.group(1).upper(), m.group(2)) if m else (None, line or "")
    words = [re.sub(r"^(\d+)(ST|ND|RD|TH)$", r"\1", w) for w in re.findall(r"[A-Za-z0-9']+", rest.upper())]
    return house, [STREET_WORDS.get(w, w) for w in words]


def same_building(query, label):
    """GeoSearch answers its best guess, not a match: '99999 Broadway' comes back as 99999 Springfield Avenue in
    Queens. The house number must match and the label's street must open the query's (the query may go on with
    a unit or a city, with or without a comma)."""
    q_house, q_street = house_and_street(query.split(",")[0])
    l_house, l_street = house_and_street((label or "").split(",")[0])
    return bool(q_house) and q_house == l_house and bool(l_street) and q_street[:len(l_street)] == l_street


def pretty(label):
    """'218 PENNSYLVANIA AVENUE, Brooklyn, NY, USA' as '218 Pennsylvania Avenue, Brooklyn, NY'."""
    head, _, tail = (label or "").partition(",")
    return ", ".join(x for x in (head.title(), tail.removesuffix(", USA").strip(" ,")) if x)


def upstream(e):
    """A SourceError carries the upstream URL; say only which dataset did not answer."""
    name = str(e).split(":", 1)[0] or "city"
    return HTTPException(status_code=502, detail=f"The city's {name} data did not answer. Try again in a minute.")


BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")


def borough_said(address):
    return next((b for b in BOROUGHS if re.search(rf"\b{b}\b", address, re.I)), None)


def candidates(address, fresh=False):
    """GeoSearch's ten best, in the frozen geocode's shape: '1 Centre St' comes back first as a school in Queens,
    with the Bronx's and Manhattan's 1 Centre Street further down."""
    doc = sources._get("geocode", sources.GEOSEARCH, {"text": address, "size": 10}, fresh)
    out = []
    for f in doc.get("features") or []:
        lng, lat = f["geometry"]["coordinates"]
        p = f["properties"]
        pad = (p.get("addendum") or {}).get("pad") or {}
        out.append({"query": address, "label": p.get("label"), "lat": lat, "lng": lng,
                    "bbl": pad.get("bbl") or p.get("pad_bbl"), "bin": pad.get("bin") or p.get("pad_bin"),
                    "borough": p.get("borough")})
    return out


def locate(address, fresh=False):
    """The geocoded building for this address, or a 422 that says why not. GeoSearch's first answer when it is
    this house on this street (in the borough the address names, if it names one); else the one candidate that
    is; two boroughs with the same address ask for the borough."""
    address = (address or "").strip()
    if len(address) < 3 or not house_and_street(address.split(",")[0])[0]:
        raise HTTPException(status_code=422, detail=EXAMPLE)
    said = borough_said(address)
    try:
        a = sources.geocode(address, fresh)
        if same_building(address, a.get("label")) and said in (None, a.get("borough")):
            return a
        exact = [c for c in candidates(address, fresh) if same_building(address, c["label"])
                 and said in (None, c["borough"])]
    except sources.SourceError as e:
        if str(e).startswith("geocode: no match"):
            raise HTTPException(status_code=422, detail=f"No New York City address matches that. {EXAMPLE}")
        raise upstream(e)
    boroughs = list(dict.fromkeys(c["borough"] for c in exact))
    if len(boroughs) == 1:
        return exact[0]
    if boroughs:
        raise HTTPException(status_code=422, detail=f"That address is in more than one borough. Add the borough, like "
                                                    f"{address.split(',')[0]}, {boroughs[-1]}.")
    raise HTTPException(status_code=422, detail=f"No exact match for that address. The closest is {pretty(a.get('label'))}.")


def pull(address, fresh=False):
    a = locate(address, fresh)
    try:
        return sources.pull_at(a, fresh=fresh)
    except sources.SourceError as e:
        raise upstream(e)


def ticks_of(bothers):
    """[HIQ-137] The renter's ticks, lower-cased; anything outside the five is a 422 naming them."""
    ticks = [b.strip().lower() for b in (bothers or "").split(",") if b.strip()]
    unknown = [t for t in ticks if t not in config_v2.TICK_TO_SOURCE]
    if unknown:
        raise HTTPException(status_code=422, detail=f"bothers takes {', '.join(config_v2.TICK_TO_SOURCE)}; "
                                                    f"{len(unknown)} value{'s' if len(unknown) > 1 else ''} not in that list.")
    return ticks


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
    inputs = pull(address, fresh)
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
    ticks = ticks_of(bothers)
    if sleep_from == sleep_until:
        raise HTTPException(status_code=422, detail="sleep_from and sleep_until are the same hour; give the hour you "
                                                    "fall asleep and the hour you wake up.")
    inputs = pull(address, fresh)
    answers = v2.Answers(sleep=(sleep_from, sleep_until), day_bothers=day_bothers, ticks=ticks)
    return v2.score(inputs, model.Unit(floor=floor, position=position), answers)


@app.get("/v1/raw")
def raw(address: str = Query(..., min_length=3), fresh: bool = False):
    """The untouched pulls behind a score, for checking the ingredients by hand."""
    return pull(address, fresh)
