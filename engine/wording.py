"""Plain-language helpers for answer text (E-60): readable IFC type names, no internal ids."""
from __future__ import annotations
import re

GLOSS = {
    "stahlbeton": "reinforced concrete", "beton": "concrete", "kalksandstein": "sand-lime brick", "mauerwerk": "masonry",
    "ziegel": "brick", "holz": "timber", "gipskarton": "plasterboard", "porenbeton": "aerated concrete", "stahl": "steel",
    "dämmung": "insulation", "daemmung": "insulation", "estrich": "screed",
}
_ID = re.compile(r"(?<![\w.])\d{6,}(?![\w.])")      # 2747937872: an internal type or element id
_THICK = re.compile(r"^(?P<name>.*?)\s+(?P<mm>\d{2,4})$")


def clean_type_name(name: str, with_mm: bool = True) -> str:
    """'Stahlbeton 2747937872 300' -> 'Stahlbeton (reinforced concrete), 300 mm'."""
    raw = str(name or "")
    s = _ID.sub(" ", raw).strip()
    s = re.sub(r"\s{2,}", " ", s)
    mm = None
    m = _THICK.match(s) if s != raw.strip() else None   # only when an id was stripped
    if m and m.group("name"):
        s, mm = m.group("name").strip(), m.group("mm")
    first = re.split(r"[\s_\-/]+", s, 1)[0].lower()
    if first in GLOSS and "(" not in s:
        s = re.sub(r"^(\S+)", lambda x: f"{x.group(1)} ({GLOSS[first]})", s, count=1)
    return f"{s}, {mm} mm" if (mm and with_mm) else s


def scrub(text: str) -> str:
    """Last-resort cleanup of answer text: drop raw numeric ids and tidy spacing."""
    out = _ID.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", out).replace(" ,", ",").replace(" :", ":")
