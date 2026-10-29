"""The agent's two tools: what the model sees (DEFINITIONS) and what happens when it calls one (run).

    read_photo      look at listing photos by index; refuses an index that does not exist
    submit_listing  the fields with their evidence; refuses any field the checks in evidence.py refuse

A result is what the model sees next. A refused call comes back with "error" so the model can correct it.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import evidence, photos
from .evidence import OBSERVED_FIELDS, SCORE_FIELDS, Refused

MAX_PHOTOS_PER_CALL = 6

_EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string", "description": '"text", or "photo:<index>" for a photo you read'},
            "quote": {"type": "string", "description": "for text: the exact words from the listing"},
        },
        "required": ["source"],
    },
}


def _field(value_schema, description):
    return {
        "type": "object",
        "description": description,
        "additionalProperties": False,
        "properties": {"status": {"type": "string", "enum": list(evidence.STATUSES)}, "value": value_schema,
                       "evidence": _EVIDENCE},
        "required": ["status"],
    }


_ENUM_OR_NULL = lambda values: {"type": ["string", "null"], "enum": list(values) + [None]}  # noqa: E731

READ_PHOTO = {
    "type": "function",
    "name": "read_photo",
    "description": "Look at listing photos by index (0-based), up to 6 per call. Returns, for each photo, every "
                   "field it shows (floor, side, view, windows, ac_units, wall_material) with what in the photo "
                   "shows it, or cant_tell. Read a photo before citing it. Refused if an index does not exist.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"indexes": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1,
                                   "maxItems": MAX_PHOTOS_PER_CALL}},
        "required": ["indexes"],
    },
}

SUBMIT_LISTING = {
    "type": "function",
    "name": "submit_listing",
    "description": "Submit the apartment's fields, each read (with evidence) or cant_tell. Every text quote must "
                   "be copied exactly from the listing and must state the value; every photo citation must be a "
                   "photo you read whose reading shows that value. Refused fields come back with the reason: fix "
                   "them or mark them cant_tell and submit again. Accepted means the reading is done.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "address": _field({"type": ["string", "null"]}, "house number and street, as written"),
                    "unit": _field({"type": ["string", "null"]}, "apartment number, as written"),
                    "floor": _field({"type": ["integer", "string", "null"]},
                                    'the floor as a whole number, or "top" for PH, penthouse or top floor with no '
                                    'number'),
                    "side": _field(_ENUM_OR_NULL(evidence.SIDES), "which side of the building the unit faces"),
                },
                "required": list(SCORE_FIELDS),
            },
            "observed": {
                "type": "object",
                "description": "what the photos show; photo evidence only",
                "additionalProperties": False,
                "properties": {
                    "view": _field(_ENUM_OR_NULL(evidence.VIEWS), "what the windows look out on"),
                    "windows": _field({"type": ["object", "null"]},
                                      '{"floor_to_ceiling": true|false, "operable": true|false|null}'),
                    "ac_units": _field(_ENUM_OR_NULL(evidence.AC_UNITS), "the kind of air conditioning visible"),
                    "wall_material": _field(_ENUM_OR_NULL(evidence.WALLS), "the wall material visible"),
                },
            },
        },
        "required": ["fields"],
    },
}

DEFINITIONS = [READ_PHOTO, SUBMIT_LISTING]


@dataclass
class Record:
    """One run's record: the photo readings, the fields kept so far, whether a submission was accepted."""
    listing: object
    photo_reads: dict = field(default_factory=dict)
    kept: dict = field(default_factory=dict)
    submitted: bool = False


@dataclass
class Context:
    client: object
    model: str
    record: Record


def run(ctx, call):
    """Run the tool the model chose: an item of response.output, or the same as a dict."""
    name, raw = _get(call, "name"), _get(call, "arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError) as e:
        return {"error": f"tool arguments are not valid JSON: {e}"}
    if not isinstance(args, dict):
        return {"error": "tool arguments must be a JSON object"}
    tool = {"read_photo": read_photo, "submit_listing": submit_listing}.get(name)
    if tool is None:
        return {"error": f"unknown tool {name!r}: call read_photo or submit_listing"}
    return tool(ctx, args)


def args_of(call):
    raw = _get(call, "arguments") or "{}"
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return {"unparsed": str(raw)[:500]}


def read_photo(ctx, args):
    indexes = args.get("indexes")
    if isinstance(indexes, int):
        indexes = [indexes]
    if not isinstance(indexes, list) or not indexes or not all(isinstance(i, int) for i in indexes):
        return {"error": "indexes must be a list of photo indexes, for example [0, 1]"}
    indexes = list(dict.fromkeys(indexes))
    if len(indexes) > MAX_PHOTOS_PER_CALL:
        return {"error": f"at most {MAX_PHOTOS_PER_CALL} photos per call"}
    n = len(ctx.record.listing.photos)
    if n == 0:
        return {"error": "this listing has no photos"}
    missing = [i for i in indexes if not 0 <= i < n]
    if missing:
        return {"error": f"photo {', '.join(map(str, missing))} does not exist; this listing has {n} photo(s), "
                         f"0 to {n - 1}"}
    todo = [i for i in indexes if i not in ctx.record.photo_reads]
    fresh = {}
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            for reading in pool.map(lambda i: photos.read_safely(ctx.client, ctx.model,
                                                                 ctx.record.listing.photos[i], i), todo):
                fresh[reading["index"]] = reading
                if not reading.get("failed"):     # a failed call is not kept, so it can be tried again
                    ctx.record.photo_reads[reading["index"]] = reading
    return {"photos": [ctx.record.photo_reads.get(i) or fresh[i] for i in indexes]}


def submit_listing(ctx, args):
    rec = ctx.record
    groups = {"fields": SCORE_FIELDS, "observed": OBSERVED_FIELDS}
    accepted, refused = {}, {}
    for group, names in groups.items():
        given = args.get(group) or {}
        if not isinstance(given, dict):
            return {"error": f"{group} must be an object keyed by field name"}
        for name in names:
            try:
                accepted[name] = evidence.check_field(name, given.get(name), rec.listing.text, rec.photo_reads,
                                                      len(rec.listing.photos))
            except Refused as e:
                refused[name] = str(e)
    rec.kept.update(accepted)
    if refused:
        return {"error": f"{len(refused)} field(s) refused. Fix each one or mark it cant_tell, then call "
                         f"submit_listing again with every field.",
                "refused": refused, "accepted": sorted(accepted)}
    rec.submitted = True
    return {"status": "accepted", "fields": {n: accepted[n] for n in SCORE_FIELDS},
            "observed": {n: accepted[n] for n in OBSERVED_FIELDS}}


def _get(call, key):
    return call.get(key) if isinstance(call, dict) else getattr(call, key, None)
