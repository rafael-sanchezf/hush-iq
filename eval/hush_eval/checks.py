"""The checks. Pure functions over the shapes in shapes.py: no network, no model, no service imports.

Each check returns a list of Problem. A hard problem fails the run; a soft one is reported and does not.
    reader_grounding   every field marked read has a quote that is in the listing, or a photo that exists
    verdict_citations  every citation points at an evidence line that exists; no decibels
    adjustments        every permit adjustment is within its cap and cites rows that are in the pull
    ai_switch          with AI off no model wrote anything; a result's `ai` object answers what the run asked for
    extraction         the reader's fields against the gold labels, one outcome per field
"""
import json
import re
from dataclasses import asdict, dataclass

from . import shapes as S


@dataclass
class Problem:
    check: str
    where: str
    message: str
    hard: bool = True

    def as_dict(self):
        return asdict(self)


def _norm_text(s):
    """Whitespace runs to one space, curly quotes and dashes to plain. Case is kept: a quote is a quote."""
    s = str(s).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


_PHOTO = re.compile(r"^photo:(\d+)$")


def _evidence_problems(ev, text, n_photos, where):
    out = []
    if not isinstance(ev, dict):
        return [Problem("reader_grounding", where, f"evidence is not an object: {ev!r}")]
    src = ev.get("source")
    if src == "text":
        q = ev.get("quote")
        if not isinstance(q, str) or not q.strip():
            out.append(Problem("reader_grounding", where, "text evidence with an empty quote"))
        elif _norm_text(q) not in _norm_text(text):
            out.append(Problem("reader_grounding", where, f"quote not in the listing: {q!r}"))
        elif "start" in ev or "end" in ev:            # offsets, where the reader sends them, must point at the quote
            a, b = ev.get("start"), ev.get("end")
            if not (isinstance(a, int) and isinstance(b, int) and text[a:b] == q):
                out.append(Problem("reader_grounding", where, f"offsets {a}:{b} do not point at the quote {q!r}"))
    elif isinstance(src, str) and _PHOTO.match(src):
        i = int(_PHOTO.match(src).group(1))
        if i >= n_photos:
            out.append(Problem("reader_grounding", where,
                               f"cites {src}, but the listing has {n_photos} photo{'s' if n_photos != 1 else ''}"))
        if not str(ev.get("what") or "").strip():
            out.append(Problem("reader_grounding", where, f"{src} evidence says nothing about what it shows"))
    else:
        out.append(Problem("reader_grounding", where, f"unknown evidence source {src!r}"))
    return out


def _adjective_only(quote):
    words = re.findall(r"[a-z']+", quote.lower())
    return bool(words) and all(w in S.SALES_ADJECTIVES for w in words)


def iter_fields(result):
    """(group, name, field) for every text field and observed field the result carries."""
    for group, names in (("fields", S.TEXT_FIELDS), ("observed", S.OBSERVED_FIELDS)):
        block = result.get(group) or {}
        for name in names:
            if name in block:
                yield group, name, block[name]


def reader_grounding(result, listing):
    """Every field marked read is tied to the listing it came from: a quote that is a substring of the text,
    or a photo index that exists. "Can't tell" carries no value. Values stay inside their enums."""
    text, n_photos = listing.get("text") or "", len(listing.get("photos") or [])
    out = []
    if not isinstance(result, dict):
        return [Problem("reader_grounding", "result", "the reader returned no result object")]
    for group in ("fields", "observed"):
        if not isinstance(result.get(group), dict):
            out.append(Problem("reader_grounding", group, f"missing the {group} object"))
    for group, name, f in iter_fields(result):
        where = f"{group}.{name}"
        if not isinstance(f, dict):
            out.append(Problem("reader_grounding", where, f"field is not an object: {f!r}"))
            continue
        status, value, evidence = f.get("status"), f.get("value"), f.get("evidence") or []
        if status not in S.STATUSES:
            out.append(Problem("reader_grounding", where, f"status {status!r} is not read or cant_tell"))
            continue
        for ev in evidence:
            out += _evidence_problems(ev, text, n_photos, where)
        if status == S.CANT_TELL:
            if value not in S.CANT_TELL_VALUES:
                out.append(Problem("reader_grounding", where, f"cant_tell with a value: {value!r}"))
            continue
        if value is None:
            out.append(Problem("reader_grounding", where, "read with no value"))
        if not evidence:
            out.append(Problem("reader_grounding", where, "read with no evidence"))
        if name in ("floor", "side") and evidence and all(
                e.get("source") == "text" and _adjective_only(e.get("quote") or "") for e in evidence if isinstance(e, dict)):
            out.append(Problem("reader_grounding", where, "the only evidence is a sales adjective: "
                               + ", ".join(repr(e.get("quote")) for e in evidence if isinstance(e, dict))))
        out += _value_problems(name, value, where)
    pos = result.get("position")
    if pos not in S.POSITIONS:
        out.append(Problem("reader_grounding", "position", f"position {pos!r} is not front, rear or unknown"))
    side = (result.get("fields") or {}).get("side") or {}
    if isinstance(side, dict) and pos in S.POSITIONS:
        want = S.canonical("side", side.get("value")) if side.get("status") == "read" else "unknown"
        if want in S.SIDES + ("unknown",) and want != pos:
            out.append(Problem("reader_grounding", "position", f"position {pos!r} disagrees with the side field ({want!r})"))
    return out


