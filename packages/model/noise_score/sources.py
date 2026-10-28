"""Every upstream pull. All public, no key needed; a Socrata app token raises the rate limit. [T2][T3]

Each function returns plain dicts (JSON-serialisable) so pulls can be cached and replayed offline.
"""
import datetime as dt
import os

import httpx

from . import cache, config
from .geo import haversine_m

NYC = "https://data.cityofnewyork.us/resource"
NYS = "https://data.ny.gov/resource"
GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"

DATASETS = {
    "311": f"{NYC}/erm2-nwe9.json",        # 311 Service Requests 2010-present
    "pluto": f"{NYC}/64uk-42ks.json",      # Primary Land Use Tax Lot Output
    "roads": f"{NYC}/inkn-q76z.json",      # NYC Street Centerline (CSCL)
    "permits": f"{NYC}/rbx6-tga4.json",    # DOB NOW: Build, Approved Permits
    "liquor": f"{NYS}/9s3h-dpkz.json",     # NYS Liquor Authority, Current Active Licenses
    "stations": f"{NYS}/39hk-dx4f.json",   # MTA Subway Stations (structure: Elevated, Subway, ...)
    "facilities": f"{NYC}/67g2-p84d.json", # NYC Facilities Database (hospitals, firehouses, police) [M11]
}


class SourceError(RuntimeError):
    pass


def _client():
    headers = {"User-Agent": config.USER_AGENT}
    token = os.environ.get("NOISE_SCORE_SOCRATA_TOKEN") or config.SOCRATA_APP_TOKEN
    if token:
        headers["X-App-Token"] = token
    return httpx.Client(headers=headers, timeout=config.HTTP_TIMEOUT_S)


def _get(name, url, params, fresh=False):
    key_params = {"url": url, **params}
    if not fresh:
        hit = cache.get(name, key_params)
        if hit is not None:
            return hit
    with _client() as c:
        for attempt in range(3):
            try:
                r = c.get(url, params=params)
                r.raise_for_status()
                return cache.put(name, key_params, r.json())
            except (httpx.HTTPError, ValueError) as e:
                err = e
        raise SourceError(f"{name}: {err}")


# ---------------------------------------------------------------- geocode
def geocode(address, fresh=False):
    doc = _get("geocode", GEOSEARCH, {"text": address, "size": 1}, fresh)
    feats = doc.get("features") or []
    if not feats:
        raise SourceError(f"geocode: no match for {address!r}")
    f = feats[0]
    lng, lat = f["geometry"]["coordinates"]
    p = f["properties"]
    pad = (p.get("addendum") or {}).get("pad") or {}
    return {
        "query": address,
        "label": p.get("label"),
        "lat": lat,
        "lng": lng,
        "bbl": pad.get("bbl") or p.get("pad_bbl"),
        "bin": pad.get("bin") or p.get("pad_bin"),
        "borough": p.get("borough"),
    }


# ---------------------------------------------------------------- building
def pluto(bbl, fresh=False):
    if not bbl:
        return None
    rows = _get("pluto", DATASETS["pluto"], {
        "bbl": bbl,
        "$select": "address,borough,yearbuilt,yearalter1,yearalter2,numfloors,bldgclass,unitsres,unitstotal,landuse,lotfront,bldgdepth,zonedist1",
    }, fresh)
    return rows[0] if rows else None


def dob_permits(borough, block, since_iso, fresh=False):
    """Approved permits on the same tax block since `since_iso`. DOB NOW stores the block without leading zeros."""
    if not borough or not block:
        return []
    block = block.lstrip("0") or "0"
    return _get("permits", DATASETS["permits"], {
        "$select": "work_type,work_permit,job_description,approved_date,issued_date,expired_date,estimated_job_costs,house_no,street_name,bin",
        "$where": f"borough='{borough.upper()}' AND block='{block}' AND issued_date > '{since_iso}'",
        "$limit": 500,
    }, fresh)


# ---------------------------------------------------------------- around the point
def complaints_311(lat, lng, radius_m, since_iso, fresh=False):
    return _get("311", DATASETS["311"], {
        "$select": "unique_key,complaint_type,descriptor,created_date,latitude,longitude,bbl,incident_address",
        "$where": f"within_circle(location,{lat},{lng},{radius_m}) AND complaint_type like 'Noise%' AND created_date > '{since_iso}'",
        "$limit": 20000,
    }, fresh)


def liquor(lat, lng, radius_m, fresh=False):
    return _get("liquor", DATASETS["liquor"], {
        "$select": "legalname,description,type,class,actualaddressofpremises,georeference",
        "$where": f"within_circle(georeference,{lat},{lng},{radius_m})",
        "$limit": 500,
    }, fresh)


