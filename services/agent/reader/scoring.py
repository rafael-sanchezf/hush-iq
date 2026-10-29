"""After the reading: place the address with NYC GeoSearch, then score it with the Hush IQ API.

The score comes from the hosted API (or a local packages/model server, HUSH_SCORE_URL): engine v2 at /v2/score,
falling back to v1 at /v1/score while v2 is not deployed. Injectable, so tests never touch the network.
"""
import re

import httpx

from . import settings

GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
HEADERS = {"User-Agent": "hush-iq-reader/0.1 (https://github.com/rafael-sanchezf/hush-iq)"}   # on every request
TIMEOUT_S = 60        # a cold score pulls eight datasets: 6 to 8 s, more on a bad day


class ScoreError(RuntimeError):
    pass


def house_number(address):
    m = re.match(r"\s*(\d+(?:-\d+)?[A-Za-z]?)\b", address or "")
    return m.group(1).upper() if m else None


class HostedScorer:
    def __init__(self, base_url=None, http=None):
        self.base_url = (base_url or settings.score_url()).rstrip("/")
        self.http = http or httpx.Client(timeout=TIMEOUT_S)

    def locate(self, address):
        """GeoSearch's best match, refused unless it is the listing's own house number."""
        house = house_number(address)
        if not house:
            raise ScoreError(f"{address!r} has no house number, so it cannot be placed on one building")
        try:
            r = self.http.get(GEOSEARCH, params={"text": address, "size": 1}, headers=HEADERS)
            r.raise_for_status()
            feats = r.json().get("features") or []
        except (httpx.HTTPError, ValueError) as e:
            raise ScoreError(f"GeoSearch failed: {e}")
        if not feats:
            raise ScoreError(f"GeoSearch found nothing for {address!r}")
        p = feats[0].get("properties") or {}
        if str(p.get("housenumber") or "").upper() != house:
            raise ScoreError(f"GeoSearch's best match is {p.get('label')!r}, not {address!r}")
        lng, lat = feats[0]["geometry"]["coordinates"]
        pad = (p.get("addendum") or {}).get("pad") or {}
        return {"label": p.get("label"), "lat": lat, "lng": lng, "bbl": pad.get("bbl"), "bin": pad.get("bin"),
                "borough": p.get("borough")}

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
