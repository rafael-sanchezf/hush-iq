"""Evidence: an engine score, the renter's answers and the reader's fields, as numbered lines E1..En.

One fact per line, in words a renter can read. Every number in a line is a rank, a weight, a floor, a count, a
distance, an hour or a date; never a decibel (V8 in packages/model/ENGINE_V2.md). The lines are the only thing
the writer may cite, so a fact that is not here cannot reach a renter.

Engine v2 is the main input (`engine: "v2"`); a v1 response is accepted as a fallback and yields fewer lines
(no per-source ranks, no weights, no range). Licensee names on liquor licenses are dropped: they are legal
entities, not the bar's name, and some are people.
"""
import datetime as dt
import re
from dataclasses import dataclass, field

SOURCES = ("street", "nightlife", "building", "sirens", "construction")
VERDICTS = ("Very loud", "Loud", "Typical", "Quiet", "Very quiet")
LABEL = {"street": "Street", "nightlife": "Nightlife", "building": "Neighbors", "sirens": "Sirens",
         "construction": "Construction"}
NOUN = {"street": "street noise", "nightlife": "nightlife", "building": "neighbor noise", "sirens": "sirens",
        "construction": "construction"}
PLURAL = {"sirens"}
TICK_TO_SOURCE = {"traffic": "street", "people": "nightlife", "neighbors": "building", "sirens": "sirens",
                  "construction": "construction"}
SOURCE_TO_TICK = {v: k for k, v in TICK_TO_SOURCE.items()}
TICK_PHRASE = {"traffic": "traffic bothers you", "people": "people and nightlife bother you",
               "neighbors": "neighbors bother you", "sirens": "sirens bother you",
               "construction": "construction bothers you"}
# The engine's time slots, from WINDOWS in packages/model/noise_score/config.py.
SLOT_WORDS = {"night": "night (10 pm to 5 am)", "early": "early morning (5 to 8 am)", "day": "daytime (8 am to 10 pm)"}

DECIBEL = re.compile(r"(?i)decibel|\bd\s?b(?:a\b|\(a\)|\b)|(?<=\d)\s?dba?\b")
_DB_WITH_NUMBER = re.compile(r"(?i)\d+(?:\.\d+)?\s*(?:d\s?b(?:a\b|\(a\)|\b)|decibels?)|decibels?|\bdba?\b")


class EvidenceError(ValueError):
    """The score is not an engine response this module can read."""


@dataclass
class Line:
    id: str
    text: str
    kind: str                  # verdict | cap | rank | weight | detail | temporary | bothers | hours | daytime |
    source: str | None = None  # time_split | floor | side | unit | commercial | range | method | address
    data: dict = field(default_factory=dict)

    def public(self):
        return {"id": self.id, "text": self.text, "kind": self.kind, "source": self.source}


# ---------------------------------------------------------------- small words
def pct(x):
    """A rank or weight as a whole percent, half up."""
    return int(float(x) + 0.5)


def hour_words(h):
    h = int(h) % 24
    if h == 0:
        return "midnight"
    if h == 12:
        return "noon"
    return f"{h} am" if h < 12 else f"{h - 12} pm"


def side_words(side):
    return {"front": "facing the street", "rear": "at the rear"}.get(side, "side unknown")


def date_words(iso):
    try:
        d = dt.date.fromisoformat(iso[:10])
    except (TypeError, ValueError):
        return None
    return f"{d.strftime('%B')} {d.day}, {d.year}"


_KEEP_UPPER = {"Nypd": "NYPD", "Fdny": "FDNY", "Ems": "EMS", "Nyc": "NYC", "Ny": "NY", "Usa": "USA", "Fdr": "FDR"}


def tidy(s):
    """Collapse spaces; title-case a name that came in capitals ("CLAREMONT AVE" -> "Claremont Ave")."""
    s = " ".join(str(s).split())
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        s = s.title()
        s = re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), s)
        s = re.sub(r"\b[A-Z][a-z]+\b", lambda m: _KEEP_UPPER.get(m.group(0), m.group(0)), s)
    return s


