"""The score API's input guards (HIQ-116, HIQ-137) and the outside-Manhattan flag (HIQ-138). No network: GeoSearch
and the pulls are stood in for. The labels are GeoSearch's own answers to these queries, Nov 4."""
import pytest
from fastapi.testclient import TestClient

from noise_score import api, sources, v2

from test_baseline import busy_inputs

LABELS = {
    "140 Claremont Ave, New York": "140 CLAREMONT AVENUE, New York, NY, USA",
    "310 W. 47th St., Manhattan": "310 WEST 47 STREET, New York, NY, USA",
    "350 Fifth Ave": "350 5 AVENUE, New York, NY, USA",
    "158 Bedford Ave Brooklyn NY": "158 BEDFORD AVENUE, Brooklyn, NY, USA",
    "140 CLAREMONT AVENUE, New York, NY, USA": "140 CLAREMONT AVENUE, New York, NY, USA",
    "1600 Pennsylvania Ave Washington DC": "218 PENNSYLVANIA AVENUE, Brooklyn, NY, USA",
    "99999 Broadway": "99999 SPRINGFIELD AVENUE, Cambria Heights, NY, USA",
    "37-12 80th St, Queens": "37 80 STREET, Brooklyn, NY, USA",
    "1 Centre St": "JAMAICA 1 PREK CENTER, Jamaica, NY, USA",
}
LABELS["1 Centre Street, Manhattan"] = "1 CENTER STREET, New York, NY, USA"
LABELS["158 Bedford Ave, Manhattan"] = "158 BEDFORD AVENUE, Brooklyn, NY, USA"
# GeoSearch's ten candidates, trimmed to the ones that matter
CANDIDATES = {
    "1 Centre St": [("JAMAICA 1 PREK CENTER, Jamaica, NY, USA", "Queens"), ("1 CENTER STREET, Bronx, NY, USA", "Bronx"),
                    ("1 CENTRE STREET, Bronx, NY, USA", "Bronx"), ("1 CENTRE STREET, New York, NY, USA", "Manhattan")],
    "1 Centre Street, Manhattan": [("1 CENTER STREET, New York, NY, USA", "Manhattan"),
                                   ("1 CENTRE STREET, New York, NY, USA", "Manhattan"),
                                   ("1 CENTRE STREET, Bronx, NY, USA", "Bronx")],
    "158 Bedford Ave, Manhattan": [("158 BEDFORD AVENUE, Brooklyn, NY, USA", "Brooklyn")],
}
SAME = ["140 Claremont Ave, New York", "310 W. 47th St., Manhattan", "350 Fifth Ave", "158 Bedford Ave Brooklyn NY",
        "140 CLAREMONT AVENUE, New York, NY, USA"]
OTHER = ["1600 Pennsylvania Ave Washington DC", "99999 Broadway", "37-12 80th St, Queens", "1 Centre St"]


@pytest.mark.parametrize("query", SAME)
def test_the_same_building_matches(query):
    assert api.same_building(query, LABELS[query])


@pytest.mark.parametrize("query", OTHER)
def test_another_house_or_street_does_not(query):
    assert not api.same_building(query, LABELS[query])


@pytest.fixture
def client(monkeypatch):
    def geocode(address, fresh=False):
        if address == "zzzzqqq":
            raise sources.SourceError(f"geocode: no match for {address!r}")
        if address == "500 Down Street":
            raise sources.SourceError("geocode: Server error '503' for url 'https://geosearch.planninglabs.nyc/v2/search?text=x'")
        borough = "Brooklyn" if "Brooklyn" in LABELS.get(address, "") else "Manhattan"   # GeoSearch's borough field
        return {"query": address, "label": LABELS.get(address, address.upper() + ", New York, NY, USA"),
                "lat": 40.81, "lng": -73.96, "bbl": "1019930001", "bin": "1", "borough": borough}

    def pull_at(a, fresh=False, today=None, pluto_row=None):
        inputs = busy_inputs()
        inputs["address"] = a
        return inputs

    def candidates(address, fresh=False):
        return [{"query": address, "label": label, "lat": 40.7, "lng": -73.9, "bbl": "1001", "bin": "1", "borough": b}
                for label, b in CANDIDATES.get(address, [])]

    monkeypatch.setattr(sources, "geocode", geocode)
    monkeypatch.setattr(sources, "pull_at", pull_at)
    monkeypatch.setattr(api, "candidates", candidates)
    return TestClient(api.app)


