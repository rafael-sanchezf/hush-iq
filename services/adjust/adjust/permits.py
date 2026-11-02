"""The permit reader: what each DOB NOW permit on the block is, how long it runs, and one bounded adjustment for the
construction source. (Hackathon work, Oct 28.)

The frozen construction ingredient counts unexpired loud-work permits and treats them all alike: an office
partition and a new tower each add one. A Meta model (Muse Spark) reads each permit's job description for the
kind of job and its duration, quoting the words behind each; code refuses a quote that is not in that permit's
description, then bounds the adjustment the model asks for. Rules P1 to P5 in CONTRACT.md.

    read_permits(rows, as_of)              rows as sources.dob_permits returns them
    read_permits(rows, as_of, client=c)    c: an OpenAI-SDK client (live, or the scripted mock in tests), or a
                                           backend from llm.client_for for any of the three providers
"""
import datetime as dt
import json
import re

from . import config as A
from .adjustment import Refused, submit_adjustment
from .backends import ProviderFailure, as_backend

SOURCE = "construction"
SCAFFOLD_WORK_TYPES = {"Sidewalk Shed", "Supported Scaffold", "Suspended Scaffold"}


# ---------------------------------------------------------------- the pull
def block_permits(address, today=None):
    """(located address, permit rows) through the frozen model's own fetch: same geocode, tax block and lookback as
    sources.pull_at. Network; raises sources.SourceError."""
    from noise_score import config as model_config, sources
    today = today or dt.date.today()
    a = sources.geocode(address)
    since = (today - dt.timedelta(days=30 * model_config.CONSTRUCTION_PERMIT_LOOKBACK_MONTHS)).isoformat()
    block = a["bbl"][1:6] if a.get("bbl") and len(a["bbl"]) == 10 else None
    return a, sources.dob_permits(a.get("borough"), block, since)


# ---------------------------------------------------------------- what is sent [P1]
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]\d{4}\b")


def scrub(row):
    """Only the allowed fields, and no email or phone number left in the description."""
    out = {k: row[k] for k in A.PERMIT_FIELDS if row.get(k) not in (None, "")}
    if "job_description" in out:
        out["job_description"] = _PHONE.sub("[removed]", _EMAIL.sub("[removed]", str(out["job_description"])))
    return out


def _cost(row):
    try:
        return float(row.get("estimated_job_costs") or 0)
    except (TypeError, ValueError):
        return 0.0


def permits_to_read(rows, as_of):
    """[P1] Unexpired permits of a loud or scaffold work type, one per permit id (a renewal repeats the id; the latest
    expiry wins), the costliest first, at most MAX_PERMITS_READ, scrubbed."""
    as_of = as_of if isinstance(as_of, str) else as_of.isoformat()
    latest = {}
    for r in rows or []:
        pid = r.get("work_permit")
        if not pid or r.get("work_type") not in A.READ_WORK_TYPES:
            continue
        exp = (r.get("expired_date") or "")[:10]
        if exp and exp < as_of:
            continue
        cur = latest.get(pid)
        if cur is None or (r.get("expired_date") or "") > (cur.get("expired_date") or ""):
            latest[pid] = r
    picked = sorted(latest.values(), key=lambda r: (-_cost(r), r["work_permit"]))[:A.MAX_PERMITS_READ]
    return [scrub(r) for r in picked]


def address_of(row):
    return " ".join(f"{row.get('house_no', '')} {row.get('street_name', '')}".split()).title()


# ---------------------------------------------------------------- one reading [P2]
def _norm(s):
    return " ".join(str(s).split()).casefold()


def check_quote(quote, description):
    """The quote as found in the description, or Refused. Case and runs of spaces are forgiven; nothing else."""
    if not isinstance(quote, str):
        raise Refused("a quote is required")
    q = quote.strip().strip("\"'“”")
    if len(q) < A.MIN_QUOTE_CHARS:
        raise Refused(f"quote {quote!r} is shorter than {A.MIN_QUOTE_CHARS} characters")
    if _norm(q) not in _norm(description or ""):
        raise Refused(f"quote {q!r} is not in this permit's job description")
    return q


