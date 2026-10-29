"""The listing reader: the agent loop. (Hackathon work, Oct 28.)

Each turn the model picks one tool (tools.py), the code runs it and sends the result back, and the turn joins
the trace with its tool, args, result and ms. The loop stops when submit_listing accepts, when the turns run
out, or when the Model API keeps failing; every way out gives a clean result: the fields the checks accepted,
cant_tell for the rest. Then the code, not the model, places the address and scores it.

read_listing() is a generator, so the app can stream each turn as it happens:

    for kind, data in read_listing(listing, client=client, scorer=scorer):
        ...   # ("turn", entry) for each turn, then ("result", result) once
"""
import json
import time
from pathlib import Path

import openai

from . import evidence, settings, tools
from .evidence import OBSERVED_FIELDS, SCORE_FIELDS
from .scoring import ScoreError

INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text()
LAST_TURN = ("This is your last turn. Call submit_listing now: keep every field you can support and mark the "
             "rest cant_tell.")
PLAIN_TEXT = "Plain text is not accepted. Call exactly one tool."
ONE_TOOL = "Not run: one tool per turn."


def first_message(listing):
    n = len(listing.photos)
    text = (f"LISTING TEXT (quote it exactly):\n<<<\n{listing.text}\n>>>" if listing.text
            else "LISTING TEXT: none. The renter sent photos only.")
    shown = (f"PHOTOS: {n}, indexes 0 to {n - 1}. Read them with read_photo before citing them." if n
             else "PHOTOS: none.")
    return f"Read this listing.\n\n{text}\n\n{shown}"


def read_listing(listing, *, client, scorer=None, model=None, turns=None, mode="live"):
    model = model or settings.model()
    turns = turns or settings.turns()
    record = tools.Record(listing)
    ctx = tools.Context(client, model, record)
    messages = [_user(first_message(listing))]
    trace, stopped, n = [], "budget", 0

    while n < turns:
        n += 1
        if n == turns:
            messages.append(_user(LAST_TURN))
        started = time.perf_counter()
        try:
            response = client.responses.create(model=model, instructions=INSTRUCTIONS, input=messages,
                                               tools=tools.DEFINITIONS, parallel_tool_calls=False, store=False)
        except openai.APIError as e:   # still failing after the SDK's own retries
            entry = {"n": n, "by": "model", "tool": None, "args": None,
                     "result": {"error": f"the Model API failed: {e}"}, "ok": False, "ms": _ms(started)}
            trace.append(entry)
            yield "turn", entry
            stopped = "model_error"
            break
        model_ms = _ms(started)
        messages += response.output
        calls = [item for item in response.output if item.type == "function_call"]
        if calls:
            ran = time.perf_counter()
            result = tools.run(ctx, calls[0])
            messages.append(_output(calls[0].call_id, result))
            for extra in calls[1:]:
                messages.append(_output(extra.call_id, {"error": ONE_TOOL}))
            entry = {"n": n, "by": "model", "tool": calls[0].name, "args": tools.args_of(calls[0]), "result": result,
                     "ok": "error" not in result, "ms": _ms(started), "model_ms": model_ms, "tool_ms": _ms(ran),
                     "tokens": _usage(response)}
        else:
            messages.append(_user(PLAIN_TEXT))
            entry = {"n": n, "by": "model", "tool": None, "args": None, "result": {"error": PLAIN_TEXT},
                     "said": (response.output_text or "")[:500], "ok": False, "ms": _ms(started),
                     "model_ms": model_ms, "tokens": _usage(response)}
        trace.append(entry)
        yield "turn", entry
        if record.submitted:
            stopped = "submitted"
            break
    used = n

    fields = {f: record.kept.get(f) or evidence.cant_tell(f) for f in SCORE_FIELDS}
    observed = {f: record.kept.get(f) or evidence.cant_tell(f) for f in OBSERVED_FIELDS}
    position = evidence.position(fields["side"])
    location = score = None
    needs, notes = [], []
    if stopped == "budget":
        notes.append(f"The reader used its {turns} turns before a full submission was accepted; fields it could "
                     f"not support are cant_tell.")
    elif stopped == "model_error":
        notes.append("The Model API stopped answering; fields accepted before that are kept, the rest are cant_tell.")

    if fields["address"]["status"] != "read":
        needs.append("address")
        notes.append("No address in the listing: add the house number and street to get a score.")
    elif scorer is None:
        notes.append("Scoring is off for this run.")
    else:
        n += 1
        address = fields["address"]["value"]
        started = time.perf_counter()
        try:
            location = scorer.locate(address)
            entry = {"n": n, "by": "code", "tool": "locate", "args": {"address": address}, "result": location,
                     "ok": True, "ms": _ms(started)}
        except ScoreError as e:
            entry = {"n": n, "by": "code", "tool": "locate", "args": {"address": address},
                     "result": {"error": str(e)}, "ok": False, "ms": _ms(started)}
            notes.append(f"Could not place the address: {e}")
        trace.append(entry)
        yield "turn", entry

    if location:
        n += 1
        args = {"address": location["label"], "floor": fields["floor"]["value"], "position": position,
                "answers": listing.answers.as_dict()}
        started = time.perf_counter()
        try:
            score = scorer.score(location["label"], fields["floor"]["value"], position, listing.answers)
            body = score["body"]
            entry = {"n": n, "by": "code", "tool": "score", "args": args, "ok": True, "ms": _ms(started),
                     "result": {"engine": score["engine"], **headline(body), "range": body.get("range")}}
        except ScoreError as e:
            entry = {"n": n, "by": "code", "tool": "score", "args": args, "result": {"error": str(e)}, "ok": False,
                     "ms": _ms(started)}
            notes.append(f"Could not score: {e}")
        trace.append(entry)
        yield "turn", entry

    yield "result", {
        "status": "complete" if stopped == "submitted" else "partial",
        "stopped": stopped,
        "fields": fields,
        "position": position,
        "observed": observed,
        "photo_readings": [record.photo_reads[i] for i in sorted(record.photo_reads)],
        "location": location,
        "score": score["body"] if score else None,
        "score_engine": score["engine"] if score else None,
        "answers": listing.answers.as_dict(),
        "needs": needs,
        "notes": notes,
        "trace": trace,
        "turns": {"used": used, "budget": turns},
        "model": model,
        "mode": mode,
    }


def read(listing, **kwargs):
    """The result alone, for callers that do not stream."""
    for kind, data in read_listing(listing, **kwargs):
        if kind == "result":
            return data


def headline(body):
    """The verdict and rank, where v2 puts them (top level) or v1 does (under manhattan)."""
    m = body.get("manhattan") if body.get("engine") != "v2" else None
    src = m if isinstance(m, dict) and "verdict" in m else body
    return {"verdict": src.get("verdict"), "quieter_than": src.get("quieter_than")}


def _user(text):
    return {"role": "user", "content": text}


def _output(call_id, result):
    return {"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)}


def _ms(since):
    return round((time.perf_counter() - since) * 1000)


def _usage(response):
    u = getattr(response, "usage", None)
    return {"input": getattr(u, "input_tokens", None), "output": getattr(u, "output_tokens", None)} if u else None
