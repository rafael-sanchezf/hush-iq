"""Reading one listing photo with Muse Spark, multimodal. (Hackathon work, Oct 28.)

One model call per photo, JSON out, every field checked in code (evidence.check_photo_field): a value outside
its type becomes cant_tell, and a field read with no description of what shows it becomes cant_tell. The
reading is what submit_listing checks photo citations against.
"""
import json

import openai

from . import evidence

FIELDS = ("floor", "side") + evidence.OBSERVED_FIELDS
MAX_ATTEMPTS = 2           # an empty or cut-off reply is not valid JSON, so it is asked again
MAX_OUTPUT_TOKENS = 4096   # reasoning tokens count against it

PROMPT = """You are looking at photo {index} of a New York City apartment listing. Report only what this photo
shows. For each field, either read it, saying in "what" the thing in the photo that shows it, or answer
cant_tell. Most photos show only a few fields: cant_tell is the right answer for the rest. Do not judge how
quiet, bright or nice anything is.

Fields:
- floor: the apartment's floor as a whole number, only if the photo shows it (a floor number on a door or a
  sign, an elevator panel lit at a floor). A high view is not a floor number: cant_tell.
- side: which side of the building the window in this photo faces. street: a street or avenue below, with
  traffic, parked cars or the building across the street; rear: the backs of other buildings, back yards;
  courtyard: an enclosed courtyard inside the building; corner: windows on two walls at a street corner.
- view: street | courtyard | rear_yards | airshaft | park | water | skyline
- windows: {{"floor_to_ceiling": true|false, "operable": true|false|null}} (null if you cannot tell whether
  they open)
- ac_units: window | through_wall | split | central (central: ceiling or wall vents, no unit visible)
- wall_material: brick | concrete | plaster | glass | wood | stone

Return only JSON:
{{"fields": {{"floor": {{"status": "read", "value": 4, "what": "..."}}, "side": {{"status": "cant_tell"}}, ...}},
 "note": "one line: what the photo shows"}}"""


def read(client, model, photo, index):
    """{"index", "fields": {name: field}, "note", "dropped": [why], "tokens"} for one photo."""
    error, parsed, tokens = "", None, {"input": 0, "output": 0, "reasoning": 0}
    for _ in range(MAX_ATTEMPTS):
        prompt = PROMPT.format(index=index)
        if error:
            prompt += f"\n\nYour previous output was not valid JSON ({error}). Return only the JSON object."
        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt},
                                                {"type": "input_image", "image_url": photo.data_url}]}],
            text={"format": {"type": "json_object"}},
            store=False,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        _add_usage(tokens, response)
        try:
            parsed = json.loads(response.output_text)
            if not isinstance(parsed, dict):
                raise ValueError("not a JSON object")
            break
        except ValueError as e:
            error, parsed = str(e), None
    if parsed is None:
        return dict(_unread(index, f"the photo model returned no usable JSON: {error}"), tokens=tokens)
    raw = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields, dropped = {}, []
    for name in FIELDS:
        fields[name], why = evidence.check_photo_field(name, raw.get(name))
        if why:
            dropped.append(why)
    return {"index": index, "fields": fields, "note": evidence.normalize(parsed.get("note"))[:evidence.MAX_WHAT],
            "dropped": dropped, "tokens": tokens}


def _add_usage(tokens, response):
    u = getattr(response, "usage", None)
    if u:
        details = getattr(u, "output_tokens_details", None)
        tokens["input"] += u.input_tokens or 0
        tokens["output"] += u.output_tokens or 0
        tokens["reasoning"] += getattr(details, "reasoning_tokens", 0) or 0


def read_safely(client, model, photo, index):
    """read(), with a failed model call coming back as an unread photo instead of an exception."""
    try:
        return read(client, model, photo, index)
    except openai.APIError as e:
        return _unread(index, f"the photo model call failed: {e}", failed=True)


def _unread(index, note, failed=False):
    reading = {"index": index, "fields": {n: evidence.cant_tell(n) for n in FIELDS}, "note": note, "dropped": []}
    if failed:
        reading["failed"] = True
    return reading