def check_reading(item, sent):
    """[P2] One accepted reading in the shared field shape, or Refused. `sent` is {permit id: scrubbed row}."""
    if not isinstance(item, dict):
        raise Refused("a reading is an object with id, kind, kind_quote, duration and duration_quote")
    pid = item.get("id")
    if pid not in sent:
        raise Refused(f"permit {pid!r} is not among the permits sent")
    row = sent[pid]
    kind, duration = item.get("kind"), item.get("duration")
    if kind not in A.KINDS:
        raise Refused(f"kind {kind!r} is not one of {', '.join(A.KINDS)}")
    if duration not in A.DURATIONS:
        raise Refused(f"duration {duration!r} is not one of {', '.join(A.DURATIONS)}")
    desc = row.get("job_description")
    evidence = lambda q: [{"source": f"permit:{pid}", "quote": q}]

    if kind == "cant_tell":
        kind_field = {"value": None, "status": "cant_tell", "evidence": []}
    else:
        kind_field = {"value": kind, "status": "read", "evidence": evidence(check_quote(item.get("kind_quote"), desc))}
    if duration == "cant_tell":
        duration_field = {"value": None, "status": "cant_tell", "evidence": []}
    else:
        duration_field = {"value": duration, "status": "read",
                          "evidence": evidence(check_quote(item.get("duration_quote"), desc))}
    return {"id": pid, "address": address_of(row), "work_type": row.get("work_type"),
            "kind": kind_field, "duration": duration_field}


def pressure(reading):
    """[P3] Steps this permit pushes the construction source, signed: louder above 0, quieter below."""
    return A.PRESSURE[reading["kind"]["value"] or "cant_tell"][reading["duration"]["value"] or "cant_tell"]


def bound_for(read, sent):
    """[P3] The evidence bound submit_adjustment checks: the most steps the cited readings support in a direction.
    Quieter also needs the block as a whole to point that way (QUIETER_MIN_SHARE, none louder)."""
    def bound(direction, cites):
        if direction == "louder":
            return max([pressure(read[c]) for c in cites] + [0])
        if any(pressure(r) > 0 for r in read.values()):
            raise Refused("a permit on this block reads louder, so the block cannot be adjusted quieter")
        quieter = [r for r in read.values() if pressure(r) < 0]
        if len(quieter) < A.QUIETER_MIN_SHARE * len(sent):
            raise Refused(f"only {len(quieter)} of {len(sent)} permits read quieter than the count; "
                          f"at least {A.QUIETER_MIN_SHARE:.0%} must")
        return max([-pressure(read[c]) for c in cites] + [0])
    return bound


# ---------------------------------------------------------------- the rules reader [P4]
_RULES = [   # kind, pattern; first match wins, so the heavier kinds come first
    ("new_building", r"\bnew (?:\d+[- ]stor(?:y|ies) )?(?:building|construction)\b"),
    ("new_building", r"\bNB\s*#?\s*[A-Z]?\d{6,}"),
    ("new_building", r"\berect(?:ion of)? (?:a )?new\b"),
    ("demolition", r"\bfull demolition\b"),
    ("demolition", r"\bdemoli(?:tion of|sh) (?:the )?(?:existing )?(?:\d+[- ]stor(?:y|ies) )?(?:building|structure)\b"),
    ("facade", r"\bfa[cç]ade(?: (?:repairs?|restoration|work))?\b"),
    ("facade", r"\b(?:exterior )?masonry(?: (?:repairs?|restoration|work))?\b"),
    ("facade", r"\bparapets?\b"),
    ("facade", r"\b(?:local law 11|LL ?11|FISP)\b"),
    ("facade", r"\b(?:re)?pointing\b"),
    ("scaffold_shed", r"\bsidewalk shed\b"),
    ("scaffold_shed", r"\bscaffold(?:s|ing)?\b"),
    ("interior_renovation", r"\b(?:office|apartment|kitchen|bathroom) renovation\b"),
    ("interior_renovation", r"\binterior\b"),
    ("interior_renovation", r"\bpartitions?\b"),
]


def rules_reading(row):
    """A reading from keyword rules, for when no model key is set. The scaffold and shed work types read as
    scaffold_shed whenever the description names the scaffold or shed, since that is what the permit is for."""
    desc = row.get("job_description") or ""
    rules = _RULES
    if row.get("work_type") in SCAFFOLD_WORK_TYPES:
        rules = [r for r in _RULES if r[0] == "scaffold_shed"] + _RULES
    for kind, pattern in rules:
        m = re.search(pattern, desc, re.I)
        if m:
            duration = A.RULES_DURATION[kind]
            return {"id": row["work_permit"], "kind": kind, "kind_quote": m.group(0),
                    "duration": duration, "duration_quote": m.group(0) if duration != "cant_tell" else None}
    return {"id": row["work_permit"], "kind": "cant_tell", "duration": "cant_tell"}