def _value_problems(name, value, where):
    if name == "floor":
        if isinstance(value, bool) or not isinstance(value, int) or not S.FLOOR_MIN <= value <= S.FLOOR_MAX:
            return [Problem("reader_grounding", where, f"floor {value!r} is not an integer from {S.FLOOR_MIN} to {S.FLOOR_MAX}")]
    elif name == "side":
        if S.canonical("side", value) not in S.SIDES:
            return [Problem("reader_grounding", where, f"side {value!r} is not front or rear")]
    elif name in S.OBSERVED_VALUES:
        if S.canonical(name, value) not in S.OBSERVED_VALUES[name]:
            return [Problem("reader_grounding", where, f"{name} {value!r} is not one of {', '.join(S.OBSERVED_VALUES[name])}",
                            hard=False)]
    elif name in ("address", "unit"):
        if not isinstance(value, str) or not value.strip():
            return [Problem("reader_grounding", where, f"{name} {value!r} is not text")]
    return []


# ---------------------------------------------------------------- verdict
_DECIBEL = re.compile(r"\b(\d+\s*)?(db|dba|decibels?)\b", re.I)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def verdict_citations(verdict, score=None):
    """Every citation points at an evidence line that exists. Hard: a citation to a missing line, duplicate ids,
    no sentences, a decibel figure (no decibels leave the engine, V8). Soft: a sentence with no citation, a number
    in a sentence that none of its cited lines contains, a writer name outside the contract."""
    out = []
    if not isinstance(verdict, dict):
        return [Problem("verdict_citations", "verdict", "the verdict writer returned no object")]
    evidence = verdict.get("evidence") or []
    ids = [e.get("id") for e in evidence if isinstance(e, dict)]
    by_id = {e.get("id"): str(e.get("text") or "") for e in evidence if isinstance(e, dict)}
    for dup in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        out.append(Problem("verdict_citations", "evidence", f"evidence id {dup!r} appears more than once"))
    for e in evidence:
        if not isinstance(e, dict) or not str(e.get("text") or "").strip():
            out.append(Problem("verdict_citations", "evidence", f"empty evidence line: {e!r}"))
    sentences = verdict.get("sentences") or []
    if not sentences:
        out.append(Problem("verdict_citations", "sentences", "no sentences"))
    for k, s in enumerate(sentences):
        where = f"sentences[{k}]"
        text = str((s or {}).get("text") or "")
        cites = (s or {}).get("cites") or []
        if not text.strip():
            out.append(Problem("verdict_citations", where, "empty sentence"))
        for c in cites:
            if c not in by_id:
                out.append(Problem("verdict_citations", where, f"cites {c!r}, which is not in the evidence it was sent"))
        if not cites:
            out.append(Problem("verdict_citations", where, f"no citation: {text[:80]!r}", hard=False))
        if _DECIBEL.search(text):
            out.append(Problem("verdict_citations", where, f"a decibel figure left the engine: {text[:80]!r}"))
        cited_text = " ".join(by_id.get(c, "") for c in cites)
        for num in _NUMBER.findall(text):
            if num not in _NUMBER.findall(cited_text):
                out.append(Problem("verdict_citations", where, f"the number {num} is in none of its cited lines", hard=False))
    if verdict.get("writer") not in S.WRITERS:
        out.append(Problem("verdict_citations", "writer", f"writer {verdict.get('writer')!r} is not one of {S.WRITERS}", hard=False))
    return out


# ---------------------------------------------------------------- permit adjustments
ADJUST_SIZE_KEYS = ("size", "delta", "points", "adjustment")
ROW_ID_KEYS = ("work_permit", "id", "job_filing_number", "row_id")
DIRECTIONS = ("louder", "quieter")
_PERMIT = re.compile(r"^permit:(.+)$")


def row_id(row):
    for k in ROW_ID_KEYS:
        if row.get(k):
            return str(row[k])
    return None