def scrub(s):
    """No decibels anywhere, not even inside a listing quote."""
    return _DB_WITH_NUMBER.sub("[sound level removed]", s)


def _short(q, n=120):
    q = " ".join(str(q).split()).strip().strip("\"'“”")
    if len(q) > n:
        q = q[:n].rsplit(" ", 1)[0] + "…"
    return scrub(q)


def _plural(n, one, many):
    return one if int(n) == 1 else many


# ---------------------------------------------------------------- the engine's own evidence, made readable
_ROAD = re.compile(r"^(?P<name>.+?): (?P<cls>highway|ramp|bridge|arterial|two lane|one lane), (?P<lanes>\d+) travel lanes?, "
                   r"(?P<mph>\d+) mph(?P<bus>, bus or truck route)?, (?P<d>\d+) m away$")
_RAIL = re.compile(r"^(?P<structure>.+?) subway \((?P<routes>[^)]*)\) at (?P<stop>.+), (?P<d>\d+) m away$")
_VEHICLE = re.compile(r"^(?P<n>\d+) vehicle noise complaints to 311 within (?P<r>\d+) m in (?P<months>\d+) months(?P<rest>.*)$")
_VENUES = re.compile(r"^(?P<n>\d+) licensed venues within (?P<r>\d+) m: (?P<kinds>.+)$")
_NO_VENUES = re.compile(r"^no licensed bar or restaurant within (?P<r>\d+) m$")
_VENUE = re.compile(r"^nearest loud: (?P<name>.+) \((?P<kind>bar|restaurant|venue)\), (?P<addr>.+), (?P<d>\d+) m$")
_PARTY = re.compile(r"^(?P<n>\d+) party, music or loud-talking complaints within (?P<r>\d+) m in (?P<months>\d+) months; "
                    r"(?P<night>\d+) of them 10 pm to 5 am$")
_RESIDENTIAL = re.compile(r"^(?P<n>\d+) residential noise complaints to 311 at this building in (?P<months>\d+) months, "
                          r"(?P<units>\d+) units: [\d.]+ per unit-year vs [\d.]+ for (?P<boro>[A-Za-z ]+) "
                          r"\((?P<x>[\d.]+)x after shrinkage\)(?P<rest>.*)$")
_BUILT = re.compile(r"^built (?P<yb>\d{4})(?:: (?P<desc>.+))?$")
_WALKUP = re.compile(r"^class \w+: walk-up, stairs pass every door$")
_ELEVATOR = re.compile(r"^class \w+: elevator building$")
_HOURS = re.compile(r"^complaint hours at this building: night (?P<night>\d+), early (?P<early>\d+), day (?P<day>\d+)$")
_FACILITIES = re.compile(r"^(?P<n>\d+) emergency facilities within (?P<r>\d+) m: (?P<kinds>.+)$")
_FACILITY = re.compile(r"^(?P<name>.+) \((?P<kind>hospital|firehouse|police station)\), (?:(?P<addr>.+), )?(?P<d>\d+) m$")
_BUILD_311 = re.compile(r"^(?P<n>\d+) construction noise complaints within (?P<r>\d+) m in (?P<months>\d+) months(?P<rest>.*)$")
_PERMITS = re.compile(r"^(?P<n>\d+) unexpired loud-work permits on this tax block: (?P<kinds>.+)$")
_PERMIT = re.compile(r"^(?P<addr>.+): (?P<wt>[A-Za-z ]+) to (?P<date>[\d-]*)$")

_ERA = {"pre-war walk-up, wood joists and plaster carry footsteps": "a pre-war walk-up, where wood joists and plaster carry footsteps",
        "pre-war elevator building, masonry and plaster": "a pre-war elevator building of masonry and plaster",
        "post-2000, likely concrete slab": "likely with concrete floor slabs"}


def _rest(rest):
    """The engine's "(top descriptors)" tail, without 311's internal codes."""
    rest = re.sub(r"\s*\([a-z]{2}\d\)", "", rest).replace("noise: ", "")
    return rest.strip()