LABELS = {"new_building": "new building", "demolition": "demolition", "facade": "facade job",
          "scaffold_shed": "scaffold or shed", "interior_renovation": "interior renovation", "other": "other job"}


def _phrase(readings):
    counts = {}
    for r in readings:
        key = (r["kind"]["value"], r["duration"]["value"])
        counts[key] = counts.get(key, 0) + 1
    parts = []
    for (kind, duration), n in counts.items():
        parts.append(f"{'a' if n == 1 else n} {LABELS[kind]}{'s' if n > 1 else ''}" + (f" ({duration})" if duration else ""))
    return ", ".join(parts)


def rules_adjustment(read, sent):
    """[P4] The adjustment the pressure table gives, through the same refusals as the model's, or (None, why)."""
    up = [r for r in read.values() if pressure(r) > 0]
    down = [r for r in read.values() if pressure(r) < 0]
    cap = A.CAPS[SOURCE]
    if up:
        adj = {"source": SOURCE, "direction": "louder", "size": min(cap, max(pressure(r) for r in up)),
               "cites": [r["id"] for r in up],
               "reason": f"Heavier or longer work than the permit count shows: {_phrase(up)} on this tax block."}
    elif down and len(down) >= A.QUIETER_MIN_SHARE * len(sent):
        adj = {"source": SOURCE, "direction": "quieter", "size": min(cap, max(-pressure(r) for r in down)),
               "cites": [r["id"] for r in down],
               "reason": f"{len(down)} of {len(sent)} permits on this tax block are lighter work than the count "
                         f"shows: {_phrase(down)}."}
    else:
        return None, "no permit reads heavier or lighter than the count already says"
    return submit_adjustment(adj, sent, read, bound_for(read, sent)), None


# ---------------------------------------------------------------- the model reader [P5]
def _pressure_table():
    lines = []
    for kind, row in A.PRESSURE.items():
        cells = ", ".join(f"{d} {'+' if v > 0 else ''}{v}" for d, v in row.items())
        lines.append(f"  {kind}: {cells}")
    return "\n".join(lines)


SYSTEM = f"""You read New York City building permits (DOB NOW) on one tax block, to tell a renter what the construction
near the building will be like. The score already counts these permits, each one the same. Your job is what the count
cannot see: what kind of job each permit is, and how long it will run.

First call read_permits once, with one reading for every permit sent:
- kind: facade (exterior walls, masonry, parapets, Local Law 11 work), interior_renovation (work inside a building),
  new_building (a new structure, including a permit filed under a new-building job, written NB), demolition (taking
  down a whole building), scaffold_shed (a scaffold or sidewalk shed with no other work described), other (the
  description says what the work is and it is none of these), or cant_tell (the description does not say).
- kind_quote: the shortest exact words of that permit's job_description that show the kind, copied as written.
  Required unless kind is cant_tell.
- duration: how long a job like this is expected to run: weeks (under 3 months), months (3 to 12), years (over 12).
  Descriptions rarely give dates, so judge from what the work is and its estimated cost. cant_tell only when the
  description does not say what the work is.
- duration_quote: the exact words of the job_description the duration rests on, usually the words that say what
  the work is. Required unless duration is cant_tell.
Quote the job_description only, never the work type or anything you know from elsewhere. A quote that is not in the
description is refused. Say cant_tell rather than guess. Ignore adjectives and sales words.

Then call submit_adjustment once, or no_adjustment when no permit reads heavier or lighter than a plain count implies.
The adjustment moves the construction source in whole steps, at most {A.CAPS[SOURCE]}. Each reading supports at most
these steps, by kind and duration (positive is louder, negative quieter):
{_pressure_table()}
A quieter adjustment also needs at least {A.QUIETER_MIN_SHARE:.0%} of the permits sent to read quieter and none louder.
Give direction (louder or quieter), size, cites (the ids of the permits it rests on) and a one-sentence reason a renter
can read. The tool refuses a size over the cap or over what the cited readings support, and a citation of a permit not
sent or not read. Read each refusal and correct the call."""

