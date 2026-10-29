"""The checks every field passes before it reaches a renter. (Hackathon work, Oct 28.)

They live here, in code the tools call, not in the prompt, so the agent cannot skip them (CLAUDE.md rule 2):

- a field marked read carries evidence, and every piece of it is checked;
- a text quote must be in the listing text, exactly, with whitespace the only thing normalized;
- the quote must state the value: the floor number next to the word floor, a side word, the address's own
  tokens. Adjectives ("quiet", "sun-drenched") never state anything, and a unit number is not a floor;
- a photo citation must name a photo that exists, that read_photo has looked at, and whose reading shows
  that same value. The "what" is copied from the reading, never from the agent.
"""
import re

SCORE_FIELDS = ("address", "unit", "floor", "side")
OBSERVED_FIELDS = ("view", "windows", "ac_units", "wall_material")
STATUSES = ("read", "cant_tell")

SIDES = ("street", "rear", "courtyard", "corner")
POSITION = {"street": "front", "corner": "front", "rear": "rear", "courtyard": "rear"}   # engine's position
VIEWS = ("street", "courtyard", "rear_yards", "airshaft", "park", "water", "skyline")
AC_UNITS = ("window", "through_wall", "split", "central")
WALLS = ("brick", "concrete", "plaster", "glass", "wood", "stone")
MAX_FLOOR = 120      # the engine's own bound
MIN_QUOTE = 4        # shorter spans are found in any text
TOP = "top"          # floor value for "PH", "penthouse", "top floor" with no number; the loop resolves it from the
                     # building's floor count in PLUTO, after the address is placed
MAX_WHAT = 240

PUFFERY = {"quiet", "quieter", "quietest", "peaceful", "serene", "tranquil", "calm", "silent", "hushed",
           "sun-drenched", "sunny", "sunlit", "bright", "airy", "charming", "stunning", "gorgeous", "beautiful",
           "cozy", "spacious", "luxurious", "luxury", "oasis", "retreat", "dreamy", "lovely", "rare", "perfect",
           "ideal", "private", "secluded", "sanctuary"}


class Refused(ValueError):
    """A field the checks refuse. The message goes back to the model so it can fix the field."""


# ---------------------------------------------------------------- the listing text
def normalize(s):
    return " ".join(str(s or "").split())


def find_quote(quote, text):
    """(start, end) of the quote in the original text, matching with whitespace collapsed, else None."""
    q = normalize(quote)
    if len(q) < MIN_QUOTE:
        return None
    chars, where, gap = [], [], True
    for i, ch in enumerate(text or ""):
        if ch.isspace():
            if not gap:
                chars.append(" ")
                where.append(i)
            gap = True
        else:
            chars.append(ch)
            where.append(i)
            gap = False
    k = "".join(chars).find(q)
    if k < 0:
        return None
    return where[k], where[k + len(q) - 1] + 1


# ---------------------------------------------------------------- does the quote state the value
_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_UNITS_TH = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
             "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
             "eighteenth", "nineteenth"]
_TENS = {20: ("twenty", "twentieth"), 30: ("thirty", "thirtieth"), 40: ("forty", "fortieth"),
         50: ("fifty", "fiftieth")}


def _number_words(n):
    if 0 < n < 20:
        return [_UNITS[n], _UNITS_TH[n]]
    tens, unit = n - n % 10, n % 10
    if tens not in _TENS:
        return []
    if unit == 0:
        return list(_TENS[tens])
    return [rf"{_TENS[tens][0]}[\s-]{_UNITS[unit]}", rf"{_TENS[tens][0]}[\s-]{_UNITS_TH[unit]}"]


_TOP_STATED = r"(?<![A-Za-z])PH(?:[\s-]?[A-Z0-9])?(?![A-Za-z])|(?i:\bpenthouse\b|\btop[\s-]floor\b)"


def _floor_stated(n, quote):
    """The number sits next to the word floor ("11th floor", "floor 11", "eleventh-floor"), or the quote says
    top floor or penthouse of an N-story building. Garden level is floor 1. "top" needs PH, penthouse or top
    floor. "Apt 3F" alone is a unit, not a floor."""
    if n == TOP:
        return re.search(_TOP_STATED, quote) is not None
    q = quote.lower()
    num = "(?:" + "|".join([rf"{n}(?:st|nd|rd|th)?"] + _number_words(n)) + ")"
    patterns = [rf"(?<![\w-]){num}[\s-]*(?:floor|fl)\b", rf"\b(?:floor|level)\s*(?:#|no\.?\s*)?{num}\b"]
    if n == 1:
        patterns.append(r"\b(?:ground|street|garden)[\s-]*(?:floor|level)\b")
    if re.search(r"\b(?:top floor|penthouse)\b", q):
        patterns.append(rf"(?<![\w-]){num}[\s-]*(?:story|stories|storey)")
    return any(re.search(p, q) for p in patterns)