def adjustment_list(adj):
    """The permit reader returns one `adjustment` (or null); an `adjustments` list is read the same way."""
    if "adjustment" in adj:
        return [adj["adjustment"]] if adj["adjustment"] is not None else []
    return adj.get("adjustments")


def adjustments(adj, rows, caps):
    """Every adjustment names a capped source, stays within that cap, and cites only rows in the pull; every
    permit reading quotes its own row's job description. `caps` comes from the permit reader's own config when it
    is importable, never from the model's output."""
    out = []
    if adj is None:
        return out
    items = adjustment_list(adj) if isinstance(adj, dict) else None
    if not isinstance(items, list):
        return [Problem("adjustments", "adjust", "the permit reader returned no adjustment or adjustments")]
    by_id = {row_id(r): r for r in rows if isinstance(r, dict)}
    by_id.pop(None, None)
    for k, a in enumerate(items):
        where = f"adjustments[{k}]"
        if not isinstance(a, dict):
            out.append(Problem("adjustments", where, f"not an object: {a!r}"))
            continue
        src = a.get("source") or a.get("ingredient")
        if src not in caps:
            out.append(Problem("adjustments", where, f"source {src!r} has no cap"))
        size = next((a[k2] for k2 in ADJUST_SIZE_KEYS if k2 in a), None)
        if isinstance(size, bool) or not isinstance(size, (int, float)):
            out.append(Problem("adjustments", where, f"size {size!r} is not a number"))
        elif src in caps and abs(size) > caps[src] + 1e-9:
            out.append(Problem("adjustments", where, f"{src} moved by {size:g}, over its cap of {caps[src]:g}"))
        if "direction" in a and a["direction"] not in DIRECTIONS:
            out.append(Problem("adjustments", where, f"direction {a['direction']!r} is not louder or quieter"))
        cites = a.get("cites") or a.get("rows") or []
        if not cites:
            out.append(Problem("adjustments", where, "cites no rows"))
        for c in cites:
            if str(c) not in by_id:
                out.append(Problem("adjustments", where, f"cites row {c!r}, which is not in the pull"))
    for k, r in enumerate(adj.get("readings") or []):
        for name in ("kind", "duration"):
            f = (r or {}).get(name) or {}
            if f.get("status") != "read":
                continue
            for ev in f.get("evidence") or []:
                m = _PERMIT.match(str(ev.get("source") or ""))
                where = f"readings[{k}].{name}"
                if not m or m.group(1) not in by_id:
                    out.append(Problem("adjustments", where, f"cites {ev.get('source')!r}, which is not a permit in the pull"))
                    continue
                desc = _norm_text(by_id[m.group(1)].get("job_description") or "").lower()
                if _norm_text(ev.get("quote") or "").lower() not in desc or not str(ev.get("quote") or "").strip():
                    out.append(Problem("adjustments", where, f"quote {ev.get('quote')!r} is not in {m.group(1)}'s description"))
    return out


# ---------------------------------------------------------------- the AI switch (AI_SWITCH.md)
AI_MODES = ("model", "basic")
AI_PROVIDERS = ("meta", "openai", "anthropic", None)
AI_KEYS = ("house", "caller", None)
AI_REASONS = (None, "switched_off", "house_off", "no_key", "key_rejected", "provider_busy", "provider_error")


def ai_switch(out, service, switch="on", provider=None, caller_key=False):
    """A result against the AI setting the run asked for. With AI off no model may have written any of it, whatever
    the service says. Its `ai` object, once the service sends one, must have the contract's shape and answer what
    was asked: a provider run that ran basic, or on the house key, did not measure that provider."""
    if not isinstance(out, dict):
        return []
    found = []
    if switch == "off":
        if service == "verdict" and out.get("writer") != "template":
            found.append(Problem("ai_switch", service, f"AI off, but the verdict was written by {out.get('writer')!r}"))
        if service == "adjust" and adjustment_list(out):
            found.append(Problem("ai_switch", service, "AI off, but the permit reader adjusted the score"))
        if service == "reader" and out.get("mode") not in ("mock", "basic", "rules") and (out.get("ai") or {}).get("mode") != "basic":
            found.append(Problem("ai_switch", service, f"AI off, but the reader ran in mode {out.get('mode')!r}"))
    ai = out.get("ai")
    if ai is None:
        return found
    if not isinstance(ai, dict):
        return found + [Problem("ai_switch", service, f"`ai` is not an object: {ai!r}")]
    for name, allowed in (("mode", AI_MODES), ("provider", AI_PROVIDERS), ("key", AI_KEYS), ("reason", AI_REASONS)):
        if ai.get(name) not in allowed:
            found.append(Problem("ai_switch", service, f"ai.{name} is {ai.get(name)!r}, not one of {allowed}"))
    if (ai.get("mode") == "basic") != (ai.get("reason") is not None):
        found.append(Problem("ai_switch", service, f"ai.reason {ai.get('reason')!r} with mode {ai.get('mode')!r}: "
                                                   "a reason is set exactly when the mode is basic"))
    if switch == "off":
        if ai.get("mode") != "basic" or ai.get("reason") != "switched_off":
            found.append(Problem("ai_switch", service, f"AI off, but ai says mode {ai.get('mode')!r}, reason {ai.get('reason')!r}"))
        return found
    if provider and ai.get("mode") == "basic":
        found.append(Problem("ai_switch", service, f"ran basic ({ai.get('reason')}): {provider} was not measured"))
    elif provider and ai.get("provider") != provider:
        found.append(Problem("ai_switch", service, f"asked for {provider}, ran {ai.get('provider')!r}"))
    if caller_key and ai.get("key") == "house":
        found.append(Problem("ai_switch", service, "a caller's key was sent, and the house key was spent"))
    return found


