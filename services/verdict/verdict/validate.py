"""The checks a reply must pass before a renter reads it. They run in code, on every reply, so no prompt can skip them.

A reply is {sentences: [{text, cites: [ids]}]}. For each sentence:

  C1 it cites at least one line, and every id it cites was sent
  C2 every number in it appears in a line it cites (digits, number words and "fourth floor" all count)
  C3 no decibel unit, anywhere
  C4 every name in it (a street, a building, a hospital, a borough) appears in a line it cites
  C5 every kind of source it mentions (a subway, a bar, a hospital, construction) appears in a line it cites
  C6 no evidence id in the text itself, and no sentence longer than MAX_CHARS

The template passes the same checks; the tests hold it to them.
"""
import json
import re

from .evidence import DECIBEL

MAX_SENTENCES = 6
MAX_CHARS = 320


# ---------------------------------------------------------------- parsing
def parse(raw):
    """A model's reply (a JSON string, or an already decoded object) -> (dict or None, [errors])."""
    if isinstance(raw, dict):
        return raw, []
    if not isinstance(raw, str) or not raw.strip():
        return None, ["the reply is empty"]
    s = re.sub(r"(?s)<think>.*?</think>", "", raw).strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        return None, [f"the reply is not valid JSON ({e.msg} at character {e.pos})"]
    if not isinstance(obj, dict):
        return None, ["the reply must be a JSON object with a sentences list"]
    return obj, []


# ---------------------------------------------------------------- C2 numbers
_NUMBER_WORDS = {"zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
                 "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                 "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
             "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
             "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20}
_ORDINAL_PLACE = re.compile(r"\b(" + "|".join(_ORDINALS) + r")\s+(?:floor|stor(?:y|ey)|street|st|avenue|ave)\b", re.I)
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.I)
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def _canon(n):
    f = float(n)
    return str(int(f)) if f == int(f) else repr(f)


def numbers(text):
    """Every number a reader would see in a text, in one canonical form: "1,670" and "1670" match, "4.0" is "4"."""
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    t = re.sub(r"(?<=\d):00\b", "", t)
    out = {_canon(m) for m in _DIGITS.findall(t)}
    out |= {_canon(_NUMBER_WORDS[m.lower()]) for m in _NUMBER_WORD.findall(t)}
    out |= {_canon(_ORDINALS[m.lower()]) for m in _ORDINAL_PLACE.findall(t)}
    return out


# ---------------------------------------------------------------- C4 names
# Words that may start or sit in a sentence without being a name. Place words (street, avenue, park, hospital,
# station) are deliberately absent: a capitalised one is part of a name and must be in a cited line.
_COMMON = set("""
a about above across after again against all almost also although always among an and another any anything are
around as at away back be because been before behind being below between both but by can cannot could daily day
days daytime depending despite do does down during each early even evening evenings every expect expected far few
for from front further given has have here how however if in inside into is it its just late least less like
likely little lot lots loud louder loudest low lower lowest many may mid middle more morning mornings most mostly
much near nearby nearest nearly next night nights nighttime no none nor not nothing now of off often on once one
only or other others otherwise our out outside over overall per perhaps quiet quieter quietest rarely rather rear
right round several she should side since so some sometimes still such than that the their them then there these
they this those though through throughout to today too toward towards typical under unless until up upon us very
was we weekday weekdays weekend weekends well were what when where whether which while who whom whose why will
with within without would yet you your yours
noise noises sound sounds traffic sirens siren nightlife neighbor neighbors neighbour neighbours construction
apartment apartments unit units building buildings floor floors listing verdict cap capped weight weighted
asleep awake sleep sleeping bedroom windows window quiet loud mainly also both things thing
besides beyond closest compared consider expect generally instead main meanwhile plus together unlike usually
whatever wherever worst best biggest bigger good bad great fine light heavy rest add note keep look think plan
light sleeper sleepers source sources records record city complaints complaint permits permit range case cases
afternoon afternoons midnight noon overnight weeknight weeknights nightly hourly between ever never there's
he her him his i'd let me my myself ours ourselves themselves itself yourself what's that's who's
""".split())
_ALWAYS_OK = set("""very loud typical quiet i january february march april may june july august september october
november december jan feb mar apr jun jul aug sep sept oct nov dec""".split())
_PLACE_NORM = {"street": "st", "streets": "st", "avenue": "ave", "avenues": "ave", "av": "ave", "boulevard": "blvd",
               "place": "pl", "drive": "dr", "road": "rd", "parkway": "pkwy", "expressway": "expy", "square": "sq",
               "west": "w", "east": "e", "north": "n", "south": "s", "saint": "st", "mt": "mount", "ft": "fort",
               "centre": "center", "ctr": "center", "hosp": "hospital", "lane": "ln"}
