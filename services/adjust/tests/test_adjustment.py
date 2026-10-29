"""The adjustment object on its own: submit_adjustment's refusals and apply()."""
import pytest

from adjust import config as A
from adjust.adjustment import Refused, apply, submit_adjustment

SENT = {"P1", "P2"}
GOOD = {"source": "construction", "direction": "louder", "size": 1, "cites": ["P1"], "reason": "A facade job."}


def test_good_adjustment_is_normalised():
    assert submit_adjustment({**GOOD, "reason": "  A facade job. "}, SENT) == {**GOOD, "cap": A.CAPS["construction"]}


def test_over_cap_refused():
    with pytest.raises(Refused, match="size 3 exceeds the construction cap of 2"):
        submit_adjustment({**GOOD, "size": 3}, SENT)


def test_citation_not_in_the_pull_refused():
    with pytest.raises(Refused, match="cites P9, which is not among the rows sent"):
        submit_adjustment({**GOOD, "cites": ["P1", "P9"]}, SENT)


@pytest.mark.parametrize("change, why", [
    ({"source": "building"}, "no adjustment for the building source is allowed yet"),
    ({"source": "weather"}, "source 'weather' is not one of"),
    ({"cap": 5}, "the construction cap is 2; it is set in config"),
    ({"direction": "up"}, "direction 'up' is not one of"),
    ({"size": 0}, "not a whole number of steps of at least 1"),
    ({"size": 1.5}, "not a whole number"),
    ({"size": True}, "not a whole number"),
    ({"cites": []}, "cites must list at least one row id"),
    ({"cites": ["P1", "P1"]}, "cites repeats a row id"),
    ({"reason": " "}, "reason is required"),
    ({"reason": "x" * (A.MAX_REASON_CHARS + 1)}, "reason is over"),
])
def test_each_refusal(change, why):
    with pytest.raises(Refused, match=why):
        submit_adjustment({**GOOD, **change}, SENT)


def test_bound_and_reading_checks():
    with pytest.raises(Refused, match="cites P2, which has no accepted reading"):
        submit_adjustment({**GOOD, "cites": ["P2"]}, SENT, read={"P1": {}})
    with pytest.raises(Refused, match="support at most 1 step louder, not 2"):
        submit_adjustment({**GOOD, "size": 2}, SENT, bound=lambda d, c: 1)
    with pytest.raises(Refused, match="none of the cited rows points louder"):
        submit_adjustment(GOOD, SENT, bound=lambda d, c: 0)


NEUTRAL = {"construction": {"night": 40.0, "early": 52.0, "day": 55.0}, "street": {"night": 60.0, "early": 62.0, "day": 65.0}}


def test_apply_moves_only_the_source_in_steps():
    out = apply(NEUTRAL, [{**GOOD, "size": 2}])
    step = A.STEP_LEVEL["construction"]
    assert out["construction"] == {"night": 40 + 2 * step, "early": 52 + 2 * step, "day": 55 + 2 * step}
    assert out["street"] == NEUTRAL["street"]
    assert NEUTRAL["construction"]["day"] == 55.0   # the input is untouched
    assert apply(NEUTRAL, [None]) == NEUTRAL


def test_quieter_never_below_an_empty_block():
    floor = A.LEVEL_FLOOR["construction"]
    near_empty = {"construction": {w: floor[w] + 1 for w in floor}}
    out = apply(near_empty, [{**GOOD, "direction": "quieter", "size": 2}])
    assert out["construction"] == floor


def test_apply_refuses_a_hand_built_adjustment_over_cap():
    with pytest.raises(Refused, match="outside its cap"):
        apply(NEUTRAL, [{**GOOD, "size": 9}])
