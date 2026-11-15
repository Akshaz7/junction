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
    return str(item.props.get("long_name") or item.label or item.name or item.type_name or item.props.get("room_type") or "unnamed room")


ROOM_TYPES = {
    "office": r"\b(?:buro|office|toimisto|kontor)\w*",
    "meeting room": r"\b(?:besprechung|meeting|conference|sitzung|kokous|motesrum)\w*",
    "lab": r"\b(?:labor|lab|laboratory|laboratories)\w*",
    "kitchen": r"\b(?:kuche|kitchen|keitti|kok)\w*",
    "bathroom": r"\b(?:wc|toilet|bath|bad|kylpy|toalett)\w*",
    "bedroom": r"\b(?:bedroom|schlaf|makuu|sovrum)\w*",
    "corridor": r"\b(?:flur|corridor|korridor|hallway|kaytav)\w*",
    "classroom": r"\b(?:classroom|klassen|seminar|luokka|klassrum)\w*",
    "storage": r"\b(?:storage|lager|abstell|varasto|forrad)\w*",
    "living room": r"\b(?:living|lounge|wohn|olohuone|vardagsrum)\w*",
}
ROOM_ALIASES = {"offices": "office", "meeting rooms": "meeting room", "laboratories": "lab", "laboratory": "lab", "labs": "lab",
                "kitchens": "kitchen", "bathrooms": "bathroom", "toilets": "bathroom", "wc": "bathroom", "bedrooms": "bedroom",
                "living rooms": "living room", "corridors": "corridor", "hallways": "corridor", "classrooms": "classroom", "storerooms": "storage",
                "makuuhuone": "bedroom", "schlafzimmer": "bedroom", "sovrum": "bedroom",
                "keittio": "kitchen", "kok": "kitchen", "kuche": "kitchen", "kokoushuone": "meeting room",
                "toimisto": "office", "kontor": "office", "luokkahuone": "classroom"}


def room_type_matches(room: Item, base: str) -> bool:
    label = fold(room_name(room))
    typed = fold(room.props.get("room_type") or "")
    types = {"bedroom": {"bedroom"}, "kitchen": {"kitchen"}, "bathroom": {"bathroom", "wc"},
             "corridor": {"corridor", "entry"}, "storage": {"storage"}, "living room": {"living"}}
    return bool(re.search(ROOM_TYPES[base], label) or typed in types.get(base, {base}))


_ROOM_NUMBER = re.compile(r"(?<!\w)(?:[^\W\d_]+[-.]?)?\d+(?:[.\-]\d+)*(?:[^\W\d_]+)?(?!\w)")
_ROOM_PREFIX = re.compile(r"^(?:(?:rooms?|spaces?|raum|zimmer|rum|huone|piece|nr|no|number|numero)(?:\s+|$))+")


def _room_labels(room: Item) -> list[str]:
    return [str(v) for v in (room.props.get("number"), room.name, room.label,
                             room.props.get("long_name"), room.type_name, room.props.get("room_type")) if v is not None]