def detail(source, raw):
    """One engine evidence string -> (text, data), or None to drop it. Unknown shapes pass through as they are."""
    s = " ".join(str(raw).split())
    label = LABEL[source]
    if m := _ROAD.match(s):
        g = m.groupdict()
        parts = [f"{tidy(g['name'])}, {g['d']} m away"]
        if g["cls"] in ("highway", "ramp", "bridge"):
            parts.append(f"a {g['cls']}")
        parts += [f"{g['lanes']} travel {_plural(g['lanes'], 'lane', 'lanes')}", f"{g['mph']} mph"]
        if g["bus"]:
            parts.append("a bus or truck route")
        return f"{label}: " + ", ".join(parts) + ".", {"type": "road", "name": tidy(g["name"]), "d": int(g["d"]),
                                                     "cls": g["cls"], "bus": bool(g["bus"])}
    if m := _RAIL.match(s):
        g = m.groupdict()
        return (f"{label}: {g['structure'].lower()} subway ({g['routes']}) at the {tidy(g['stop'])} station, {g['d']} m away.",
                {"type": "rail", "structure": g["structure"].lower(), "stop": tidy(g["stop"]), "d": int(g["d"])})
    if m := _VEHICLE.match(s):
        g = m.groupdict()
        rest = _rest(g["rest"])
        return (f"{label}: {g['n']} vehicle noise complaints to 311 within {g['r']} m in {g['months']} months"
                + (f" {rest}" if rest else "") + ".", {"type": "complaints", **{k: int(g[k]) for k in ("n", "r", "months")}})
    if s == "no road segment within radius":
        return f"{label}: no road segment close by.", {"type": "none"}
    if m := _VENUES.match(s):
        g = m.groupdict()
        n = int(g["n"])
        return (f"{label}: {n} licensed {_plural(n, 'venue', 'venues')} within {g['r']} m ({g['kinds']}).",
                {"type": "count", "n": n, "r": int(g["r"])})
    if m := _NO_VENUES.match(s):
        return f"{label}: no licensed bar or restaurant within {m['r']} m.", {"type": "none", "r": int(m["r"])}
    if m := _VENUE.match(s):
        g = m.groupdict()
        kind = {"bar": "a bar", "restaurant": "a restaurant", "venue": "a licensed venue"}[g["kind"]]
        return (f"{label}: {kind} at {tidy(g['addr'])}, {g['d']} m away.",
                {"type": "venue", "kind": kind, "addr": tidy(g["addr"]), "d": int(g["d"])})
    if m := _PARTY.match(s):
        g = m.groupdict()
        return (f"{label}: {g['n']} party, music or loud-talking complaints to 311 within {g['r']} m in {g['months']} "
                f"months, {g['night']} of them between 10 pm and 5 am.",
                {"type": "complaints", **{k: int(g[k]) for k in ("n", "r", "months", "night")}})
    if s == "commercial space on the ground floor of this building":
        return f"{label}: commercial space on the ground floor of this building.", {"type": "commercial"}
    if m := _RESIDENTIAL.match(s):
        g = m.groupdict()
        rest = _rest(g["rest"])
        return (f"{label}: {g['n']} residential noise complaints to 311 at this building in {g['months']} months, "
                f"across {g['units']} {_plural(g['units'], 'apartment', 'apartments')}" + (f" {rest}" if rest else "") + ".",
                {"type": "complaints", "n": int(g["n"]), "months": int(g["months"]), "units": int(g["units"]),
                 "x": g["x"], "boro": g["boro"]})
    if s == "residential unit count unknown; treated as one unit":
        return f"{label}: the number of apartments is not on record, so the building counts as one.", {"type": "units_unknown"}
    if m := _BUILT.match(s):
        g = m.groupdict()
        era = _ERA.get(g["desc"] or "", g["desc"])
        return (f"{label}: built {g['yb']}" + (f", {era}" if era else "") + ".",
                {"type": "era", "yb": int(g["yb"]), "era": era, "walkup": "walk-up" in (era or "")})
    if _WALKUP.match(s):
        return f"{label}: a walk-up, so the stairs pass every door.", {"type": "walkup"}
    if _ELEVATOR.match(s):
        return f"{label}: an elevator building.", {"type": "elevator"}
    if m := _HOURS.match(s):
        g = m.groupdict()
        return (f"{label}: of those complaints, {g['night']} came at night (10 pm to 5 am), {g['early']} early in the "
                f"morning (5 to 8 am) and {g['day']} in the day.", {"type": "hours"})
    if m := _FACILITIES.match(s):
        g = m.groupdict()
        n = int(g["n"])
        return (f"{label}: {n} emergency {_plural(n, 'facility', 'facilities')} within {g['r']} m ({g['kinds']}).",
                {"type": "count", "n": n, "r": int(g["r"])})
    if m := _FACILITY.match(s):
        g = m.groupdict()
        where = f" at {tidy(g['addr'])}" if g["addr"] else ""
        return (f"{label}: {tidy(g['name'])}, a {g['kind']}{where}, {g['d']} m away.",
                {"type": "facility", "name": tidy(g["name"]), "kind": g["kind"], "d": int(g["d"])})
    if m := _BUILD_311.match(s):
        g = m.groupdict()
        rest = _rest(g["rest"])
        return (f"{label}: {g['n']} construction noise complaints to 311 within {g['r']} m in {g['months']} months"
                + (f" {rest}" if rest else "") + ".", {"type": "complaints", **{k: int(g[k]) for k in ("n", "r", "months")}})
    if m := _PERMITS.match(s):
        g = m.groupdict()
        n = int(g["n"])
        return (f"{label}: {n} unexpired loud-work {_plural(n, 'permit', 'permits')} on this tax block ({g['kinds']}).",
                {"type": "permits", "n": n})
    if source == "construction" and (m := _PERMIT.match(s)):
        g = m.groupdict()
        until = date_words(g["date"])
        return (f"{label}: a {g['wt'].strip().lower()} permit at {tidy(g['addr'])}, "
                + (f"open until {until}." if until else "with no end date on record."),
                {"type": "permit", "addr": tidy(g["addr"]), "work": g["wt"].strip().lower(), "until": until})
    if s == "no construction complaints or loud-work permits nearby":
        return f"{label}: no construction complaints or loud-work permits nearby.", {"type": "none"}
    if s.startswith("no hospital, firehouse or police station within"):
        return f"{label}: {s}.", {"type": "none"}
    return f"{label}: {scrub(s)}.", {"type": "other"}


