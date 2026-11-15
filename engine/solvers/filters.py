"""Shared, explicit room/storey filters. A missing match never means all items."""
from __future__ import annotations

import re
import unicodedata

from .data import Item


def fold(text: str) -> str:
    text = str(text or "").casefold().replace("ß", "ss")
    for a, b in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("ae", "a"), ("oe", "o"), ("ue", "u")):
        text = text.replace(a, b)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = re.sub(r"[^\w]+", " ", text).strip()
    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
    return " ".join(roman.get(w, w) for w in text.split())


STOREY_REQUEST = re.compile(
    r"\b(?:ground|grund|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:floor|level|storey|story)\b"
    r"|\b(?:floor|level|storey|story)\s+\d+\b|\b\d+\.?\s*(?:og|obergeschoss)\b"
    r"|\b(?:basement|cellar|underground|keller|erdgeschoss|eg|dachgeschoss|dg)\b|\b(?:top|roof|uppermost)\s+(?:floor|level|storey)\b", re.I)


def storey_requested(question: str) -> bool:
    return bool(STOREY_REQUEST.search(question))


def room_name(item: Item) -> str:
    return str(item.props.get("long_name") or item.label or item.name or item.type_name or item.item_id)


ROOM_TYPES = {
    "office": r"\b(?:buro|office|toimisto)\w*",
    "meeting room": r"\b(?:besprechung|meeting|conference|sitzung|kokous)\w*",
    "lab": r"\b(?:labor|lab|laboratory|laboratories)\w*",
    "kitchen": r"\b(?:kuche|kitchen|keitti)\w*",
    "bathroom": r"\b(?:wc|toilet|bath|bad|kylpy)\w*",
    "bedroom": r"\b(?:bedroom|schlaf|makuu)\w*",
    "corridor": r"\b(?:flur|corridor|korridor|hallway|kaytav)\w*",
    "classroom": r"\b(?:classroom|klassen|seminar|luokka)\w*",
    "storage": r"\b(?:storage|lager|abstell|varasto)\w*",
}
ROOM_ALIASES = {"offices": "office", "meeting rooms": "meeting room", "laboratories": "lab", "laboratory": "lab", "labs": "lab",
                "kitchens": "kitchen", "bathrooms": "bathroom", "toilets": "bathroom", "wc": "bathroom", "bedrooms": "bedroom",
                "corridors": "corridor", "hallways": "corridor", "classrooms": "classroom", "storerooms": "storage"}


def room_filter(question: str, rooms: list[Item]) -> tuple[str, list[Item]] | None:
    """Recognise a drawn name, a translated room type, or an explicit area target."""
    # A quoted label that carries its own room number ('Toilet (Rum nr. S11)') is matched by the exact-label path in solve.py.
    if re.search(r"['\"\u2018\u2019\u201c][^'\"]*\([^)]*\d[^)]*\)\s*['\"\u2018\u2019\u201d]", question):
        return None
    # A generic noun followed by its synonym is not a named room. Preserve
    # parenthesised room numbers/names everywhere else.
    question = re.sub(r'\b(rooms?|spaces?)\s*\(\s*(?:rooms?|spaces?)\s*\)', r'\1', question, flags=re.I)
    q = fold(question)
    if re.search(r"\b(?:largest|biggest|smallest|tiniest)\s+room\b", q):
        return None
    aliases = {**{k: k for k in ROOM_TYPES}, **ROOM_ALIASES}
    explicit = re.search(r"\b(?:area|size) of (?:the |a |an )?(.+)|\bhow (?:big|large) is (?:the |a |an )?(.+)", q)
    if explicit:
        target = (explicit.group(1) or explicit.group(2)).strip()
        target = re.split(r"\b(?:on|in|with|between|including|excluding)\b", target)[0].strip()
        target = re.sub(r"^(?:(?:all|every|each|of|the)\s+)+", "", target)
        if not target or target in ("it", "this", "that") or re.fullmatch(r"(?:(?:whole|entire|total|combined|net|gross|floor)\s+)*(?:rooms?|spaces?|building|model|floor|storey|plan|house|flat|apartment)(?:\s+\d+)?", target):
            return None
        if target in aliases:
            base = aliases[target]
            return base, [r for r in rooms if re.search(ROOM_TYPES[base], fold(room_name(r)))]
        # Never shorten an unknown full name ('Buero Mueller XI') to a known prefix ('Buero').
        return target, [r for r in rooms if re.search(rf"(?<!\w){re.escape(target)}(?!\w)", fold(room_name(r)))]
    # A full name beats a type (and 'II' beats 'I'). Whole tokens prevent Roman-prefix matches.
    names = sorted({room_name(r) for r in rooms if len(fold(room_name(r))) > 2 and not room_name(r).isdigit()}, key=lambda s: len(fold(s)), reverse=True)
    for name in names:
        n = fold(name)
        if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", q):
            return name, [r for r in rooms if fold(room_name(r)) == n]
    for alias, base in sorted(aliases.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return base, [r for r in rooms if re.search(ROOM_TYPES[base], fold(room_name(r)))]
    return None


def missing_room_text(target: str, rooms: list[Item]) -> str:
    from difflib import get_close_matches
    names = sorted({room_name(r) for r in rooms})
    closest = get_close_matches(target, names, n=5, cutoff=0.25)
    return (f"No room matching **{target}** was found in this model. "
            + (f"Closest matches: {', '.join(closest)}. " if closest else "")
            + "Room names/types present: " + ", ".join(names[:30]) + (f"; and {len(names) - 30} more" if len(names) > 30 else "") + ".")
