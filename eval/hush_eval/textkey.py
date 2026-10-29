"""The text key: what a listing's own text states about the fields a photo could also show.

    key(text) -> {field: {"value": v, "quote": "the words that state it"}}

A free answer key for the photos-only run: withhold the text, give the reader the photos, and see whether it
reaches what the text says. So the key comes from these rules and Rafa's confirm click, never from a model.

The rules are strict. Each needs a fact word next to an orientation or a number ("faces the street", "third
floor", "exposed brick"), never a sales word: "quiet", "peaceful" and "no street noise" never make a key. A
field whose rules point two ways (a front room on the street and a bedroom on the garden) gets no key.

The labeler pre-fills from the same rules: RULES is copied verbatim into eval/labeler.html, between the
`text-key-rules` markers, and tests/test_textkey.py fails when the two differ. `photo sync-rules` rewrites it.
"""
import json
import re
from pathlib import Path

ORDINALS = {"ground": 1, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
            "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20}
NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12}

_TO = r"(?:faces?|facing|overlook(?:s|ing)?|looks?\s+(?:out\s+)?(?:onto|over|into)|opens?\s+(?:out\s+)?onto|windows?\s+(?:onto|on)\s)"
_A = r"\s+(?:the\s+|a\s+|an\s+)?(?:[a-z-]+\s+){0,2}?"
_STREET = r"(?:street|avenue|broadway|(?:[\w.']+\s+){1,3}(?:street|st|avenue|ave|place|pl|boulevard|blvd|road))\b"

# (field, value, pattern). Matched case-blind on ASCII words, the same in Python and in the browser.
# Floor values: an integer, "n" (group 1 is the number), "ordinal" or "stories" (group 1 is a word), and "unit"
# (only when nothing else states the floor: "Apt 12F" is the 12th floor in most buildings, not all).
RULES = [
    ["floor", "n", r"\b(\d{1,2})(?:st|nd|rd|th)[\s-]*(?:fl\b|floor\b)"],
    ["floor", "n", r"\bfloor\s+(\d{1,2})\b"],
    ["floor", "ordinal", r"\b(" + "|".join(ORDINALS) + r")[\s-]+floor\b"],
    ["floor", 1, r"\bgarden[\s-]+(?:level|floor)\b"],
    ["floor", "stories", r"\btop[\s-]+floor\s+of\s+an?\s+(\d{1,2}|" + "|".join(NUMBERS) + r")[\s-]+stor(?:y|ey)\b"],
    ["floor", "unit", r"\b(?:apt\.?|apartment|unit|#)\s*(\d{1,2})[a-z]{1,2}\b"],
    ["side", "rear", r"\b(?:courtyard|rear|back|garden|yard)[\s-]facing\b"],
    ["side", "rear", r"\b" + _TO + _A + r"(?:courtyard|rear|back|backyard|gardens?|yards?|air\s?shaft|light\s?well)\b"],
    ["side", "rear", r"\b(?:in|at)\s+the\s+(?:[a-z]+\s+)?(?:rear|back)\s+of\s+the\s+building\b"],
    ["side", "rear", r"\brear\s+(?:unit|apartment|bedroom)\b"],
    ["side", "front", r"\bstreet[\s-]facing\b"],
    ["side", "front", r"\bcorner\s+(?:unit|apartment)\b"],
    ["side", "front", r"\b" + _TO + r"\s+(?:the\s+)?" + _STREET],
    ["view", "wall", r"\b" + _TO + _A + r"(?:air\s?shaft|light\s?well)\b"],
    ["view", "courtyard", r"\b" + _TO + _A + r"(?:courtyard|backyard|gardens?|yards?)\b"],
    ["view", "courtyard", r"\b(?:courtyard|garden)\s+views?\b"],
    ["view", "open", r"\b(?:river|hudson|water|park|skyline|open|bridge)\s+views?\b"],
    ["view", "open", r"\bviews?\s+of\s+(?:the\s+)?(?:hudson|east\s+river|river|central\s+park|park|skyline|city\s+skyline)\b"],
    ["windows", "floor_to_ceiling", r"\bfloor[\s-]to[\s-]ceiling\s+(?:[a-z-]+\s+)?(?:windows?|glass)\b"],
    ["ac_units", "no", r"\bcentral\s+(?:air|a/?c\b|air[\s-]?conditioning|heat(?:ing)?\s+and\s+(?:air|a/?c\b|cooling))"],
    ["ac_units", "no", r"\b(?:split[\s-]system|ductless|mini[\s-]splits?)\b"],
    ["ac_units", "yes", r"\b(?:window|through[\s-](?:the[\s-])?wall|sleeve)\s+(?:a/?c\b|air[\s-]?condition(?:ers?|ing)|units?\b)"],
    ["wall_material", "brick", r"\bexposed\s+(?:brick|stone)\b"],
    ["wall_material", "concrete", r"\b(?:exposed\s+concrete|concrete\s+(?:ceilings?|walls?))\b"],
    ["wall_material", "glass", r"\b(?:glass\s+(?:curtain\s+)?walls?|window\s+walls?)\b"],
]
FIELDS = ("floor", "side", "view", "windows", "ac_units", "wall_material")
# Before matching, odd spaces, curly apostrophes and dashes become plain ones, one character for one.
NORMALIZE = [["[\\u00a0\\u2007\\u202f]", " "], ["[\\u2018\\u2019]", "'"], ["[\\u2010-\\u2014]", "-"]]
_COMPILED = [(f, v, re.compile(p, re.I | re.A)) for f, v, p in RULES]
_NORMALIZE = [(re.compile(p), r) for p, r in NORMALIZE]


