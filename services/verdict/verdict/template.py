"""The template writer: the reply shape the model is held to, written from the evidence lines alone.

It is the fallback when the model fails its checks twice or does not answer, and the writer when no key is set,
so it has to read well on its own. It says, in order: the verdict for this renter; the cap, if one held the
verdict down; the loudest source and what is behind it; the sources the renter said bother them; the floor and
side used; the range when the listing was silent. At most six sentences, each citing the lines it states, and it
passes the same checks as the model (validate.check), which the tests enforce.
"""
from .evidence import NOUN, PLURAL, SOURCE_TO_TICK, TICK_PHRASE, side_words
from .validate import MAX_SENTENCES


def _be(src):
    return "are" if src in PLURAL else "is"


def _it(src):
    return "they" if src in PLURAL else "it"


def _counts(src):
    return "count" if src in PLURAL else "counts"


def _cap(s):
    return s[:1].upper() + s[1:]


def _low(s):
    return s[:1].lower() + s[1:]


def _rank(r):
    """A rank in words: the ends read as words, the middle keeps its number."""
    if r <= 0:
        return "among the loudest in Manhattan"
    if r >= 100:
        return "among the quietest in Manhattan"
    return f"quieter than {r}% of Manhattan apartments"


class _Index:
    def __init__(self, lines):
        self.lines = lines

    def all(self, kind, source=None, **match):
        return [l for l in self.lines if l.kind == kind and (source is None or l.source == source)
                and all(l.data.get(k) == v for k, v in match.items())]

    def one(self, kind, source=None, **match):
        found = self.all(kind, source, **match)
        return found[0] if found else None


# ---------------------------------------------------------------- what is behind a source
def _behind(ix, src):
    """One sentence on what the records show for a source: (text, [ids]) or None."""
    if src == "street":
        road, rail, c311 = ix.one("detail", src, type="road"), ix.one("detail", src, type="rail"), ix.one("detail", src, type="complaints")
        parts, ids = [], []
        if road:
            d = road.data
            kind = f", a {d['cls']}" if d["cls"] in ("highway", "ramp", "bridge") else ""
            parts.append(f"the nearest road is {d['name']}{kind}, {d['d']} m away" + (", a bus or truck route" if d["bus"] else ""))
            ids.append(road.id)
        if rail:
            d = rail.data
            parts.append(f"an {d['structure']} subway stops at the {d['stop']} station, {d['d']} m away")
            ids.append(rail.id)
        if c311 and len(parts) < 2:
            d = c311.data
            parts.append(f"311 logged {d['n']:,} vehicle noise complaints within {d['r']} m in {d['months']} months")
            ids.append(c311.id)
        return (_cap(", and ".join(parts)) + ".", ids) if parts else None
    if src == "nightlife":
        count, venue, party = ix.one("detail", src, type="count"), ix.one("detail", src, type="venue"), ix.one("detail", src, type="complaints")
        none = ix.one("detail", src, type="none")
        if party and party.data["n"] >= 100:
            d = party.data
            return (f"311 logged {d['n']:,} party, music or loud-talking complaints within {d['r']} m in {d['months']} "
                    f"months, {d['night']:,} of them between 10 pm and 5 am.", [party.id])
        if count:
            n = count.data["n"]
            text = f"There {'is' if n == 1 else 'are'} {n} licensed {'venue' if n == 1 else 'venues'} within {count.data['r']} m"
            if venue:
                text += f", the nearest {venue.data['kind']} at {venue.data['addr']}, {venue.data['d']} m away"
                return text + ".", [count.id, venue.id]
            return text + ".", [count.id]
        if none:
            return f"There is no licensed bar or restaurant within {none.data['r']} m.", [none.id]
        return None
    if src == "building":
        c, era = ix.one("detail", src, type="complaints"), ix.one("detail", src, type="era")
        unknown = ix.one("detail", src, type="units_unknown")
        parts, ids = [], []
        if c:
            d = c.data
            if d["n"] == 0:
                parts.append(f"no residential noise complaints reached 311 from this building in {d['months']} months")
            elif unknown:
                parts.append(f"311 logged {d['n']} residential noise complaints at this building in {d['months']} months")
            else:
                parts.append(f"311 logged {d['n']} residential noise complaints at this building in {d['months']} months, "
                             f"across {d['units']} {'apartment' if d['units'] == 1 else 'apartments'}")
            ids.append(c.id)
        if era and era.data.get("walkup"):
            parts.append(f"it is {era.data['era']}")
            ids.append(era.id)
        if not parts:
            return None
        joint = ", but " if c and c.data["n"] == 0 and len(parts) > 1 else ", and "
        return _cap(joint.join(parts)) + ".", ids
    if src == "sirens":
        count, fac, none = ix.one("detail", src, type="count"), ix.one("detail", src, type="facility"), ix.one("detail", src, type="none")
        if fac:
            d = fac.data
            article = "an" if d["kind"][0] in "aeiou" else "a"
            name = d["name"] if d["kind"].split()[0].lower() in d["name"].lower() else f"{d['name']}, {article} {d['kind']}"
            if count and count.data["n"] > 1:
                return (f"There are {count.data['n']} emergency facilities within {count.data['r']} m; the nearest is "
                        f"{name}, {d['d']} m away.", [count.id, fac.id])
            return f"The nearest emergency facility is {name}, {d['d']} m away.", [fac.id]
        if none:
            return "There is no hospital, firehouse or police station close by.", [none.id]
        return None
    if src == "construction":
        permits, c, temp = ix.one("detail", src, type="permits"), ix.one("detail", src, type="complaints"), ix.one("temporary", src)
        none = ix.one("detail", src, type="none")
        tail = ([temp.id], "; construction is temporary, and permits expire.") if temp else ([], ".")
        if permits:
            n = permits.data["n"]
            return (f"There {'is' if n == 1 else 'are'} {n} unexpired loud-work {'permit' if n == 1 else 'permits'} on "
                    f"this tax block" + tail[1], [permits.id] + tail[0])
        if c:
            d = c.data
            return (f"311 logged {d['n']} construction noise complaints within {d['r']} m in {d['months']} months"
                    + tail[1], [c.id] + tail[0])
        if none:
            return "There are no construction complaints or loud-work permits nearby.", [none.id]
    return None


