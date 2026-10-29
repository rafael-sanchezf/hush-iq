import pytest

from conftest import SCORES, ids
from verdict import template, validate


def test_a_grounded_reply_passes(lines):
    ls = lines("ludlow")
    reply = {"sentences": [
        {"text": "For the way you sleep, this apartment is very loud: quieter than 5% of Manhattan apartments.",
         "cites": ["E1", "E29"]},
        {"text": "Nightlife counts for 35% of the verdict because you said it bothers you, and 311 logged 1,670 "
                 "party, music or loud-talking complaints within 150 m in 24 months, 916 of them between 10 pm and 5 am.",
         "cites": ["E4", "E8"]},
        {"text": "The nearest bar is at 152 Ludlow Street, 15 m away.", "cites": ["E6"]},
        {"text": "The listing gives no floor, so this assumes floor 4; the side is unknown.", "cites": ["E32", "E33"]},
    ]}
    assert validate.check(reply, ls) == []


def test_every_sentence_cites_and_every_id_exists(lines):
    ls = lines("ludlow")
    errs = validate.check({"sentences": [{"text": "It is very loud here.", "cites": []},
                                         {"text": "It is very loud here.", "cites": ["E1", "E99"]}]}, ls)
    assert errs == ["sentence 1: must cite at least one evidence id", "sentence 2: cites E99, not in the evidence"]


def test_a_decibel_never_passes(lines):
    ls = lines("ludlow")
    for text in ("Expect about 70 dB at night.", "Nights reach 65dBA.", "It runs a few decibels louder."):
        errs = validate.check({"sentences": [{"text": text, "cites": ["E1"]}]}, ls)
        assert any("decibel" in e for e in errs), text


def test_numbers_must_be_in_the_cited_lines(lines):
    ls = lines("ludlow")
    # 95 is nowhere in the evidence
    errs = validate.check({"sentences": [{"text": "It is louder than 95% of Manhattan apartments.", "cites": ["E1"]}]}, ls)
    assert errs == ["sentence 1: the number 95 is not in the lines it cites (E1)"]
    # 916 is in the evidence, but not in the line this sentence cites
    errs = validate.check({"sentences": [{"text": "916 complaints came at night.", "cites": ["E1"]}]}, ls)
    assert errs == ["sentence 1: the number 916 is not in the lines it cites (E1)"]
    # words and ordinals count as numbers too
    errs = validate.check({"sentences": [{"text": "This assumes the seventh floor.", "cites": ["E32"]}]}, ls)
    assert errs == ["sentence 1: the number 7 is not in the lines it cites (E32)"]
    assert validate.check({"sentences": [{"text": "This assumes the fourth floor.", "cites": ["E32"]}]}, ls) == []


def test_names_must_be_in_the_cited_lines(lines):
    ls = lines("ludlow")
    errs = validate.check({"sentences": [{"text": "Broadway traffic is loud here.", "cites": ["E9"]}]}, ls)
    assert errs == ["sentence 1: 'Broadway' is not in the lines it cites (E9)"]
    # "Ludlow Street" matches "Ludlow St"
    assert validate.check({"sentences": [{"text": "The nearest road is Ludlow Street, 14 m away.", "cites": ["E11"]}]}, ls) == []


def test_kinds_of_source_must_be_in_the_cited_lines(lines):
    ls = lines("ludlow")
    errs = validate.check({"sentences": [{"text": "The elevated subway is the worst of it.", "cites": ["E9"]}]}, ls)
    assert errs == ['sentence 1: mentions "elevated", but no line it cites does (E9)']
    errs = validate.check({"sentences": [{"text": "A school lets out next door.", "cites": ["E1"]}]}, ls)
    assert errs == ['sentence 1: mentions "school", but no line it cites does (E1)']
    assert validate.check({"sentences": [{"text": "Bars are the loudest thing here.", "cites": ["E5"]}]}, ls) == []
    assert validate.check({"sentences": [{"text": "Bar crowds fill the block.", "cites": ["E5"]}]}, ls) == []


def test_ids_stay_out_of_the_text(lines):
    errs = validate.check({"sentences": [{"text": "It is very loud (E1).", "cites": ["E1"]}]}, lines("ludlow"))
    assert errs == ["sentence 1: puts an evidence id in the text; ids go in cites only"]


def test_malformed_json_is_an_error_not_a_crash():
    reply, errs = validate.parse('{"sentences": [{"text": "Quiet", "cites": ["E1"]')
    assert reply is None and errs[0].startswith("the reply is not valid JSON")
    reply, errs = validate.parse('```json\n{"sentences": []}\n```')
    assert reply == {"sentences": []} and errs == []
    assert validate.check({"paragraph": "Quiet."}, []) == ["the reply must be an object with a sentences list"]


@pytest.mark.parametrize("name", list(SCORES))
def test_the_template_passes_the_same_checks(lines, name):
    answers = {"sleep_from": 23, "sleep_until": 7, "day_bothers": True, "bothers": ["sirens"]}
    ls = lines(name, answers)
    reply = template.write(ls)
    assert validate.check(reply, ls) == []
    assert 3 <= len(reply["sentences"]) <= validate.MAX_SENTENCES


def test_the_template_says_the_range_for_a_silent_listing(lines):
    ls = lines("ludlow")
    reply = template.write(ls)
    rng = [s for s in reply["sentences"] if set(s["cites"]) == set(ids(ls, "range"))]
    assert rng and rng[0]["text"] == ("Depending on the unit, it runs from very loud on floor 2 facing the street "
                                      "(among the loudest in Manhattan) to loud on floor 5 at the rear (36%).")
    floor = [s for s in reply["sentences"] if ids(ls, "floor")[0] in s["cites"]]
    assert "neither the floor nor the side" in floor[0]["text"]