TOOLS = [
    {"type": "function", "function": {
        "name": "read_permits",
        "description": "Record one reading per permit: its kind and duration, each with the quoted words of its job "
                       "description. Each reading is accepted or refused on its own.",
        "parameters": {"type": "object", "required": ["readings"], "properties": {"readings": {
            "type": "array", "items": {"type": "object", "required": ["id", "kind", "duration"], "properties": {
                "id": {"type": "string", "description": "the permit id as sent"},
                "kind": {"type": "string", "enum": list(A.KINDS)},
                "kind_quote": {"type": ["string", "null"]},
                "duration": {"type": "string", "enum": list(A.DURATIONS)},
                "duration_quote": {"type": ["string", "null"]},
            }}}}}}},
    {"type": "function", "function": {
        "name": "submit_adjustment",
        "description": "Submit the one adjustment to the construction source. Refused when over the cap, over what "
                       "the cited readings support, or citing a permit not sent or not read.",
        "parameters": {"type": "object", "required": ["direction", "size", "cites", "reason"], "properties": {
            "direction": {"type": "string", "enum": list(A.DIRECTIONS)},
            "size": {"type": "integer", "minimum": 1, "maximum": A.CAPS[SOURCE]},
            "cites": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string", "maxLength": A.MAX_REASON_CHARS},
        }}}},
    {"type": "function", "function": {
        "name": "no_adjustment",
        "description": "Leave the construction source as the permit count has it.",
        "parameters": {"type": "object", "required": ["reason"], "properties": {"reason": {"type": "string"}}}}},
]


def _for_model(row):
    return {"id": row["work_permit"], "work_type": row.get("work_type"), "job_description": row.get("job_description"),
            "address": address_of(row), "issued_date": (row.get("issued_date") or "")[:10] or None,
            "expired_date": (row.get("expired_date") or "")[:10] or None,
            "estimated_job_costs": row.get("estimated_job_costs")}


def model_read(sent_rows, as_of, client, model):
    """[P5] The agent loop: the model calls read_permits, then submit_adjustment or no_adjustment; every call is
    checked here and a refusal goes back as the tool result. An empty reply (the token budget spent on reasoning)
    is sent again, and a failed call ends the read with no adjustment. `client` is a backend from adjust.backends,
    or an OpenAI-SDK client for Chat Completions; the checks are the same for every provider [S4].
    Returns (readings by id, adjustment, why_none, trace, usage per call, failure kind or None)."""
    backend = as_backend(client, model)
    sent = {r["work_permit"]: r for r in sent_rows}
    read, trace, usage = {}, [], []
    backend.start(SYSTEM, json.dumps({"as_of": as_of, "permits": [_for_model(r) for r in sent_rows]}), TOOLS)
    nudged, empties, turn = False, 0, 0
    while turn < A.MODEL_MAX_TURNS:
        try:
            reply = backend.call()
        except ProviderFailure as e:   # the kind and status only: a provider's error text can quote the key
            trace.append({"turn": turn + 1, "tool": None, "error": e.kind, "status": e.status})
            return read, None, "the model call failed", trace, usage, e.kind
        usage.append(reply.usage)
        if reply.declined:
            trace.append({"turn": turn + 1, "tool": None, "declined": True, "finish_reason": reply.finish})
            return read, None, "the model declined to read these permits", trace, usage, None
        if not reply.calls and not reply.text.strip():
            empties += 1
            trace.append({"turn": turn + 1, "tool": None, "empty": True, "finish_reason": reply.finish})
            if empties > A.MODEL_EMPTY_RETRIES:
                return read, None, "the model sent only empty replies", trace, usage, "provider_error"
            continue
        turn += 1
        backend.keep(reply)
        if not reply.calls:
            trace.append({"turn": turn, "tool": None, "said": reply.text[:300]})
            if nudged:
                return read, None, "the model stopped without submitting an adjustment", trace, usage, None
            nudged = True
            backend.say("Call read_permits, then submit_adjustment or no_adjustment.")
            continue
        done, results = None, []
        for call_id, name, arguments in reply.calls:
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if not isinstance(args, dict):
                result = {"ok": False, "refused": "arguments are not a JSON object"}
                trace.append({"turn": turn, "tool": name, "ok": False, "refused": result["refused"]})
            elif name == "read_permits":
                accepted, refused = [], []
                items = args.get("readings")
                for item in items if isinstance(items, list) else []:
                    try:
                        r = check_reading(item, sent)
                        read[r["id"]] = r
                        accepted.append(r["id"])
                    except Refused as e:
                        refused.append({"id": item.get("id") if isinstance(item, dict) else None, "why": str(e)})
                if not isinstance(items, list):
                    refused.append({"id": None, "why": "readings must be a list"})
                result = {"ok": not refused, "accepted": accepted, "refused": refused,
                          "not_read_yet": [p for p in sent if p not in read]}
                trace.append({"turn": turn, "tool": name, "accepted": accepted, "refused": refused})
            elif name == "submit_adjustment":
                try:
                    adj = submit_adjustment({"source": SOURCE, **args}, sent, read, bound_for(read, sent))
                    result = {"ok": True, "adjustment": adj}
                    done = ("adjustment", adj)
                    trace.append({"turn": turn, "tool": name, "ok": True, "adjustment": adj})
                except Refused as e:
                    result = {"ok": False, "refused": str(e)}
                    trace.append({"turn": turn, "tool": name, "ok": False, "refused": str(e), "asked": args})
            elif name == "no_adjustment":
                result = {"ok": True}
                done = ("none", str(args.get("reason") or "the model left the count as it is")[:A.MAX_REASON_CHARS])
                trace.append({"turn": turn, "tool": name, "ok": True, "reason": done[1]})
            else:
                result = {"ok": False, "refused": f"no tool named {name!r}"}
                trace.append({"turn": turn, "tool": name, "ok": False, "refused": result["refused"]})
            results.append((call_id, json.dumps(result)))
        backend.answer(results)
        if done:
            adj = done[1] if done[0] == "adjustment" else None
            return read, adj, (done[1] if done[0] == "none" else None), trace, usage, None
    return read, None, f"no accepted adjustment after {A.MODEL_MAX_TURNS} model turns", trace, usage, None