def normalize(text):
    for rx, r in _NORMALIZE:
        text = rx.sub(r, text)
    return text


def _floor(value, m):
    if isinstance(value, int):
        return value
    word = m.group(1).lower()
    if value == "ordinal":
        return ORDINALS[word]
    if value == "stories":
        return int(word) if word.isdigit() else NUMBERS[word]
    return int(word)


def key(text):
    """{field: {"value", "quote"}} for every field the text states one way only."""
    text = normalize(text or "")
    found = {f: [] for f in FIELDS}          # field -> [(value, quote, start)] in rule order
    unit = []
    for field, value, rx in _COMPILED:
        for m in rx.finditer(text):
            if field == "floor":
                (unit if value == "unit" else found["floor"]).append((_floor(value, m), m.group(0), m.start()))
            else:
                found[field].append((value, m.group(0), m.start()))
    if not found["floor"]:
        found["floor"] = unit
    out = {}
    for field, hits in found.items():
        if hits and len({v for v, _, _ in hits}) == 1:
            first = min(hits, key=lambda h: h[2])
            out[field] = {"value": first[0], "quote": first[1].strip()}
    return out


def confirmed(labels_doc, text):
    """The keys Rafa confirmed: the rule's value is his label and he has clicked it (it is no longer pre-filled).
    Returns (confirmed, waiting, corrected): waiting still needs the click, corrected is where his label differs."""
    labels = (labels_doc or {}).get("labels") or {}
    pre = set((labels_doc or {}).get("prefilled") or [])
    ok, waiting, corrected = {}, {}, {}
    for field, k in key(text).items():
        got = labels.get(field)
        if got is None or field in pre:
            waiting[field] = k
        elif got == k["value"]:
            ok[field] = k
        else:
            corrected[field] = dict(k, label=got)
    return ok, waiting, corrected


# ---------------------------------------------------------------- the copy in the labeler
LABELER = Path(__file__).resolve().parents[1] / "labeler.html"
_BLOCK = re.compile(r'(<script type="application/json" id="text-key-rules">\n)(.*?)(\n</script>)', re.S)


def rules_json():
    """Everything the labeler needs to key a text the same way: the rules, the number words, the clean-up."""
    return json.dumps({"fields": FIELDS, "normalize": NORMALIZE, "ordinals": ORDINALS, "numbers": NUMBERS, "rules": RULES},
                      indent=1)


def labeler_rules(path=LABELER):
    m = _BLOCK.search(Path(path).read_text())
    return json.loads(m.group(2)) if m else None


def sync_labeler(path=LABELER):
    """Rewrite the labeler's copy of RULES. Returns True when it changed."""
    html = Path(path).read_text()
    new = _BLOCK.sub(lambda m: m.group(1) + rules_json() + m.group(3), html, count=1)
    if new != html:
        Path(path).write_text(new)
    return new != html
