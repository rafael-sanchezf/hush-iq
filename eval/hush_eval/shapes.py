"""The shared shapes the eval reads, and the one place their names and values live.

Reader result (services/agent, POST /read):
    {fields: {address, unit, floor, side}, position: front|rear|unknown,
     observed: {view, windows, ac_units, wall_material}, score: <v2 or v1 response>, trace: [...]}
    each field: {value, status: "read"|"cant_tell", evidence: [{source: "text", quote} | {source: "photo:<i>", what}]}
Verdict (services/verdict, POST /verdict):
    {evidence: [{id: "E1", text}], sentences: [{text, cites: ["E1"]}], writer: "muse-spark-open"|"muse-spark-1.3"|"template"}
Answers (the three taps, v2 query names):
    {sleep_from: int hour, sleep_until: int hour, day_bothers: bool, bothers: [traffic|people|neighbors|sirens|construction]}
"""
import re

CANT_TELL = "cant_tell"
STATUSES = ("read", CANT_TELL)
POSITIONS = ("front", "rear", "unknown")
BOTHERS = ("traffic", "people", "neighbors", "sirens", "construction")
VERDICTS = ("Very loud", "Loud", "Typical", "Quiet", "Very quiet")
WRITERS = ("muse-spark-open", "muse-spark-1.3", "template")

TEXT_FIELDS = ("address", "unit", "floor", "side")
OBSERVED_FIELDS = ("view", "windows", "ac_units", "wall_material")

# The values a read field may take. Floor is an integer; address and unit are free text.
SIDES = ("front", "rear")
OBSERVED_VALUES = {
    "view": ("street", "courtyard", "open", "wall"),
    "windows": ("floor_to_ceiling", "standard"),
    "ac_units": ("yes", "no"),
    "wall_material": ("brick", "concrete", "drywall", "glass"),
}
FLOOR_MIN, FLOOR_MAX = 1, 120

# A cant_tell field carries no value; the listing reader spells a cant_tell side "unknown".
CANT_TELL_VALUES = (None, "unknown")

# What the photo test labels, in the order the labeler shows them.
PHOTO_FIELDS = ("floor", "side") + OBSERVED_FIELDS

# Spellings a reader might use for the same value. The eval maps them before comparing, so a naming
# difference between sessions shows up as a contract note, not as a wrong answer.
ALIASES = {
    "side": {"street": "front", "street-facing": "front", "street_facing": "front", "corner": "front",
             "back": "rear", "courtyard": "rear", "courtyard-facing": "rear", "airshaft": "rear"},
    "view": {"courtyard_or_yard": "courtyard", "yard": "courtyard", "rear_yard": "courtyard", "rear_yards": "courtyard",
             "garden": "courtyard", "skyline": "open", "river": "open", "water": "open", "park": "open", "open_view": "open",
             "airshaft": "wall", "air_shaft": "wall", "brick_wall": "wall", "building": "wall"},
    "windows": {"floor-to-ceiling": "floor_to_ceiling", "floor_to_ceiling_glass": "floor_to_ceiling",
                "regular": "standard", "double_hung": "standard", "casement": "standard"},
    "ac_units": {True: "yes", False: "no", "true": "yes", "false": "no", "window": "yes", "window_unit": "yes",
                 "through_wall": "yes", "sleeve": "yes", "none": "no", "central": "no", "split": "no",
                 "none_visible": "no"},
    "wall_material": {"exposed_brick": "brick", "masonry": "brick", "stone": "brick", "plaster": "drywall",
                      "plaster_or_drywall": "drywall", "painted": "drywall", "wood": "drywall", "curtain_wall": "glass"},
}

# Words a listing uses to sell, which say nothing about floor or side. A quote made only of these is not evidence.
SALES_ADJECTIVES = {
    "quiet", "super", "very", "peaceful", "serene", "tranquil", "calm", "silent", "sunny", "bright", "charming",
    "lovely", "beautiful", "gorgeous", "stunning", "spacious", "cozy", "private", "secluded", "block", "street",
    "location", "apartment", "home", "unit", "the", "a", "an", "on", "in", "and", "of", "with", "so", "most",
}


def canonical(field, value):
    """The canonical spelling of a value, or the value unchanged. The listing reader's windows value is an object,
    {"floor_to_ceiling": bool, "operable": bool or null}; only floor_to_ceiling is labeled."""
    if value is None:
        return None
    if isinstance(value, dict):
        if field == "windows" and isinstance(value.get("floor_to_ceiling"), bool):
            return "floor_to_ceiling" if value["floor_to_ceiling"] else "standard"
        return CANT_TELL if field == "windows" and value.get("floor_to_ceiling") is None else value
    if isinstance(value, str):
        v = value.strip()
        key = v.lower().replace(" ", "_")
        if key in (CANT_TELL, "can't_tell", "cant-tell", "unknown"):
            return CANT_TELL
        aliases = ALIASES.get(field, {})
        if v.lower() in aliases:
            return aliases[v.lower()]
        if key in aliases:
            return aliases[key]
        return key if field in OBSERVED_VALUES or field == "side" else v
    return ALIASES.get(field, {}).get(value, value)


# ---------------------------------------------------------------- addresses
_ORDINAL_WORDS = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
                  "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11", "twelfth": "12"}
_ABBREV = {"st": "street", "str": "street", "ave": "avenue", "av": "avenue", "pl": "place", "blvd": "boulevard",
           "dr": "drive", "sq": "square", "rd": "road", "ln": "lane", "pkwy": "parkway", "ter": "terrace",
           "e": "east", "w": "west", "n": "north", "s": "south", "bway": "broadway", "b'way": "broadway"}
_UNIT_WORDS = {"apt", "apartment", "unit", "suite", "ph", "#", "fl", "floor"}


def normalize_address(addr):
    """'51 St. Mark's Pl, New York, NY 10003' -> '51 st marks place'. House number and street only."""
    if not addr:
        return None
    s = str(addr).lower().split(",")[0]
    s = s.replace("b'way", "broadway").replace("’", "'")
    s = re.sub(r"['.]", "", s)
    s = re.sub(r"#\s*\w+", " ", s)
    toks = re.split(r"[\s\-]+", s.strip())
    out = []
    for i, t in enumerate(toks):
        if t in _UNIT_WORDS and i > 1:
            break                                    # "2109 broadway apt 4b": stop at the unit
        if t == "saint":
            t = "st"
        elif t == "st" and i < len(toks) - 1 and i > 0:
            t = "st"                                 # "st marks": saint, kept short
        elif t in _ORDINAL_WORDS:
            t = _ORDINAL_WORDS[t]
        elif re.fullmatch(r"\d+(st|nd|rd|th)", t):
            t = re.sub(r"(st|nd|rd|th)$", "", t)
        elif t in _ABBREV:
            t = _ABBREV[t]
        out.append(t)
    if out and out[-1] == "st":
        out[-1] = "street"
    return " ".join(out) or None