_SIDE_STATED = {
    "rear": r"\b(?:rear|back of the (?:building|house)|back ?yards?|back gardens?)\b",
    "courtyard": r"\b(?:courtyard|court yard|interior court|inner court|light court)\b",
    # "corner unit", not "on the corner of X and Y" or "laundromat on the corner"
    "corner": r"\bcorner[\s-]+(?:unit|apartment|apt|home|residence|studio|loft|layout|exposures?|windows?"
              r"|(?:one|two|three|[123])[\s-]?(?:bedroom|br))\b"
              r"|\b(?:windows|exposures?) (?:on|facing) (?:two|both) (?:streets|sides)\b",
    "street": r"\b(?:street-facing|streetside|front-facing|front of the building)\b"
              r"|\b(?:fac(?:e|es|ing)|overlook(?:s|ing)?|onto|views? (?:of|over|onto)|windows? (?:on|over|onto))\b"
              r"[^.;]{0,60}\b(?:street|st\.?|avenue|ave\.?|broadway|boulevard|blvd\.?|place|road)\b",
}

_GENERIC = {"street", "st", "avenue", "ave", "east", "e", "west", "w", "north", "n", "south", "s", "new", "york",
            "ny", "nyc", "manhattan", "usa", "the", "of", "and", "at", "apt", "apartment", "unit"}


def _tokens(s):
    return {re.sub(r"(?<=\d)(st|nd|rd|th)$", "", t) for t in re.findall(r"[a-z0-9-]+", s.lower())}


def _address_stated(value, quote):
    """Every specific token of the address (house number, street name) is in the quote."""
    wanted = _tokens(value) - _GENERIC
    return bool(wanted) and wanted <= _tokens(quote)


def _unit_core(value):
    v = re.sub(r"\b(?:apt|apartment|unit|no)\b\.?|#", "", str(value), flags=re.I)
    return re.sub(r"\s+", "", v).lower()


def _unit_stated(value, quote):
    core = _unit_core(value)
    q = quote.lower().replace("#", " ")
    return bool(core) and re.search(rf"(?<![a-z0-9]){re.escape(core)}(?![a-z0-9])", q) is not None


def stated(name, value, quote):
    """None if the quote states this value, else why not."""
    ok = {
        "address": lambda: _address_stated(value, quote),
        "unit": lambda: _unit_stated(value, quote),
        "floor": lambda: _floor_stated(value, quote),
        "side": lambda: re.search(_SIDE_STATED[value], quote, re.I) is not None,
    }[name]()
    if ok:
        return None
    adjectives = sorted(PUFFERY & {w.strip(".,;:!()").lower() for w in quote.split()})
    if adjectives:
        return (f"adjectives are not evidence ({', '.join(adjectives)}): quote the words that state the {name}, "
                f"or mark it cant_tell")
    hints = {
        "address": "the quote must contain the house number and street exactly as in the value",
        "unit": "the quote must contain the unit as written in the value",
        "floor": "the quote must put the floor number next to the word floor; a unit number like 4B is not a floor. "
                 "For PH, penthouse or top floor with no number, send \"top\": the building's floor count is "
                 "looked up after the address is placed",
        "side": f"the quote must say the unit is on the {value} side (for example rear, courtyard, corner unit, "
                f"or faces <street name>)",
    }
    return f"the quote does not state {name} = {value!r}: {hints[name]}"


