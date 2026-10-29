"""The hosted scorer, against a fake GeoSearch and a fake score API."""
import httpx
import pytest

from reader.listing import Answers
from reader.scoring import GEOSEARCH, HostedScorer, ScoreError

GEO = {"features": [{"geometry": {"coordinates": [-73.98, 40.79]},
                     "properties": {"label": "315 WEST 86 STREET, New York, NY, USA", "housenumber": "315",
                                    "borough": "Manhattan", "addendum": {"pad": {"bbl": "1012480022", "bin": "1033000"}}}}]}


def scorer(handler):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    s = HostedScorer(base_url="https://score.test", http=httpx.Client(transport=httpx.MockTransport(record)))
    return s, seen


def test_locate_takes_geosearchs_match_for_the_same_house_number():
    s, seen = scorer(lambda r: httpx.Response(200, json=GEO))
    loc = s.locate("315 West 86th Street")
    assert loc["label"] == "315 WEST 86 STREET, New York, NY, USA" and loc["bbl"] == "1012480022"
    assert str(seen[0].url).startswith(GEOSEARCH)
    assert seen[0].headers["user-agent"].startswith("hush-iq-reader/")     # the user agent names this repository


def test_locate_refuses_another_building_or_no_house_number():
    s, _ = scorer(lambda r: httpx.Response(200, json=GEO))
    with pytest.raises(ScoreError, match="best match is '315 WEST 86 STREET"):
        s.locate("317 West 86th Street")
    with pytest.raises(ScoreError, match="has no house number"):
        s.locate("Upper West Side")


def test_v2_first_with_the_renters_answers():
    s, seen = scorer(lambda r: httpx.Response(200, json={"engine": "v2", "verdict": "Quiet"}))
    out = s.score("315 WEST 86 STREET", 11, "rear", Answers(sleep_from=0, sleep_until=8, day_bothers=False,
                                                            bothers=["sirens", "people"]))
    q = dict(seen[0].url.params)
    assert seen[0].url.path == "/v2/score" and out["engine"] == "v2"
    assert q == {"address": "315 WEST 86 STREET", "position": "rear", "sleep_from": "0", "sleep_until": "8",
                 "day_bothers": "false", "bothers": "sirens,people", "floor": "11"}


def test_falls_back_to_v1_while_v2_is_not_deployed():
    def api(r):
        if r.url.path == "/v2/score":
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(200, json={"score": 61, "manhattan": {"verdict": "Typical"}})

    s, seen = scorer(api)
    out = s.score("315 WEST 86 STREET", None, "unknown", Answers())
    assert out["engine"] == "v1" and out["body"]["manhattan"]["verdict"] == "Typical"
    assert dict(seen[1].url.params) == {"address": "315 WEST 86 STREET", "position": "unknown", "wfh": "true"}


def test_a_score_error_is_a_score_error():
    s, _ = scorer(lambda r: httpx.Response(502, json={"detail": "311: timed out"}))
    with pytest.raises(ScoreError, match="v2 score failed, HTTP 502: 311: timed out"):
        s.score("315 WEST 86 STREET", 11, "rear", Answers())