_KEEP = {"street": {"road": 2, "rail": 2, "complaints": 1}, "nightlife": {"venue": 2}, "sirens": {"facility": 2},
         "construction": {"permit": 2}}


def details(source, raws):
    """The readable lines for one source, capped per type and without repeats (one venue can hold two licenses)."""
    out, seen, counts = [], set(), {}
    for raw in raws or []:
        text, data = detail(source, raw)
        key = (data.get("type"), data.get("addr") or data.get("name") or text)
        if key in seen:
            continue
        cap = _KEEP.get(source, {}).get(data["type"])
        if cap is not None and counts.get(data["type"], 0) >= cap:
            continue
        seen.add(key)
        counts[data["type"]] = counts.get(data["type"], 0) + 1
        out.append((text, data))
    if any(d.get("type") == "era" and "elevator" in (d.get("era") or "") for _, d in out):
        out = [(t, d) for t, d in out if d.get("type") != "elevator"]
    return out


# ---------------------------------------------------------------- the reader's fields
def quote(f):
    """How the reader knew a field: a quoted line of the listing or what a photo showed. None if it could not tell."""
    if not isinstance(f, dict) or f.get("status") != "read":
        return None
    for e in f.get("evidence") or []:
        src = str(e.get("source") or "")
        if src == "text" and e.get("quote"):
            return f'read from the listing: "{_short(e["quote"])}"'
        if src.startswith("photo:") and e.get("what"):
            try:
                n = int(src.split(":", 1)[1]) + 1
            except ValueError:
                n = None
            return (f"seen in photo {n}: " if n else "seen in a photo: ") + _short(e["what"])
    return "read from the listing"