def key_absent(out, key, service):
    """The caller's key appears nowhere in a result. The message never contains the key."""
    if not key:
        return []
    blob = out if isinstance(out, str) else json.dumps(out, default=str)
    return [Problem("ai_switch", service, "the caller's key is in the result")] if key in blob else []


# ---------------------------------------------------------------- extraction against gold
CORRECT, WRONG, ABSTAINED, INVENTED = "correct", "wrong", "cant_tell", "invented"


def field_value(result, name):
    """The reader's answer for one field: its value, CANT_TELL, or None when the field is absent."""
    group = "fields" if name in S.TEXT_FIELDS else "observed"
    f = (result.get(group) or {}).get(name)
    if not isinstance(f, dict):
        return None
    if f.get("status") != "read" or f.get("value") is None:
        return S.CANT_TELL
    return f["value"]


def compare(name, gold, got, building_floors=None):
    """One outcome for one field.
    gold None or CANT_TELL: the listing does not say (or contradicts itself); the right answer is cant_tell.
    gold "top": the listing says PH or top floor; "top" or the building's floor count is right."""
    got = S.canonical(name, got) if got is not None else S.CANT_TELL
    silent = gold is None or gold == S.CANT_TELL
    if got == S.CANT_TELL:
        return CORRECT if silent else ABSTAINED
    if silent:
        return INVENTED
    if name == "address":
        return CORRECT if S.normalize_address(got) == S.normalize_address(gold) else WRONG
    if name == "floor":
        if gold == "top":
            return CORRECT if got == "top" or (building_floors and _int(got) == int(building_floors)) else WRONG
        return CORRECT if _int(got) == int(gold) else WRONG
    if name == "unit":
        return CORRECT if re.sub(r"[^a-z0-9]", "", str(got).lower()) == re.sub(r"[^a-z0-9]", "", str(gold).lower()) else WRONG
    return CORRECT if got == S.canonical(name, gold) else WRONG


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def extraction(result, gold):
    """{field: {outcome, gold, got}} for every field the gold labels name."""
    out = {}
    bf = gold.get("building_floors")
    for name in S.TEXT_FIELDS:
        if name in gold:
            got = field_value(result, name)
            out[name] = {"outcome": compare(name, gold[name], got, bf), "gold": gold[name], "got": got}
    for name, g in (gold.get("observed") or {}).items():
        got = field_value(result, name)
        out[name] = {"outcome": compare(name, g, got), "gold": g, "got": got}
    return out


def tally(outcomes_by_case, fields):
    """Per-field counts and rates across cases. answerable = cases whose gold has a value."""
    rows = {}
    for name in fields:
        c = {CORRECT: 0, WRONG: 0, ABSTAINED: 0, INVENTED: 0, "answerable": 0, "silent_ok": 0, "n": 0}
        for outcomes in outcomes_by_case:
            o = outcomes.get(name)
            if not o:
                continue
            c["n"] += 1
            silent = o["gold"] is None or o["gold"] == S.CANT_TELL
            if not silent:
                c["answerable"] += 1
            if o["outcome"] == CORRECT and silent:
                c["silent_ok"] += 1
            c[o["outcome"]] += 1
        right = c[CORRECT] - c["silent_ok"]
        c["accuracy"] = right / c["answerable"] if c["answerable"] else None
        c["wrong_rate"] = (c[WRONG] + c[INVENTED]) / c["n"] if c["n"] else None
        rows[name] = c
    return rows
