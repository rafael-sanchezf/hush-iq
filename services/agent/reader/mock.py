"""An offline Model API: a real OpenAI client whose requests never leave the machine.

    client = mock.client(responder)     # responder(body) -> {"output": [...]} or {"output_text": "..."}

The transport answers POST /responses in the Responses API's shape, so the loop runs the same SDK code path
in mock mode as live. Two responders use it: HeuristicModel below, which lets the app and the website run
without a key (regular expressions, clearly labelled mode "mock"), and the scripted model in the tests.
"""
import json
import re

import httpx
from openai import OpenAI

from . import evidence, settings


class ApiFailure(Exception):
    """Raise from a responder to make the mock API answer with this HTTP status."""

    def __init__(self, status=500, message="mock failure"):
        super().__init__(message)
        self.status = status


def tool_call(name, arguments, n=1):
    return {"output": [{"type": "function_call", "call_id": f"call-{n}", "name": name,
                        "arguments": json.dumps(arguments), "status": "completed"}]}


class MockTransport(httpx.BaseTransport):
    def __init__(self, responder):
        self.responder = responder
        self.requests = []

    def handle_request(self, request):
        if not request.url.path.endswith("/responses"):
            return httpx.Response(404, json={"error": {"message": f"mock: no {request.url.path}"}})
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        n = len(self.requests)
        try:
            answer = self.responder(body) or {}
        except ApiFailure as e:
            return httpx.Response(e.status, json={"error": {"message": str(e), "type": "server_error"}})
        return httpx.Response(200, json=_response_body(answer, n))


def client(responder):
    """An OpenAI client answered by responder. The transport is on client.mock_transport for inspection."""
    transport = MockTransport(responder)
    c = OpenAI(api_key="mock", base_url=settings.DEFAULT_BASE_URL, max_retries=0,
               http_client=httpx.Client(transport=transport))
    c.mock_transport = transport
    return c


def _response_body(answer, n):
    output = answer.get("output") or []
    if not output and answer.get("output_text") is not None:
        output = [{"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": answer["output_text"], "annotations": []}]}]
    usage = answer.get("usage") or {"input_tokens": 100, "output_tokens": 20}
    return {
        "id": f"resp-mock-{n}", "object": "response", "created_at": 0, "model": "mock", "status": "completed",
        "output": [dict(item, id=item.get("id", f"item-{n}-{i}")) for i, item in enumerate(output)],
        "usage": dict(usage, total_tokens=usage["input_tokens"] + usage["output_tokens"]),
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


# ---------------------------------------------------------------- reading the request back
def listing_of(body):
    """(text, photo count) from the agent's first message."""
    first = next((i for i in body.get("input", []) if isinstance(i, dict) and i.get("role") == "user"), {})
    content = first.get("content") if isinstance(first.get("content"), str) else ""
    m = re.search(r"<<<\n(.*)\n>>>", content, re.S)
    photos = re.search(r"PHOTOS: (\d+)", content)
    return (m.group(1) if m else ""), (int(photos.group(1)) if photos else 0)


def history(body):
    """[(call, output)] for every tool call so far, oldest first."""
    items = [i for i in body.get("input", []) if isinstance(i, dict)]
    outputs = {i["call_id"]: json.loads(i["output"]) for i in items if i.get("type") == "function_call_output"}
    return [(i, outputs.get(i["call_id"])) for i in items if i.get("type") == "function_call"]


def photo_index(body):
    """The photo a read_photo sub-call is about, from its prompt."""
    for item in body.get("input", []):
        for block in item.get("content", []) if isinstance(item.get("content"), list) else []:
            m = re.search(r"photo (\d+) of", block.get("text", "")) if isinstance(block, dict) else None
            if m:
                return int(m.group(1))
    return None


# ---------------------------------------------------------------- the heuristic model
_ADDRESS = re.compile(r"\b\d{1,5}(?:-\d{1,4})?\s+(?:(?:East|West|North|South|E\.|W\.|E|W)\s+)?"
                      r"(?:\d{1,3}(?:st|nd|rd|th)|[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)?\s+"
                      r"(?:Street|St\.?|Avenue|Ave\.?|Place|Pl\.?|Road|Boulevard|Blvd\.?|Drive|Square|Terrace|Lane)"
                      r"|\b\d{1,5}\s+Broadway\b")
_UNIT = re.compile(r"\b(?:Apt\.?|Apartment|Unit)\s*#?\s*([0-9]{1,3}[A-Z]{1,2}|[A-Z]{1,2}[0-9]{0,3}|[0-9]{1,4})\b")
_FLOOR_WORDS = {w: i for i, w in enumerate(evidence._UNITS_TH) if w}
_FLOOR = re.compile(r"\b(\d{1,3})(?:st|nd|rd|th)?[\s-]*(?:floor|fl)\b|\b(" + "|".join(_FLOOR_WORDS) + r")[\s-]*floor\b",
                    re.I)
_SIDE_ORDER = ("corner", "courtyard", "rear", "street")


def _clause(text, m):
    """The sentence around a match: from the last . ; or blank line before it to the next one after it."""
    stops = (".", ";", "\n\n")
    start = max(text.rfind(c, 0, m.start()) + len(c) if text.rfind(c, 0, m.start()) >= 0 else 0 for c in stops)
    ends = [i for i in (text.find(c, m.end()) for c in stops) if i >= 0]
    return text[start:min(ends) if ends else len(text)].strip()


def _read(value, quote):
    return {"status": "read", "value": value, "evidence": [{"source": "text", "quote": quote}]}


def heuristic_fields(text):
    """What regular expressions can read from a listing. Stand-in for the model when there is no key."""
    fields = {f: {"status": "cant_tell"} for f in evidence.SCORE_FIELDS}
    if m := _ADDRESS.search(text):
        fields["address"] = _read(m.group(0), m.group(0))
    if m := _UNIT.search(text):
        fields["unit"] = _read(m.group(1), m.group(0))
    if m := _FLOOR.search(text):
        floor = int(m.group(1)) if m.group(1) else _FLOOR_WORDS[m.group(2).lower()]
        fields["floor"] = _read(floor, m.group(0))
    elif m := re.search(r"\bgarden[\s-]*(?:level|floor)\b", text, re.I):
        fields["floor"] = _read(1, m.group(0))
    elif m := re.search(evidence._TOP_STATED, text):
        fields["floor"] = _read(evidence.TOP, _clause(text, m))
    for side in _SIDE_ORDER:
        if m := re.search(evidence._SIDE_STATED[side], text, re.I):
            fields["side"] = _read(side, _clause(text, m))
            break
    return fields


class HeuristicModel:
    """Reads photos as cant_tell (it cannot see), then submits what heuristic_fields finds. A refused field is
    resubmitted as cant_tell, so a run always ends."""

    def __call__(self, body):
        if "tools" not in body:
            return {"output_text": json.dumps({"fields": {}, "note": "mock mode: no model looked at this photo"})}
        text, n_photos = listing_of(body)
        past = history(body)
        if n_photos and not any(c["name"] == "read_photo" for c, _ in past):
            return tool_call("read_photo", {"indexes": list(range(min(n_photos, 6)))}, len(past) + 1)
        fields = heuristic_fields(text)
        for call, out in past:
            if call["name"] == "submit_listing" and out and out.get("refused"):
                for name in out["refused"]:
                    if name in fields:
                        fields[name] = {"status": "cant_tell"}
        return tool_call("submit_listing", {"fields": fields}, len(past) + 1)