def field_value(f):
    return f.get("value") if isinstance(f, dict) and f.get("status") == "read" else None


# ---------------------------------------------------------------- the lines
class _Lines:
    def __init__(self):
        self.items = []

    def add(self, kind, text, source=None, /, **data):
        self.items.append((kind, source, text, data))


def build(score, answers=None, fields=None):
    """Score + answers + fields -> [Line] numbered E1..En. For v2 the answers the engine echoes win: its numbers came
    from them. The request's answers fill in for a v1 score."""
    if not isinstance(score, dict):
        raise EvidenceError("score must be an object")
    fields = fields if isinstance(fields, dict) else {}
    if score.get("engine") == "v2":
        if not isinstance(score.get("ingredients"), list) or "verdict" not in score:
            raise EvidenceError("engine v2 score without verdict or ingredients")
        out = _v2(score, fields)
    elif isinstance(score.get("ingredients"), list) and "score" in score:
        out = _v1(score, answers if isinstance(answers, dict) else {}, fields)
    else:
        raise EvidenceError("score is neither an engine v2 nor a v1 response")
    lines = [Line(id=f"E{i}", text=scrub(text), kind=kind, source=source, data=data)
             for i, (kind, source, text, data) in enumerate(out.items, 1)]
    for line in lines:
        assert not DECIBEL.search(line.text), line.text
    return lines


def _ingredients(score):
    return {i.get("name"): i for i in score.get("ingredients") or [] if i.get("name") in SOURCES}