# ---------------------------------------------------------------- values
def coerce(name, value):
    """The value in its contract type, or Refused."""
    if name in ("address", "unit"):
        v = normalize(value)
        if not v:
            raise Refused(f"{name} is read but has no value")
        return v
    if name == "floor":
        if str(value).strip().lower() == TOP:
            return TOP
        try:
            v = int(str(value).strip())
        except (TypeError, ValueError):
            raise Refused(f"floor must be a whole number or \"top\", got {value!r}")
        if not 1 <= v <= MAX_FLOOR:
            raise Refused(f"floor must be between 1 and {MAX_FLOOR}, got {v}")
        return v
    enums = {"side": SIDES, "view": VIEWS, "ac_units": AC_UNITS, "wall_material": WALLS}
    if name in enums:
        v = str(value or "").strip().lower()
        if v not in enums[name]:
            raise Refused(f"{name} must be one of {', '.join(enums[name])}, got {value!r}")
        return v
    if name == "windows":
        if not isinstance(value, dict) or not isinstance(value.get("floor_to_ceiling"), bool):
            raise Refused('windows must be {"floor_to_ceiling": true|false, "operable": true|false|null}')
        operable = value.get("operable")
        if operable is not None and not isinstance(operable, bool):
            raise Refused("windows.operable must be true, false or null")
        return {"floor_to_ceiling": value["floor_to_ceiling"], "operable": operable}
    raise Refused(f"unknown field {name!r}")


def cant_tell(name):
    return {"value": "unknown" if name == "side" else None, "status": "cant_tell", "evidence": []}


def position(side_field):
    """The engine's position from the side field: street and corner are front, rear and courtyard are rear."""
    if side_field and side_field.get("status") == "read":
        return POSITION.get(side_field.get("value"), "unknown")
    return "unknown"


# ---------------------------------------------------------------- one field
def check_field(name, raw, text, photo_reads, n_photos):
    """The clean field, or Refused with the reason. photo_reads: {index: reading} from read_photo."""
    if raw is None:
        return cant_tell(name)
    if not isinstance(raw, dict):
        raise Refused(f"{name} must be an object with status, value and evidence")
    status = raw.get("status")
    if status not in STATUSES:
        raise Refused(f"{name}.status must be read or cant_tell, got {status!r}")
    if status == "cant_tell":
        return cant_tell(name)
    value = coerce(name, raw.get("value"))
    evidence = raw.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        raise Refused(f"{name} is marked read with no evidence: quote the listing or cite a photo, or mark it cant_tell")
    clean = []
    for item in evidence:
        source = str((item or {}).get("source", "")).strip()
        photo = re.fullmatch(r"photo:(\d+)", source)
        if source == "text":
            clean.append(_check_quote(name, value, (item or {}).get("quote"), text))
        elif photo:
            clean.append(_check_photo(name, value, int(photo.group(1)), photo_reads, n_photos))
        else:
            raise Refused(f"{name}: evidence source must be \"text\" or \"photo:<index>\", got {source!r}")
    return {"value": value, "status": "read", "evidence": clean}


def _check_quote(name, value, quote, text):
    if name in OBSERVED_FIELDS:
        raise Refused(f"{name} is read from photos only; cite photo:<index>")
    short = len(normalize(quote))
    if short < MIN_QUOTE:
        raise Refused(f"{name}: quote too short ({short} chars, minimum {MIN_QUOTE}): quote the words around it too")
    span = find_quote(quote, text)
    if span is None:
        raise Refused(f"{name}: quote not found in the listing text: {normalize(quote)!r}. Copy the exact words, "
                      f"or mark {name} cant_tell")
    exact = text[span[0]:span[1]]
    why = stated(name, value, exact)
    if why:
        raise Refused(f"{name}: {why}")
    return {"source": "text", "quote": exact, "start": span[0], "end": span[1]}


def _check_photo(name, value, index, photo_reads, n_photos):
    if index >= n_photos:
        raise Refused(f"{name}: photo {index} does not exist; this listing has {n_photos} photo(s)"
                      + (f", 0 to {n_photos - 1}" if n_photos else ""))
    reading = photo_reads.get(index)
    if reading is None:
        raise Refused(f"{name}: photo {index} has not been read; call read_photo first")
    seen = reading["fields"].get(name) or cant_tell(name)
    if seen["status"] != "read" or seen["value"] != value:
        shown = seen["value"] if seen["status"] == "read" else "cant_tell"
        raise Refused(f"{name}: photo {index} does not show {value!r} (its reading says {shown!r})")
    return {"source": f"photo:{index}", "what": seen["what"]}


def check_photo_field(name, raw):
    """One field of a photo reading, from the photo model. Anything malformed becomes cant_tell, with why."""
    if not isinstance(raw, dict) or raw.get("status") != "read":
        return cant_tell(name), None
    try:
        value = coerce(name, raw.get("value"))
    except Refused as e:
        return cant_tell(name), str(e)
    what = normalize(raw.get("what"))[:MAX_WHAT]
    if len(what) < 8:
        return cant_tell(name), f"{name}: read with no description of what in the photo shows it"
    return {"value": value, "status": "read", "what": what}, None
