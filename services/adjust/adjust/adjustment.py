"""The adjustment object, the tool that refuses a bad one, and how the engine applies a good one.
(Hackathon work, Oct 28.)

    {"source": "construction", "direction": "louder", "size": 1, "cap": 2,
     "cites": ["M01113570-I1-GC"], "reason": "a facade restoration on the block runs for months"}

The checks are code, not prompt: whatever the model asks for passes through submit_adjustment or does not reach the
engine. Rules A1 to A5 in CONTRACT.md.
"""
from . import config as A


class Refused(ValueError):
    """A tool refused the model's call. The message goes back to the model as the tool result."""


def submit_adjustment(adj, sent_ids, read=None, bound=None):
    """[A1-A4] The adjustment, normalised, or Refused with the reason.

    sent_ids  the row ids sent to the model; a citation outside them is refused
    read      optional {row id: accepted reading}; when given, a citation with no accepted reading is refused
    bound     optional f(direction, cites) -> the most steps the cited rows support in that direction
    """
    if not isinstance(adj, dict):
        raise Refused("an adjustment is an object with source, direction, size, cites and reason")
    source = adj.get("source")
    if source not in A.SOURCES:
        raise Refused(f"source {source!r} is not one of {', '.join(A.SOURCES)}")
    if source not in A.CAPS:
        raise Refused(f"no adjustment for the {source} source is allowed yet")
    cap = A.CAPS[source]
    if "cap" in adj and adj["cap"] != cap:
        raise Refused(f"the {source} cap is {cap}; it is set in config, not by the caller")
    direction = adj.get("direction")
    if direction not in A.DIRECTIONS:
        raise Refused(f"direction {direction!r} is not one of {', '.join(A.DIRECTIONS)}")
    size = adj.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise Refused(f"size {size!r} is not a whole number of steps of at least 1")
    if size > cap:
        raise Refused(f"size {size} exceeds the {source} cap of {cap}")
    cites = adj.get("cites")
    if not isinstance(cites, list) or not cites or not all(isinstance(c, str) for c in cites):
        raise Refused("cites must list at least one row id")
    if len(set(cites)) != len(cites):
        raise Refused("cites repeats a row id")
    sent = set(sent_ids)
    for c in cites:
        if c not in sent:
            raise Refused(f"cites {c}, which is not among the rows sent")
    if read is not None:
        for c in cites:
            if c not in read:
                raise Refused(f"cites {c}, which has no accepted reading")
    if bound is not None:
        most = bound(direction, cites)
        if most < 1:
            raise Refused(f"none of the cited rows points {direction}")
        if size > most:
            raise Refused(f"the cited rows support at most {most} step{'s' if most != 1 else ''} {direction}, not {size}")
    reason = adj.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise Refused("reason is required")
    if len(reason) > A.MAX_REASON_CHARS:
        raise Refused(f"reason is over {A.MAX_REASON_CHARS} characters")
    return {"source": source, "direction": direction, "size": size, "cap": cap, "cites": list(cites),
            "reason": reason.strip()}


def apply(neutral, adjustments):
    """[A5] Per-source, per-window levels with each adjustment applied, for the engine to rank. A copy; the input is
    untouched. Each adjustment is checked against the cap again, so a hand-built one cannot skip it."""
    out = {n: dict(levels) for n, levels in neutral.items()}
    for adj in adjustments or []:
        if adj is None:
            continue
        source, size = adj["source"], adj["size"]
        if source not in A.CAPS or not 1 <= size <= A.CAPS[source]:
            raise Refused(f"adjustment of {size} on {source} is outside its cap")
        sign = 1 if adj["direction"] == "louder" else -1
        floor = A.LEVEL_FLOOR.get(source, {})
        for w, level in out[source].items():
            moved = level + sign * size * A.STEP_LEVEL[source]
            out[source][w] = max(moved, min(level, floor[w])) if w in floor else moved
    return out