# The baseline every rank is stated against: fine in any sentence, as long as some line says it.
_CONTEXT_NAMES = {"manhattan", "nyc", "new", "york", "ny"}
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")


def _base(word):
    """A word without its apostrophe tail, curly or straight: "You’ll" -> "you", "It's" -> "it", "Don't" -> "do",
    "Manhattan’s" -> "manhattan"."""
    w = word.lower().replace("’", "'")
    if w.endswith("n't"):
        return {"won't": "will", "can't": "can", "shan't": "shall"}.get(w, w[:-3])
    return re.sub(r"'(?:ll|re|ve|d|s|m)?$", "", w)


def _norm(word):
    w = _base(word)
    return _PLACE_NORM.get(w, w)


def _tokens(text):
    return {_norm(w) for w in _WORD.findall(text)}


def names(text, plain=frozenset()):
    """The capitalised words of a text that are not plain English: candidate names, in order. Contractions count as
    the word they shorten, with either apostrophe ("You’ll", "It's"). A capital that only starts a sentence is a name
    only if the word is not ordinary English: not common, not an adverb or verb form ("Roughly", "Living"), and not a
    word the evidence itself writes in lowercase (`plain`). So "Nights here are loud." passes and "Broadway is
    loud." does not."""
    out = []
    for m in _WORD.finditer(text):
        w = m.group(0)
        if not w[0].isupper():
            continue
        low = _base(w)
        if low in _ALWAYS_OK or low in _NUMBER_WORDS or low in _ORDINALS:
            continue
        if low in _COMMON and not (w.isupper() and len(w) > 1):
            continue
        if any(rx.fullmatch(low) for rx, _ in _TERMS):   # "Bar", "Hospital": a kind of source, checked by C5
            continue
        first = re.search(r"(?:^|[.!?:;\"“”(])\s*[\"“]?$", text[:m.start()]) is not None
        if first and (re.search(r"(?:ly|ing|ed)$", low) or low in plain):
            continue
        out.append(w)
    return out


# ---------------------------------------------------------------- C5 kinds of source
# (what a sentence says, what a cited line must contain). None: the word itself must be in a cited line.
_TERMS = [
    (r"subways?|trains?|elevated|railways?|rail", ("subway", "elevated", "rail")),
    (r"highways?|expressways?|freeways?|parkways?|ramps?", ("highway", "ramp", "expressway", "parkway", "expy", "pkwy")),
    (r"bridges?", ("bridge",)),
    (r"bus|buses|trucks?", ("bus", "truck")),
    (r"hospitals?|ambulances?|medical cent(?:er|re)s?|emergency rooms?", ("hospital", "medical", "ambulance")),
    (r"fire ?houses?|fire stations?|fire trucks?|fire engines?|fire department|fdny", ("firehouse", "fire", "engine", "ladder")),
    (r"police|precincts?|nypd|cops?|patrol cars?", ("police", "precinct", "nypd")),
    (r"bars?|pubs?|clubs?|nightclubs?|lounges?|taverns?|cabarets?", ("bar", "club", "cabaret")),
    (r"restaurants?", ("restaurant",)),
    (r"venues?", ("venue",)),
    (r"construction|permits?|scaffold(?:ing|s)?|jackhammers?|demolition|excavation|renovations?|sidewalk sheds?|drilling|cranes?",
     ("construction", "permit", "demolition", "excavation", "shed")),
    (r"sirens?", ("siren", "hospital", "firehouse", "police", "emergency")),
    (r"neighbou?rs?|upstairs|downstairs|footsteps?", ("neighbor", "residential", "footsteps")),
    (r"nightlife|part(?:y|ies)|music|crowds?|revel(?:ers|lers)", ("nightlife", "party", "music", "venue", "bar")),
    (r"traffic|cars?|horns?|honking|vehicles?|engines? idling", ("street", "vehicle", "road", "traffic", "lane")),
    (r"schools?|playgrounds?|parks?|church(?:es)?|stadiums?|airports?|helicopters?|heliports?|garbage|sanitation|"
     r"deliver(?:y|ies)|ferr(?:y|ies)|train yards?|bells?|dogs?|barking|generators?|hvac|air condition(?:er|ers|ing)", None),
]
_TERMS = [(re.compile(r"\b(?:" + p + r")\b", re.I), kws) for p, kws in _TERMS]