def _total(usage):
    out = {"calls": len(usage)}
    for k in ("prompt_tokens", "completion_tokens", "reasoning_tokens"):
        vals = [u[k] for u in usage if u and u.get(k) is not None]
        out[k] = sum(vals) if vals else None
    return out


# ---------------------------------------------------------------- the whole read
def _unread(rows, as_of):
    as_of = as_of or dt.date.today().isoformat()
    as_of = as_of if isinstance(as_of, str) else as_of.isoformat()
    sent_rows = permits_to_read(rows, as_of)
    out = {"source": SOURCE, "as_of": as_of, "reader": None, "permits": [_for_model(r) for r in sent_rows],
           "readings": [], "not_read": [], "adjustment": None, "why_none": None, "refusals": [], "trace": []}
    return as_of, sent_rows, out


def skip_permits(rows, as_of=None, why=None):
    """The reply when AI reading is off or cannot run [S2]: the permits listed, none read, no adjustment, so the
    permit count stands. No model call and no rules."""
    _, sent_rows, out = _unread(rows, as_of)
    out["not_read"] = [r["work_permit"] for r in sent_rows]
    out["why_none"] = why
    return out


def read_permits(rows, as_of=None, client=None, model=None):
    """The permits on the block, read, and at most one adjustment for the construction source.

    rows    permit rows as sources.dob_permits returns them; filtered and scrubbed here [P1]
    client  a backend from llm.client_for (Meta, OpenAI or Anthropic), or an OpenAI-SDK client for the Meta Model
            API; None reads with the rules [P4]
    The model path adds `usage` and `failure` (null, or key_rejected, provider_busy, provider_error).
    """
    as_of, sent_rows, out = _unread(rows, as_of)
    sent = {r["work_permit"]: r for r in sent_rows}
    if not sent_rows:
        out["why_none"] = "no unexpired loud-work or scaffold permit on this tax block"
        return out

    if client is None:
        out["reader"] = "rules"
        read = {}
        for row in sent_rows:
            try:
                r = check_reading(rules_reading(row), sent)
                read[r["id"]] = r
            except Refused as e:   # the rules obey the same gate; a refusal here is a bug in a pattern
                out["refusals"].append({"tool": "read_permits", "id": row["work_permit"], "why": str(e)})
        adj, why = rules_adjustment(read, sent)
        trace = [{"turn": 0, "tool": "rules", "accepted": list(read)}]
    else:
        backend = as_backend(client, model or A.MODEL_DEFAULT)
        out["reader"] = backend.model
        read, adj, why, trace, usage, out["failure"] = model_read(sent_rows, as_of, backend, backend.model)
        out["usage"] = _total(usage)
        for t in trace:
            if isinstance(t.get("refused"), list):
                out["refusals"] += [{"tool": t["tool"], **r} for r in t["refused"]]
            elif t.get("refused"):
                out["refusals"].append({"tool": t["tool"], "why": t["refused"]})

    out["readings"] = [read[p] for p in sent if p in read]
    out["not_read"] = [p for p in sent if p not in read]
    out["adjustment"], out["why_none"], out["trace"] = adj, why, trace
    return out