@pytest.mark.parametrize("address", ["   ", "Claremont Ave", "zzzzqqq", "1600 Pennsylvania Ave Washington DC",
                                     "99999 Broadway"])
def test_a_bad_address_is_a_422_with_a_short_message(client, address):
    for path in ("/v2/score", "/v1/score", "/v1/raw"):
        r = client.get(path, params={"address": address})
        assert r.status_code == 422, (path, address)
        assert isinstance(r.json()["detail"], str) and len(r.json()["detail"]) < 160


def test_a_mismatch_names_the_closest_building(client):
    detail = client.get("/v2/score", params={"address": "99999 Broadway"}).json()["detail"]
    assert detail == "No exact match for that address. The closest is 99999 Springfield Avenue, Cambria Heights, NY."


def test_an_upstream_failure_names_the_dataset_never_its_url(client):
    r = client.get("/v2/score", params={"address": "500 Down Street"})
    assert r.status_code == 502
    assert "geocode" in r.json()["detail"] and "http" not in r.json()["detail"]


def test_an_exact_address_still_scores(client):
    r = client.get("/v2/score", params={"address": "140 Claremont Ave, New York", "bothers": "Traffic,sirens"})
    assert r.status_code == 200
    assert r.json()["engine"] == "v2" and r.json()["answers"]["ticks"] == ["traffic", "sirens"]
    assert client.get("/v1/score", params={"address": "140 Claremont Ave, New York"}).status_code == 200


def test_unknown_ticks_and_equal_sleep_hours_are_refused(client):
    r = client.get("/v2/score", params={"address": "140 Claremont Ave, New York", "bothers": "traffic,dogs"})
    assert r.status_code == 422
    assert "traffic, people, neighbors, sirens, construction" in r.json()["detail"] and "dogs" not in r.json()["detail"]
    r = client.get("/v2/score", params={"address": "140 Claremont Ave, New York", "sleep_from": 7, "sleep_until": 7})
    assert r.status_code == 422 and "same hour" in r.json()["detail"]


def test_outside_manhattan_scores_with_the_flag_and_caveat(client):
    body = client.get("/v2/score", params={"address": "158 Bedford Ave Brooklyn NY"}).json()
    assert body["coverage"] == {"borough": "Brooklyn", "outside_manhattan": True, "ranked_against": "Manhattan"}
    assert v2.OUTSIDE_MANHATTAN in body["caveats"]
    inside = client.get("/v2/score", params={"address": "140 Claremont Ave, New York"}).json()
    assert inside["coverage"]["outside_manhattan"] is False and v2.OUTSIDE_MANHATTAN not in inside["caveats"]



def test_a_better_candidate_is_found_and_two_boroughs_ask_for_one(client):
    r = client.get("/v2/score", params={"address": "1 Centre Street, Manhattan"})
    assert r.status_code == 200 and r.json()["address"]["label"] == "1 CENTRE STREET, New York, NY, USA"
    r = client.get("/v2/score", params={"address": "1 Centre St"})
    assert r.status_code == 422 and r.json()["detail"] == ("That address is in more than one borough. Add the borough, "
                                                           "like 1 Centre St, Manhattan.")


def test_a_named_borough_is_held_to(client):
    r = client.get("/v2/score", params={"address": "158 Bedford Ave, Manhattan"})
    assert r.status_code == 422 and "158 Bedford Avenue, Brooklyn" in r.json()["detail"]
