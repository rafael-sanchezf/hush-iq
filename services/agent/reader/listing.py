"""What the reader is given: the listing (pasted text, uploaded photos) and the renter's three taps."""
import base64
import re
from dataclasses import dataclass, field

MAX_TEXT = 20_000
MAX_PHOTOS = 12
MAX_PHOTO_BYTES = 8 * 1024 * 1024
TICKS = ("traffic", "people", "neighbors", "sirens", "construction")

_MAGIC = [(b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"GIF8", "image/gif")]


class BadInput(ValueError):
    pass


def sniff(data):
    """The image type from its first bytes, or None. The declared type is never trusted."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass
class Photo:
    data: bytes
    kind: str
    name: str = ""

    @classmethod
    def from_bytes(cls, data, name=""):
        label = f"photo {name}" if name else "a photo"
        if len(data) > MAX_PHOTO_BYTES:
            raise BadInput(f"{label} is over {MAX_PHOTO_BYTES // (1024 * 1024)} MB")
        kind = sniff(data)
        if kind is None:
            raise BadInput(f"{label} is not a JPEG, PNG, WebP or GIF image")
        return cls(data=data, kind=kind, name=name)

    @classmethod
    def from_data_url(cls, value, name=""):
        """A data URL ("data:image/jpeg;base64,...") or bare base64."""
        m = re.fullmatch(r"data:[\w/+.-]*;base64,(.*)", value.strip(), re.S)
        try:
            data = base64.b64decode(m.group(1) if m else value, validate=False)
        except (ValueError, TypeError):
            raise BadInput(f"{f'photo {name}' if name else 'a photo'} is not valid base64")
        return cls.from_bytes(data, name)

    @property
    def data_url(self):
        return f"data:{self.kind};base64,{base64.b64encode(self.data).decode()}"


@dataclass
class Answers:
    """The renter's three taps, with engine v2's query names and defaults."""
    sleep_from: int = 23
    sleep_until: int = 7
    day_bothers: bool = True
    bothers: list = field(default_factory=list)

    @classmethod
    def parse(cls, raw):
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise BadInput("answers must be an object")
        a = cls()
        for key in ("sleep_from", "sleep_until"):
            if raw.get(key) is not None:
                try:
                    hour = int(raw[key])
                except (TypeError, ValueError):
                    raise BadInput(f"answers.{key} must be an hour, 0 to 23")
                if not 0 <= hour <= 23:
                    raise BadInput(f"answers.{key} must be an hour, 0 to 23")
                setattr(a, key, hour)
        if raw.get("day_bothers") is not None:
            if not isinstance(raw["day_bothers"], bool):
                raise BadInput("answers.day_bothers must be true or false")
            a.day_bothers = raw["day_bothers"]
        bothers = raw.get("bothers") or []
        if isinstance(bothers, str):
            bothers = [b.strip() for b in bothers.split(",") if b.strip()]
        unknown = [b for b in bothers if b not in TICKS]
        if unknown:
            raise BadInput(f"answers.bothers must be among {', '.join(TICKS)}; got {', '.join(map(str, unknown))}")
        a.bothers = list(dict.fromkeys(bothers))
        return a

    def as_dict(self):
        return {"sleep_from": self.sleep_from, "sleep_until": self.sleep_until, "day_bothers": self.day_bothers,
                "bothers": list(self.bothers)}


@dataclass
class Listing:
    text: str = ""
    photos: list = field(default_factory=list)
    answers: Answers = field(default_factory=Answers)

    def __post_init__(self):
        self.text = (self.text or "").strip()
        if len(self.text) > MAX_TEXT:
            raise BadInput(f"listing text is over {MAX_TEXT} characters")
        if len(self.photos) > MAX_PHOTOS:
            raise BadInput(f"at most {MAX_PHOTOS} photos")
        if not self.text and not self.photos:
            raise BadInput("send the listing text, photos, or both")
