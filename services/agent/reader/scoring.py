"""After the reading: place the address with NYC GeoSearch, then score it with the Hush IQ API.

The score comes from the hosted API (or a local packages/model server, HUSH_SCORE_URL): engine v2 at /v2/score,
falling back to v1 at /v1/score while v2 is not deployed. Injectable, so tests never touch the network.
"""
import re

import httpx

from . import settings

GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
HEADERS = {"User-Agent": "hush-iq-reader/0.1 (https://github.com/rafael-sanchezf/hush-iq)"}   # on every request
TIMEOUT_S = 60        # a cold score pulls eight datasets: 6 to 8 s, more on a bad day


CANDIDATES = 10       # the same house number shows up in other boroughs and on other streets in the top few
DEFAULT_BOROUGH = "Manhattan"

# Listing words that name a borough. Explicit borough names first, then ZIP codes after NY, then neighborhoods.
NEIGHBORHOODS = {
    "Manhattan": ["Upper East Side", "Upper West Side", "Lower East Side", "East Village", "West Village",
                  "Greenwich Village", "Chelsea", "Kips Bay", "Murray Hill", "Gramercy", "Flatiron", "Midtown",
                  "Hell's Kitchen", "Hells Kitchen", "Clinton", "SoHo", "NoHo", "Nolita", "Tribeca", "Chinatown",
                  "Financial District", "FiDi", "Battery Park City", "Harlem", "East Harlem", "Morningside Heights",
                  "Hamilton Heights", "Washington Heights", "Inwood", "Yorkville", "Lenox Hill", "Carnegie Hill",
                  "Lincoln Square", "Stuyvesant Town", "Alphabet City", "Two Bridges", "Sutton Place", "Tudor City",
                  "NoMad", "Hudson Yards", "Roosevelt Island"],
    "Brooklyn": ["Williamsburg", "Greenpoint", "Bushwick", "Bedford-Stuyvesant", "Bed-Stuy", "Park Slope",
                 "Prospect Heights", "Crown Heights", "Flatbush", "Canarsie", "DUMBO", "Brooklyn Heights",
                 "Cobble Hill", "Carroll Gardens", "Boerum Hill", "Fort Greene", "Clinton Hill", "Bay Ridge",
                 "Sunset Park", "Red Hook", "Gowanus", "Bensonhurst", "Sheepshead Bay", "Brighton Beach",
                 "Coney Island", "Ditmas Park", "Windsor Terrace", "Kensington", "East New York", "Brownsville"],
    "Queens": ["Astoria", "Long Island City", "Sunnyside", "Woodside", "Jackson Heights", "Elmhurst", "Flushing",
               "Forest Hills", "Rego Park", "Ridgewood", "Bayside", "Jamaica", "Rockaway", "Kew Gardens"],
    "Bronx": ["Riverdale", "Mott Haven", "Fordham", "Pelham Bay", "Kingsbridge", "Concourse", "Throgs Neck"],
    "Staten Island": ["St. George", "Tottenville", "Great Kills"],
}
_ZIP = [("Manhattan", r"10[0-2]\d\d"), ("Staten Island", r"103\d\d"), ("Bronx", r"104\d\d"),
        ("Brooklyn", r"112\d\d"), ("Queens", r"11[01]\d\d|11[3-6]\d\d")]


class ScoreError(RuntimeError):
    pass


def borough_hint(text):
    """{"how": "text", "borough", "said"} from the first word in the listing that names a borough, else None."""
    text = text or ""
    for borough in ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"):
        m = re.search(rf"\b{borough}\b", text, re.I)
        if m:
            return {"how": "text", "borough": borough, "said": m.group(0)}
    for borough, pattern in _ZIP:
        m = re.search(rf"\b(?:NY|New York)\s*,?\s*({pattern})\b", text)
        if m:
            return {"how": "text", "borough": borough, "said": m.group(1)}
    for borough, names in NEIGHBORHOODS.items():
        for name in names:
            m = re.search(rf"\b{re.escape(name)}\b", text, re.I)
            if m:
                return {"how": "text", "borough": borough, "said": m.group(0)}
    return None


_STREET_WORDS = {"E": "EAST", "W": "WEST", "N": "NORTH", "S": "SOUTH", "ST": "STREET", "AVE": "AVENUE", "AV": "AVENUE",
                 "PL": "PLACE", "RD": "ROAD", "BLVD": "BOULEVARD", "DR": "DRIVE", "LN": "LANE", "SQ": "SQUARE",
                 "TER": "TERRACE", "PKWY": "PARKWAY", "B'WAY": "BROADWAY", "BWAY": "BROADWAY"}