def _numbered_rooms(target: str, rooms: list[Item]) -> tuple[str, list[Item]] | None:
    """Intersect a source room number with its name/type, regardless of field order.

    Exact ids win. A punctuation-free spelling is accepted only when no exact id
    exists, and all ambiguous matches are retained for the caller to clarify.
    Numbers are compared as identifiers, never as floats or substring prefixes.
    """
    target = target.strip(" '\"\u2018\u2019\u201c\u201d?")
    scanned = target.casefold()
    numbers = list(_ROOM_NUMBER.finditer(scanned))
    if len(numbers) != 1:
        return None
    number = numbers[0]
    requested = number.group()
    name = _ROOM_PREFIX.sub("", fold(scanned[:number.start()] + " " + scanned[number.end():]))
    aliases = {**{k: k for k in ROOM_TYPES}, **ROOM_ALIASES}
    base = aliases.get(name) or next((k for k, pattern in ROOM_TYPES.items() if re.fullmatch(pattern, name)), None)

    def ids(room):
        found = set()
        # A type code (e.g. "Space Type 1") is not the room's identifier.
        for label in (room.props.get("number"), room.name, room.label, room.props.get("long_name")):
            if label is not None:
                found.update(m.group() for m in _ROOM_NUMBER.finditer(str(label).casefold()))
        return found

    indexed = [(r, ids(r)) for r in rooms]
    hit = [r for r, values in indexed if requested in values]
    if not hit:
        compact = lambda value: re.sub(r"[.\-]", "", value)
        hit = [r for r, values in indexed if any(compact(requested) == compact(v) for v in values)]
    if name:
        pattern = ROOM_TYPES[base] if base else rf"(?<!\w){re.escape(name)}(?!\w)"
        hit = [r for r in hit if any(re.search(pattern, fold(v)) for v in _room_labels(r))]
        if not hit:
            # A full drawn name may use Roman numerals ('Prüfzimmer II' / 'Pruefzimmer 2').
            # Its ordinal alone must never become a room number.
            hit = [r for r in rooms if not any(c.isdigit() for c in room_name(r))
                   and fold(room_name(r)) == fold(target)]
    return target, hit


def _target_before_scope(target: str) -> str:
    return re.split(r"\b(?:on|in|with|between|including|excluding)\b", target, flags=re.I)[0].strip()


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
    explicit = re.search(r"\b(?:area|size) of (?:the |a |an )?(.+)|\bhow (?:big|large) is (?:the |a |an )?(.+)", question, re.I)
    if explicit:
        raw_target = _target_before_scope(explicit.group(1) or explicit.group(2))
        target = fold(raw_target)
        target = re.sub(r"^(?:(?:all|every|each|of|the)\s+)+", "", target)
        if not target or target in ("it", "this", "that") or re.fullmatch(r"(?:(?:whole|entire|total|combined|net|gross|floor)\s+)*(?:rooms?|spaces?|(?:building|model|floor|storey|plan|house|flat|apartment)(?:\s+\d+)?)", target):
            return None
        if STOREY_REQUEST.fullmatch(target):
            return None  # "area of the ground floor" scopes rooms by storey, not by room name.
        numbered = _numbered_rooms(raw_target, rooms)
        if numbered is not None:
            return numbered
        if target in aliases:
            base = aliases[target]
            return base, [r for r in rooms if room_type_matches(r, base)]
        # Never shorten an unknown full name ('Buero Mueller XI') to a known prefix ('Buero').
        return target, [r for r in rooms if re.search(rf"(?<!\w){re.escape(target)}(?!\w)", fold(room_name(r)))]
    reference = re.search(r"\b(?:where (?:is|are)|(?:show|locate|find)(?: me)?|how many|number of|list)\s+(?:the\s+)?(.+)", question, re.I)
    target = _target_before_scope(reference.group(1) if reference else question)
    numbered = _numbered_rooms(target, rooms)
    if numbered is not None:
        return numbered
    # A full name beats a type (and 'II' beats 'I'). Whole tokens prevent Roman-prefix matches.
    names = sorted({room_name(r) for r in rooms if len(fold(room_name(r))) > 2 and not room_name(r).isdigit()}, key=lambda s: len(fold(s)), reverse=True)
    for name in names:
        n = fold(name)
        if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", q):
            return name, [r for r in rooms if fold(room_name(r)) == n]
    for alias, base in sorted(aliases.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return base, [r for r in rooms if room_type_matches(r, base)]
    return None


def missing_room_text(target: str, rooms: list[Item]) -> str:
    from difflib import get_close_matches
    names = sorted({room_name(r) for r in rooms})
    closest = get_close_matches(target, names, n=5, cutoff=0.25)
    return (f"No room matching **{target}** was found in this model. "
            + (f"Closest matches: {', '.join(closest)}. " if closest else "")
            + "Room names/types present: " + ", ".join(names[:30]) + (f"; and {len(names) - 30} more" if len(names) > 30 else "") + ".")