def _v2(score, fields):
    out = _Lines()
    ings = _ingredients(score)
    a = score.get("answers") or {}
    sleep = a.get("sleep") or {}
    ticks = [t for t in a.get("ticks") or [] if t in TICK_TO_SOURCE]
    ticked = {TICK_TO_SOURCE[t] for t in ticks}
    verdict, uncapped = score["verdict"], score.get("uncapped_verdict") or score["verdict"]

    q = pct(score["quieter_than"])
    out.add("verdict", f"Verdict for you: {verdict}, quieter than {q}% of Manhattan apartments.",
            verdict=verdict, quieter_than=q)

    caps = {}   # [V6] per source: the caps that bit, else the strictest one that would have
    for c in score.get("caps") or []:
        caps.setdefault(c.get("source"), []).append(c)
    for src, cs in caps.items():
        if src not in SOURCES:
            continue
        chosen = [c for c in cs if c.get("applied")] or [min(cs, key=lambda c: VERDICTS.index(c["cap"]))]
        for c in chosen:
            m = re.search(r"loudest (\d+(?:\.\d+)?)%", c.get("why") or "")
            verb = "are" if src in PLURAL else "is"
            reason = (f"{NOUN[src]} {verb} in Manhattan's loudest {m.group(1)}%" if m
                      else f"{NOUN[src]} {verb} among Manhattan's loudest")
            if "bothers you" in (c.get("why") or ""):
                reason += " and you said it bothers you"
            if c.get("applied"):
                text = f"Cap: {reason}, which holds the verdict at {c['cap']}; without the cap it would be {uncapped}."
            else:
                text = f"Cap not needed: {reason}, which would hold the verdict at {c['cap']}; it is already {verdict}."
            out.add("cap", text, src, cap=c["cap"], applied=bool(c.get("applied")), uncapped=uncapped,
                    pct=m.group(1) if m else None)

    def weight_of(n):
        return float(ings.get(n, {}).get("weight") or 0)

    for n in sorted(ings, key=lambda n: -weight_of(n)):
        ing = ings[n]
        r = pct(ing.get("quieter_than", 0))
        v = ing.get("verdict") or VERDICTS[max(0, min(int(float(ing.get("quieter_than", 0)) // 20), 4))]
        out.add("rank", f"{LABEL[n]}: {v}, quieter than {r}% of Manhattan apartments for {NOUN[n]}.", n,
                verdict=v, quieter_than=r)
        w = pct(weight_of(n))
        if n in ticked:
            why = f"counted three times because you said {TICK_PHRASE[SOURCE_TO_TICK[n]]}"
        elif ticked:
            why = "its default share from NYC health department noise surveys, scaled down because you ticked other sources"
        else:
            why = "its default share from NYC health department noise surveys"
        out.add("weight", f"{LABEL[n]} weight: {w}% of the verdict, {why}.", n, weight=w, ticked=n in ticked)
        for text, data in details(n, ing.get("evidence")):
            out.add("detail", text, n, **data)
        if ing.get("temporary") and any(d.get("type") in ("complaints", "permits", "permit") for _, d in details(n, ing.get("evidence"))):
            out.add("temporary", f"{LABEL[n]} is temporary: permits expire.", n)

    _renter(out, sleep.get("from", 23), sleep.get("until", 7), a.get("day_bothers", True), ticks)
    sw = score.get("slot_weights") or {}
    if all(k in sw for k in SLOT_WORDS):
        out.add("time_split", "Time of day in the verdict: " + ", ".join(
            f"{SLOT_WORDS[k]} {pct(sw[k])}%" for k in SLOT_WORDS) + ".", **{k: pct(sw[k]) for k in SLOT_WORDS})

    u = score.get("unit") or {}
    floor, floors = u.get("floor"), u.get("building_floors")
    floor_from, side_from, side = u.get("floor_from"), u.get("side_from"), u.get("side") or "unknown"
    _floor(out, floor, floors, "listing" if floor_from == "listing" else floor_from, fields)
    _side(out, side if side_from == "listing" else "unknown", "listing", fields)
    _unit(out, fields)
    if u.get("ground_floor_commercial"):
        out.add("commercial", "The building has commercial space on the ground floor, so apartments start on floor 2.")

    rng = score.get("range")   # [V7]
    if isinstance(rng, dict):
        for case, name, where in (("loudest_case", "Loudest", "the lowest apartment floor"),
                                  ("quietest_case", "Quietest", "the top floor")):
            c = rng.get(case)
            if not c:
                continue
            fl = c.get("floor")
            at = (f"floor {fl}" + (f", {where}" if floor_from != "listing" else "")) if fl is not None else "floor unknown"
            cq = pct(c.get("quieter_than", 0))
            out.add("range", f"{name} case for this listing: {at}, {side_words(c.get('side'))}: {c.get('verdict')}, "
                    f"quieter than {cq}% of Manhattan apartments.", case=case, floor=fl, side=c.get("side"),
                    verdict=c.get("verdict"), quieter_than=cq)
    _method(out, score.get("manhattan"))
    _address(out, score.get("address"))
    return out


def _v1(score, answers, fields):
    out = _Lines()
    ings = _ingredients(score)
    m = score.get("manhattan") or {}
    if m.get("verdict") is not None and m.get("quieter_than") is not None:
        q = pct(m["quieter_than"])
        out.add("verdict", f"Verdict for you: {m['verdict']}, quieter than {q}% of Manhattan apartments.",
                verdict=m["verdict"], quieter_than=q)
    prof = score.get("profile") or {}
    ticks = [t for t in (answers.get("bothers") if "bothers" in answers else prof.get("bothers")) or [] if t in TICK_TO_SOURCE]
    up = [n for n in ings if ings[n].get("weighted_up")]
    for n in sorted(ings, key=lambda n: (n not in up, SOURCES.index(n))):
        if n in up:
            tick = SOURCE_TO_TICK[n]
            out.add("weight", f"{LABEL[n]} {'are' if n in PLURAL else 'is'} weighted up because you said {TICK_PHRASE[tick]}.",
                    n, ticked=True)
        for text, data in details(n, ings[n].get("evidence")):
            out.add("detail", text, n, **data)
        if ings[n].get("temporary") and any(d.get("type") in ("complaints", "permits", "permit") for _, d in details(n, ings[n].get("evidence"))):
            out.add("temporary", f"{LABEL[n]} is temporary: permits expire.", n)
    if "sleep_from" in answers or "sleep_until" in answers or "day_bothers" in answers or ticks:
        _renter(out, answers.get("sleep_from", 23), answers.get("sleep_until", 7), answers.get("day_bothers", True), ticks)
    u = score.get("unit") or {}
    floor, pos = u.get("floor"), u.get("position") or "unknown"
    read_floor = field_value(fields.get("floor"))
    _floor(out, floor, u.get("building_floors"), "listing" if floor is not None and str(read_floor) == str(floor)
           else ("given" if floor is not None else None), fields)
    read_side = field_value(fields.get("side"))
    _side(out, pos if pos in ("front", "rear") else "unknown", "listing" if read_side == pos else "given", fields)
    _unit(out, fields)
    if m.get("buildings"):
        _method(out, m)
    _address(out, score.get("address"))
    return out


def _renter(out, sleep_from, sleep_until, day_bothers, ticks):
    if ticks:
        out.add("bothers", "You said these bother you: " + ", ".join(
            {"people": "people and nightlife"}.get(t, t) for t in ticks) + ".", ticks=list(ticks))
    else:
        out.add("bothers", "You did not tick any source as bothering you, so each keeps its default weight.", ticks=[])
    if int(sleep_from) % 24 != int(sleep_until) % 24:
        out.add("hours", f"You sleep from {hour_words(sleep_from)} to {hour_words(sleep_until)}; each hour asleep counts "
                "three times an hour awake.", sleep_from=int(sleep_from), sleep_until=int(sleep_until))
    if day_bothers:
        out.add("daytime", "Daytime noise bothers you, so your waking hours count in full.", day_bothers=True)
    else:
        out.add("daytime", "Daytime noise does not bother you, so your waking hours count half.", day_bothers=False)


def _floor(out, floor, floors, how, fields):
    of = f" of {floors}" if floors else ""
    if floor is None:
        out.add("floor", "Floor unknown: the listing does not give one and the building's height is not on record.",
                floor=None, how=None)
    elif how == "listing":
        out.add("floor", f"Floor {floor}{of}, {quote(fields.get('floor')) or 'read from the listing'}.", floor=floor, how="listing")
    elif how == "expected":
        out.add("floor", f"Floor {floor} assumed: the listing does not give one, so this uses the middle apartment floor"
                + (f" of the building's {floors} floors." if floors else "."), floor=floor, how="expected")
    else:
        out.add("floor", f"Floor {floor}{of}, as sent with the score.", floor=floor, how="given")


def _side(out, side, how, fields):
    if side in ("front", "rear"):
        said = (quote(fields.get("side")) or "read from the listing") if how == "listing" else "as sent with the score"
        out.add("side", f"{'Facing the street' if side == 'front' else 'Facing the rear'}, {said}.", side=side, how=how)
    else:
        out.add("side", "Side unknown: the listing does not say whether the apartment faces the street or the rear.",
                side="unknown", how=None)


def _unit(out, fields):
    v = field_value(fields.get("unit"))
    if v:
        out.add("unit", f"Apartment {_short(v, 20)}, {quote(fields.get('unit'))}.", unit=str(v))


def _method(out, m):
    if isinstance(m, dict) and m.get("buildings"):
        out.add("method", f"Every rank compares this apartment with {m['buildings']} Manhattan buildings sampled by "
                "number of apartments, each at a typical apartment.", buildings=m["buildings"])


def _address(out, a):
    label = (a or {}).get("label") if isinstance(a, dict) else None
    if label:
        label = re.sub(r",\s*USA$", "", label)
        head, _, tail = label.partition(",")
        out.add("address", f"Address scored: {tidy(head)}{',' + tail if tail else ''}.", label=tidy(head))