def _term_errors(text, cited_text):
    errs = []
    for rx, kws in _TERMS:
        m = rx.search(text)
        if not m:
            continue
        if kws is None:
            stem = re.sub(r"(?:es|s)$", "", m.group(0).lower())
            ok = re.search(r"\b" + re.escape(stem), cited_text) is not None
        else:
            ok = any(re.search(r"\b" + re.escape(k), cited_text) for k in kws)
        if not ok:
            errs.append(f'mentions "{m.group(0)}", but no line it cites does')
    return errs


# ---------------------------------------------------------------- the checks
def check(reply, lines):
    """[] when the reply may reach a renter, else one plain-English error per problem (fed back on the retry)."""
    by_id = {l.id: l for l in lines}
    if not isinstance(reply, dict) or not isinstance(reply.get("sentences"), list):
        return ["the reply must be an object with a sentences list"]
    sentences = reply["sentences"]
    if not sentences:
        return ["the reply has no sentences"]
    context = _CONTEXT_NAMES & set().union(*(_tokens(l.text) for l in lines)) if lines else set()
    plain = {_base(w) for l in lines for w in _WORD.findall(l.text) if w.islower()}
    errs = []
    if len(sentences) > MAX_SENTENCES:
        errs.append(f"the reply has {len(sentences)} sentences; at most {MAX_SENTENCES}")
    for i, s in enumerate(sentences, 1):
        where = f"sentence {i}"
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or not s["text"].strip():
            errs.append(f"{where}: needs a non-empty text")
            continue
        text = s["text"].strip()
        cites = s.get("cites")
        if not isinstance(cites, list) or not cites or not all(isinstance(c, str) for c in cites):
            errs.append(f"{where}: must cite at least one evidence id")   # C1
            cites = []
        unknown = [c for c in cites if c not in by_id]
        if unknown:
            errs.append(f"{where}: cites {', '.join(unknown)}, not in the evidence")
        cited = [by_id[c] for c in cites if c in by_id]
        cited_text = " ".join(l.text for l in cited).lower()
        label = ", ".join(l.id for l in cited) or "none"
        if DECIBEL.search(text):                                          # C3
            errs.append(f"{where}: uses a decibel unit; give ranks against Manhattan, never sound levels")
        if re.search(r"\bE\d+\b", text):                                  # C6
            errs.append(f"{where}: puts an evidence id in the text; ids go in cites only")
        if len(text) > MAX_CHARS:
            errs.append(f"{where}: is {len(text)} characters; keep each sentence under {MAX_CHARS}")
        if cited:
            allowed = set().union(*(numbers(l.text) for l in cited))      # C2
            extra = sorted(numbers(re.sub(r"\bE\d+\b", "", text)) - allowed, key=float)
            if extra:
                errs.append(f"{where}: the number{'s' if len(extra) > 1 else ''} {', '.join(extra)} "
                            f"{'are' if len(extra) > 1 else 'is'} not in the lines it cites ({label})")
            known = set().union(*(_tokens(l.text) for l in cited)) | context   # C4
            missing = []
            for w in names(re.sub(r"\bE\d+\b", "", text), plain):
                if _norm(w) not in known and w not in missing:
                    missing.append(w)
            if missing:
                errs.append(f"{where}: {', '.join(repr(w) for w in missing)} "
                            f"{'are' if len(missing) > 1 else 'is'} not in the lines it cites ({label})")
            errs += [f"{where}: {e} ({label})" for e in _term_errors(text, cited_text)]   # C5
    return errs


def clean(reply):
    """The checked reply in its public shape: trimmed texts, cites without repeats."""
    return [{"text": s["text"].strip(), "cites": list(dict.fromkeys(s["cites"]))} for s in reply["sentences"]]
