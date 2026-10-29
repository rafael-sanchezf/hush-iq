"""The checks in evidence.py, one rule at a time."""
import pytest

from conftest import fixture_text
from reader import evidence
from reader.evidence import Refused, check_field, find_quote, position, stated

TEXT = fixture_text("01-stated-rear.txt")


def test_quotes_match_with_whitespace_normalized_only():
    span = find_quote("The bedroom and the living room face the rear", TEXT)    # the text breaks after "The"
    assert span and TEXT[span[0]:span[1]] == "The\nbedroom and the living room face the rear"
    assert find_quote("  eleventh   floor ", TEXT)
    assert find_quote("the Rear of the building", TEXT) is None                 # case is not normalized
    assert find_quote("eleventh-floor", TEXT) is None                           # nor punctuation
    assert find_quote("on", TEXT) is None                                       # too short to mean anything


@pytest.mark.parametrize("floor, quote", [
    (11, "on the eleventh floor"), (11, "11th floor"), (11, "11th-floor unit"), (4, "Floor 4"),
    (4, "fourth-floor walk-up"), (5, "top floor of a five-story walk-up"), (24, "twenty-fourth floor"),
    (1, "ground floor"), (2, "2nd fl"),
])
def test_floor_stated(floor, quote):
    assert stated("floor", floor, quote) is None


@pytest.mark.parametrize("floor, quote", [
    (3, "Apt 3F"), (3, "Unit 3F in a five-story walk-up"), (11, "an 11 floors elevator building"),
    (4, "fourteenth floor"), (5, "a five-story walk-up"), (11, "Apartment 11C"),
])
def test_floor_not_stated(floor, quote):
    assert stated("floor", floor, quote)


@pytest.mark.parametrize("side, quote", [
    ("rear", "face the rear of the building"), ("rear", "rear unit"), ("courtyard", "overlooks the interior courtyard"),
    ("corner", "Corner unit on the 14th floor"), ("corner", "a corner two-bedroom"),
    ("street", "Both bedrooms face Ludlow Street"), ("street", "windows on Second Avenue"),
    ("street", "street-facing living room"),
])
def test_side_stated(side, quote):
    assert stated("side", side, quote) is None


@pytest.mark.parametrize("side, quote", [
    ("corner", "Laundromat on the corner"), ("corner", "on the corner of 24th and Second"),
    ("street", "155 Ludlow Street"), ("rear", "Quiet, sun-drenched one-bedroom"), ("rear", "the street"),
])
def test_side_not_stated(side, quote):
    assert stated("side", side, quote)


def test_adjectives_get_their_own_refusal():
    assert stated("side", "rear", "A peaceful, serene home").startswith("adjectives are not evidence (peaceful, serene)")


def test_address_and_unit_must_be_in_the_quote():
    assert stated("address", "315 West 86th Street", "315 West 86th Street, Apartment 11C") is None
    assert stated("address", "315 West 86th Street", "315 W. 86th St.") is None
    assert stated("address", "315 West 86th Street", "West 86th Street")          # no house number
    assert stated("address", "315 West 87th Street", "315 West 86th Street")      # the model's own street
    assert stated("unit", "11C", "Apartment 11C") is None
    assert stated("unit", "#2A", "Unit 2A") is None
    assert stated("unit", "11", "Apartment 11C")


def test_side_maps_to_the_engines_position():
    side = lambda v: {"status": "read", "value": v}     # noqa: E731
    assert [position(side(v)) for v in ("street", "corner", "rear", "courtyard")] == ["front", "front", "rear", "rear"]
    assert position(evidence.cant_tell("side")) == "unknown"


def test_check_field_refusals():
    with pytest.raises(Refused, match="no evidence"):
        check_field("floor", {"status": "read", "value": 11, "evidence": []}, TEXT, {}, 0)
    with pytest.raises(Refused, match="source must be"):
        check_field("floor", {"status": "read", "value": 11, "evidence": [{"source": "listing", "quote": "x"}]},
                    TEXT, {}, 0)
    with pytest.raises(Refused, match="between 1 and 120"):
        check_field("floor", {"status": "read", "value": 0, "evidence": []}, TEXT, {}, 0)
    with pytest.raises(Refused, match="photo 0 does not exist; this listing has 0 photo"):
        check_field("side", {"status": "read", "value": "rear", "evidence": [{"source": "photo:0"}]}, TEXT, {}, 0)
    with pytest.raises(Refused, match="read from photos only"):
        check_field("view", {"status": "read", "value": "street", "evidence": [{"source": "text", "quote": "315 West"}]},
                    TEXT, {}, 0)
    with pytest.raises(Refused, match="status must be read or cant_tell"):
        check_field("unit", {"status": "maybe"}, TEXT, {}, 0)


def test_a_photo_citation_takes_the_readings_description():
    reading = {"fields": {"side": {"status": "read", "value": "street", "what": "cars parked on the street below"}}}
    field = check_field("side", {"status": "read", "value": "street",
                                 "evidence": [{"source": "photo:0", "what": "a very quiet street"}]},
                        "", {0: reading}, 1)
    assert field["evidence"] == [{"source": "photo:0", "what": "cars parked on the street below"}]