def roads(lat, lng, radius_m, fresh=False):
    """Socrata's within_circle on a line matches its vertices, not the line, so ask wide and let the model
    measure the true distance to each segment (NYC block faces run up to ~270 m)."""
    radius_m = max(radius_m, config.ROADS_QUERY_RADIUS_M)
    return _get("roads", DATASETS["roads"], {
        "$select": "full_street_name,rw_type,streetwidth,trafdir,number_total_lanes,number_travel_lanes,posted_speed,snow_priority,status,the_geom",
        "$where": f"within_circle(the_geom,{lat},{lng},{radius_m})",
        "$limit": 500,
    }, fresh)


def rail_stations(lat, lng, radius_m, fresh=False):
    return _get("stations", DATASETS["stations"], {
        "$select": "stop_name,daytime_routes,structure,gtfs_latitude,gtfs_longitude",
        "$where": f"within_circle(georeference,{lat},{lng},{radius_m})",
        "$limit": 50,
    }, fresh)


def facilities(lat, lng, radius_m, fresh=False):
    """Hospitals, firehouses, ambulance stations and police stations within `radius_m`. [M11]

    FacDB's `within_circle` on `the_geom` returns nothing, so the pull is citywide (about 400 rows, one cache
    entry shared by every address: the key has no lat/lng) and the radius is applied by haversine here.
    Rows with no coordinates are dropped."""
    rows = _get("facilities", DATASETS["facilities"], {
        "$select": "facname,factype,address,latitude,longitude",
        "$where": "factype in('HOSPITAL','ACUTE CARE HOSPITAL','FIREHOUSE','AMBULANCE STATION','POLICE STATION')",
        "$limit": 2000,
    }, fresh)
    out = []
    for r in rows:
        kind = config.SIRENS_KINDS.get(r.get("factype"))
        try:
            la, ln = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not kind or haversine_m(lat, lng, la, ln) > radius_m:
            continue
        out.append({"name": r.get("facname"), "kind": kind, "address": r.get("address"), "latitude": la, "longitude": ln})
    return out


# ---------------------------------------------------------------- everything for one address
def pull_all(address, fresh=False, today=None):
    return pull_at(geocode(address, fresh), fresh=fresh, today=today)


def pull_at(a, fresh=False, today=None, pluto_row=None):
    """Every pull for an already-located address dict (lat, lng, bbl, borough). The Manhattan baseline [M12]
    calls this directly with PLUTO's own coordinates, so no geocode and, when given, no PLUTO pull."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=30 * config.LOOKBACK_MONTHS)).isoformat()
    permits_since = (today - dt.timedelta(days=30 * config.CONSTRUCTION_PERMIT_LOOKBACK_MONTHS)).isoformat()
    lat, lng = a["lat"], a["lng"]
    radius = max(config.RADIUS_BLOCK_M, config.RADIUS_NIGHTLIFE_M)
    block = a["bbl"][1:6] if a.get("bbl") and len(a["bbl"]) == 10 else None
    return {
        "address": a,
        "as_of": today.isoformat(),
        "lookback_months": config.LOOKBACK_MONTHS,
        "since": since,
        "pluto": pluto_row if pluto_row is not None else pluto(a.get("bbl"), fresh),
        "complaints": complaints_311(lat, lng, radius, since, fresh),
        "liquor": liquor(lat, lng, config.RADIUS_NIGHTLIFE_M, fresh),
        "roads": roads(lat, lng, config.RADIUS_ROADS_M, fresh),
        "stations": rail_stations(lat, lng, config.RADIUS_RAIL_M, fresh),
        "permits": dob_permits(a.get("borough"), block, permits_since, fresh),
        "facilities": facilities(lat, lng, config.RADIUS_SIRENS_M, fresh),
        "sources": [
            {"name": "NYC GeoSearch (address, BBL, BIN)", "url": GEOSEARCH},
            {"name": "NYC 311 Service Requests", "url": DATASETS["311"]},
            {"name": "NYC PLUTO (year built, floors, units, class)", "url": DATASETS["pluto"]},
            {"name": "NYC Street Centerline (road class, lanes, speed)", "url": DATASETS["roads"]},
            {"name": "DOB NOW approved permits (same tax block)", "url": DATASETS["permits"]},
            {"name": "NYS Liquor Authority active licenses", "url": DATASETS["liquor"]},
            {"name": "MTA subway stations (elevated structures)", "url": DATASETS["stations"]},
            {"name": "NYC Facilities Database (hospitals, firehouses, police)", "url": DATASETS["facilities"]},
        ],
    }