# ---------------------------------------------------------------- the paragraph
def write(lines):
    """The evidence lines -> {"sentences": [{text, cites}]}, deterministic."""
    ix = _Index(lines)
    picks = []   # (priority, text, ids); lower priority numbers survive the six-sentence limit

    def say(priority, text, ids):
        if text and ids:
            picks.append((priority, len(picks), text, list(dict.fromkeys(ids))))

    verdict, hours = ix.one("verdict"), ix.one("hours")
    if verdict:
        lead = "For the way you sleep, this" if hours else "This"
        say(0, f"{lead} apartment is {verdict.data['verdict'].lower()}: {_rank(verdict.data['quieter_than'])}.",
            [verdict.id] + ([hours.id] if hours else []))
    else:
        say(0, "Here is what the city's records show around this building.", [lines[0].id])

    for cap in ix.all("cap", applied=True)[:1]:
        src = cap.source
        reason = (f"{NOUN[src]} {_be(src)} in Manhattan's loudest {cap.data['pct']}%" if cap.data.get("pct")
                  else f"{NOUN[src]} {_be(src)} among Manhattan's loudest")
        if "bothers you" in cap.text:
            reason += f" and you said {_it(src)} {'bother' if src in PLURAL else 'bothers'} you"
        say(0, f"It would be {cap.data['uncapped'].lower()}, but {reason}, which holds the verdict at "
               f"{cap.data['cap'].lower()}.", [cap.id])

    ranks = ix.all("rank")
    weights = {l.source: l for l in ix.all("weight")}
    covered = set()
    if ranks:
        loudest = min(ranks, key=lambda l: l.data["quieter_than"])
        src, r, v = loudest.source, loudest.data["quieter_than"], loudest.data["verdict"].lower()
        w = weights.get(src)
        if w and w.data.get("ticked"):
            say(1, f"{_cap(NOUN[src])} {_be(src)} the loudest source here, and you said {_it(src)} "
                   f"{'bother' if src in PLURAL else 'bothers'} you: {v}, {_rank(r)}, "
                   f"counting for {w.data['weight']}% of the verdict.", [loudest.id, w.id])
        elif r < 40:
            say(1, f"The loudest source here is {NOUN[src]}: {v}, {_rank(r)}.", [loudest.id])
        else:
            say(1, f"Even the loudest source here, {NOUN[src]}, {_be(src)} {v}: quieter than {r}% of Manhattan "
                   "apartments.", [loudest.id])
        if b := _behind(ix, src):
            say(3, *b)
        covered.add(src)

        ticked = sorted((l for l in ranks if weights.get(l.source) and weights[l.source].data.get("ticked")
                         and l.source not in covered), key=lambda l: -weights[l.source].data["weight"])
        for i, rk in enumerate(ticked[:2]):
            s, w = rk.source, weights[rk.source]
            subject = _it(s) if SOURCE_TO_TICK[s] in ("sirens", "construction") else NOUN[s]
            say(2 + i * 2, f"You said {TICK_PHRASE[SOURCE_TO_TICK[s]]}, so {subject} {_counts(s)} for "
                           f"{w.data['weight']}% of the verdict; here {_it(s)} {_be(s)} {rk.data['verdict'].lower()}, "
                           f"{_rank(rk.data['quieter_than'])}.", [w.id, rk.id])
            if rk.data["quieter_than"] < 40 and (b := _behind(ix, s)):
                say(5, *b)
            covered.add(s)

        for rk in sorted(ranks, key=lambda l: l.data["quieter_than"]):
            if rk.source not in covered and rk.data["verdict"] == "Very loud":
                s = rk.source
                say(6, f"{_cap(NOUN[s])} {_be(s)} also very loud: {_rank(rk.data['quieter_than'])}.", [rk.id])
                break
    else:   # a v1 score: no ranks, so the sources the renter ticked, then the street
        for w in ix.all("weight", ticked=True)[:2]:
            if b := _behind(ix, w.source):
                say(2, f"You said {TICK_PHRASE[SOURCE_TO_TICK[w.source]]}: {_low(b[0])}", [w.id] + b[1])
                covered.add(w.source)
        if "street" not in covered and (b := _behind(ix, "street")):
            say(3, *b)

    floor, side = ix.one("floor"), ix.one("side")
    if floor and side:
        f, fhow, s, shside = floor.data.get("floor"), floor.data.get("how"), side.data.get("side"), side.data.get("how")
        sw = side_words(s)
        if fhow == "listing" and shside == "listing":
            text = f"This is for floor {f} {sw}, both read from the listing."
        elif fhow == "expected" and s == "unknown":
            text = f"The listing gives neither the floor nor the side, so this assumes floor {f}, the middle apartment floor."
        elif fhow == "expected":
            text = (f"The listing does not give the floor, so this assumes floor {f}, the middle apartment floor, "
                    f"{sw} as the listing says.")
        elif fhow == "listing":
            text = f"This is for floor {f}, read from the listing, which does not say which side the apartment faces."
        elif f is None:
            text = ("Neither the listing nor the city's records give a floor" +
                    (f", and the apartment is {sw}." if s != "unknown" else ", and the side is unknown."))
        else:
            text = f"This is for floor {f} {sw}." if s != "unknown" else f"This is for floor {f}, with the side unknown."
        say(4, text, [floor.id, side.id])

    loud, quiet = ix.one("range", case="loudest_case"), ix.one("range", case="quietest_case")
    if loud and quiet:
        ld, qd = loud.data, quiet.data
        if ld["verdict"] == qd["verdict"]:
            text = (f"Whatever the unit, it stays {ld['verdict'].lower()}: from quieter than {ld['quieter_than']}% of "
                    f"Manhattan apartments on floor {ld['floor']} {side_words(ld['side'])} to {qd['quieter_than']}% on "
                    f"floor {qd['floor']} {side_words(qd['side'])}.")
        else:
            text = (f"Depending on the unit, it runs from {ld['verdict'].lower()} on floor {ld['floor']} "
                    f"{side_words(ld['side'])} ({_rank(ld['quieter_than'])}) to "
                    f"{qd['verdict'].lower()} on floor {qd['floor']} {side_words(qd['side'])} ({qd['quieter_than']}%).")
        say(4, text, [loud.id, quiet.id])

    kept = sorted(sorted(picks)[:MAX_SENTENCES], key=lambda p: p[1])
    return {"sentences": [{"text": t, "cites": ids} for _, _, t, ids in kept]}
