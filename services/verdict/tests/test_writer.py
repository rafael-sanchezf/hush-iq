"""The writer in mock mode: a scripted client stands in for Baseten and the Meta Model API."""
import httpx
import openai

from conftest import ids
from verdict import mock, writer

GOOD = {"sentences": [
    {"text": "For the way you sleep, this apartment is very loud: quieter than 5% of Manhattan apartments.",
     "cites": ["E1", "E29"]},
    {"text": "Nightlife is the reason: 311 logged 1,670 party, music or loud-talking complaints within 150 m in "
             "24 months, 916 of them between 10 pm and 5 am.", "cites": ["E3", "E8"]},
    {"text": "The listing gives no floor or side, so this assumes floor 4.", "cites": ["E32", "E33"]},
]}


def _bad(text, cites=("E1",)):
    return {"sentences": [{"text": text, "cites": list(cites)}]}


def test_a_valid_reply_is_used_as_is(lines, backend):
    ls, b = lines("ludlow"), backend(GOOD)
    out = writer.write(ls, b)
    assert out["writer"] == "muse-spark-open"
    assert out["sentences"] == GOOD["sentences"]
    assert [t["ok"] for t in out["trace"]] == [True]
    call = b.client.calls[0]
    assert call["model"] == "meta-models/muse-spark-open-1026"
    assert call["tool_choice"] == {"type": "function", "function": {"name": "submit_verdict"}}
    enum = call["tools"][0]["function"]["parameters"]["properties"]["sentences"]["items"]["properties"]["cites"]["items"]["enum"]
    assert enum == [l.id for l in ls]
    assert "E8: Nightlife: 1670 party" in call["messages"][1]["content"]


def test_an_invented_citation_is_retried_with_the_error_then_accepted(lines, backend):
    ls, b = lines("ludlow"), backend(_bad("It is very loud here.", ["E1", "E41"]), GOOD)
    out = writer.write(ls, b)
    assert out["writer"] == "muse-spark-open" and out["sentences"] == GOOD["sentences"]
    assert out["trace"][0]["errors"] == ["sentence 1: cites E41, not in the evidence"]
    retry = b.client.calls[1]["messages"][-1]["content"]
    assert "cites E41, not in the evidence" in retry and '"E41"' in retry


def test_an_invented_citation_twice_falls_back_to_the_template(lines, backend):
    ls, b = lines("ludlow"), backend(_bad("It is very loud.", ["E77"]), _bad("It is very loud.", ["E78"]))
    out = writer.write(ls, b)
    assert out["writer"] == "template"
    assert len(b.client.calls) == 2
    assert [t.get("attempt") for t in out["trace"]] == [1, 2, None]
    assert out["sentences"][0]["text"].startswith("For the way you sleep, this apartment is very loud")


def test_a_decibel_leak_never_reaches_the_renter(lines, backend):
    leak = _bad("Expect around 68 dB at night from the bars.", ["E1", "E5"])
    out = writer.write(lines("ludlow"), backend(leak, leak))
    assert out["writer"] == "template"
    assert any("decibel" in e for e in out["trace"][0]["errors"])
    assert not any("dB" in s["text"] for s in out["sentences"])


def test_a_number_not_in_evidence_is_retried(lines, backend):
    made_up = _bad("Roughly 40 bars sit within a block.", ["E5"])
    out = writer.write(lines("ludlow"), backend(made_up, GOOD))
    assert out["writer"] == "muse-spark-open"
    assert out["trace"][0]["errors"] == ["sentence 1: the number 40 is not in the lines it cites (E5)"]


def test_malformed_json_is_retried(lines, backend):
    out = writer.write(lines("ludlow"), backend('{"sentences": [{"text": "Very loud", "cites": ["E1"]', GOOD))
    assert out["writer"] == "muse-spark-open"
    assert out["trace"][0]["errors"][0].startswith("the reply is not valid JSON")


def test_a_timeout_falls_back_to_the_template_without_a_second_call(lines, backend):
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://inference.baseten.co/v1/chat/completions"))
    ls, b = lines("ludlow"), backend(timeout)
    out = writer.write(ls, b)
    assert out["writer"] == "template"
    assert len(b.client.calls) == 1
    assert out["trace"][0]["errors"][0].startswith("APITimeoutError")
    assert out["trace"][-1] == {"writer": "template", "ok": True,
                                "why": "the model's reply did not pass the checks or did not arrive"}


def test_a_silent_listing_keeps_its_range(lines, backend):
    ls = lines("ludlow")
    loud, quiet = ids(ls, "range")
    reply = {"sentences": GOOD["sentences"] + [
        {"text": "Depending on the unit, it runs from very loud on floor 2 facing the street to loud on floor 5 at "
                 "the rear, quieter than 36% of Manhattan apartments.", "cites": [loud, quiet]}]}
    out = writer.write(ls, backend(reply))
    assert out["writer"] == "muse-spark-open" and out["sentences"][-1]["cites"] == [loud, quiet]
    # and the template, with no model, says the same range
    fallback = writer.write(ls, None)
    assert fallback["writer"] == "template"
    assert any(s["cites"] == [loud, quiet] for s in fallback["sentences"])


def test_muse_spark_13_uses_a_strict_json_schema(lines, backend):
    ls, b = lines("ludlow"), backend(GOOD, mode="json_schema")
    out = writer.write(ls, b)
    assert out["writer"] == "muse-spark-1.3"
    call = b.client.calls[0]
    assert call["model"] == "muse-spark-1.3" and "tools" not in call
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True


def test_a_reply_in_the_content_instead_of_the_tool_call_is_still_checked(lines, backend):
    import json
    out = writer.write(lines("ludlow"), backend({"_content_only": True, "content": json.dumps(GOOD)}))
    assert out["writer"] == "muse-spark-open"


def test_no_key_means_the_template(lines):
    assert writer.from_env({}) is None
    assert writer.from_env({"BASETEN_API_KEY": "x", "VERDICT_BACKEND": "template"}) is None
    assert writer.from_env({"BASETEN_API_KEY": "x"}).name == "muse-spark-open"
    assert writer.from_env({"MODEL_API_KEY": "x"}).name == "muse-spark-1.3"
    both = {"BASETEN_API_KEY": "x", "MODEL_API_KEY": "y"}
    assert writer.from_env(both).name == "muse-spark-open"
    assert writer.from_env({**both, "VERDICT_BACKEND": "muse-spark-1.3"}).name == "muse-spark-1.3"
    assert writer.from_env({"VERDICT_BACKEND": "muse-spark-1.3"}) is None   # chosen, but no key
    out = writer.write(lines("claremont"), None)
    assert out["writer"] == "template" and out["trace"] == [{"writer": "template", "ok": True, "why": "no model configured"}]


def test_the_one_call_entry_the_eval_uses(lines):
    import verdict
    from conftest import FIELDS, load
    out = verdict.write(score=load("ludlow"), answers=None, fields=FIELDS["ludlow"], client=mock.ScriptedClient(GOOD))
    assert out["writer"] == "muse-spark-open" and out["sentences"] == GOOD["sentences"]
    assert [e["id"] for e in out["evidence"]] == [l.id for l in lines("ludlow")]
    assert writer.TOOL_NAME.startswith("submit")   # the eval's scripted client answers the first submit_* tool
    assert verdict.write(score=load("ludlow"), writer_choice="template")["writer"] == "template"