def street_key(address):
    """The street of an address, comparable with GeoSearch's: no house number, no ordinal suffix, words spelled
    out. "315 W. 86th St." and "WEST 86 STREET" give the same key."""
    words = re.findall(r"[A-Za-z0-9']+", re.sub(r"^\s*\d+(?:-\d+)?[A-Za-z]?\b", "", address or "").upper())
    words = [_STREET_WORDS.get(w, w) for w in words]
    return " ".join(re.sub(r"(?<=\d)(ST|ND|RD|TH)$", "", w) for w in words)


def house_number(address):
    m = re.match(r"\s*(\d+(?:-\d+)?[A-Za-z]?)\b", address or "")
    return m.group(1).upper() if m else None


class HostedScorer:
    def __init__(self, base_url=None, http=None):
        self.base_url = (base_url or settings.score_url()).rstrip("/")
        self.http = http or httpx.Client(timeout=TIMEOUT_S)

    def locate(self, address, text=""):
        """The building GeoSearch has at this house number on this street. The same address can exist in two
        boroughs (East 81st Street is in Manhattan and in Brooklyn): the listing's own borough, ZIP or
        neighborhood picks one, else Manhattan, the borough the score is ranked against, with the others listed."""
        house = house_number(address)
        if not house:
            raise ScoreError(f"{address!r} has no house number, so it cannot be placed on one building")
        try:
            r = self.http.get(GEOSEARCH, params={"text": address, "size": CANDIDATES}, headers=HEADERS)
            r.raise_for_status()
            feats = r.json().get("features") or []
        except (httpx.HTTPError, ValueError) as e:
            raise ScoreError(f"GeoSearch failed: {e}")
        street = street_key(address)
        same = [f for f in feats if str((f.get("properties") or {}).get("housenumber") or "").upper() == house
                and street_key(f["properties"].get("street") or "") == street]
        if not same:
            best = (feats[0].get("properties") or {}).get("label") if feats else None
            raise ScoreError(f"GeoSearch has no building at {address!r}" + (f"; its best match is {best!r}" if best else ""))
        boroughs = list(dict.fromkeys(f["properties"].get("borough") for f in same))
        if len(boroughs) == 1:
            chosen, how = same[0], {"how": "only match"}
        else:
            hint = borough_hint(text)
            pick = hint["borough"] if hint and hint["borough"] in boroughs else DEFAULT_BOROUGH
            how = hint if hint and hint["borough"] in boroughs else {"how": "default", "borough": DEFAULT_BOROUGH}
            chosen = next((f for f in same if f["properties"].get("borough") == pick), same[0])
        p = chosen["properties"]
        lng, lat = chosen["geometry"]["coordinates"]
        pad = (p.get("addendum") or {}).get("pad") or {}
        return {"label": p.get("label"), "lat": lat, "lng": lng, "bbl": pad.get("bbl"), "bin": pad.get("bin"),
                "borough": p.get("borough"), "borough_from": how,
                "alternatives": [f["properties"].get("label") for f in same if f is not chosen]}

    def floors(self, bbl):
        """The building's floor count as the score engine counts it (whole floors of PLUTO numfloors), or None."""
        if not bbl:
            return None
        try:
            r = self.http.get(PLUTO, params={"bbl": bbl, "$select": "numfloors"}, headers=HEADERS)
            r.raise_for_status()
            rows = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ScoreError(f"PLUTO failed: {e}")
        try:
            return int(float(rows[0]["numfloors"])) or None
        except (IndexError, KeyError, TypeError, ValueError):
            return None

    def score(self, address, floor, position, answers):
        """{"engine": "v2"|"v1", "url", "body"}. v1 has no sleep hours: day_bothers goes in as wfh."""
        a = answers
        v2 = {"address": address, "position": position, "sleep_from": a.sleep_from, "sleep_until": a.sleep_until,
              "day_bothers": str(a.day_bothers).lower(), "bothers": ",".join(a.bothers)}
        v1 = {"address": address, "position": position, "wfh": str(a.day_bothers).lower(),
              "bothers": ",".join(a.bothers)}
        if floor is not None:
            v2["floor"] = v1["floor"] = floor
        r = self._get("/v2/score", v2)
        engine = "v2"
        if r.status_code == 404:
            r, engine = self._get("/v1/score", v1), "v1"
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            raise ScoreError(f"{engine} score failed, HTTP {r.status_code}: {detail}")
        return {"engine": engine, "url": str(r.request.url), "body": r.json()}

    def _get(self, path, params):
        try:
            return self.http.get(self.base_url + path, params={k: v for k, v in params.items() if v != ""},
                                 headers=HEADERS)
        except httpx.HTTPError as e:
            raise ScoreError(f"the score API did not answer: {e}")
