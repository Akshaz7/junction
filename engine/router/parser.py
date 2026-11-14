"""Question parser (E-02): rules and a synonym table, no model call.

parse(question) -> Parsed(type, kind, scope, matched, ...)
  type  in count / area / length / volume / text / other
  kind  = plan-map kind (CONTRACT 5.4) or IFC kind (door, window, wall, room, storey, slab, ...)
  scope = "room" | "storey" | "whole-doc" | None (None = not stated)
  matched = True when the rules are confident. False sends the question to the
            model fallback (E-07); type/kind are then best guesses only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------- synonym table
# (kind, regex). The EARLIEST match in the cleaned question wins; ties go to the
# longer match. Multi-word terms ("wc room") must therefore be listed as their own
# pattern so they beat the shorter one that starts at the same place.
KIND_TERMS: list[tuple[str, str]] = [
    ("room", r"wc rooms?|toilet rooms?|powder rooms?"),
    ("toilet", r"toilets?|toilet bowls?|water closets?|\bwcs?\b|lavator(?:y|ies)|urinals?"),
    ("sink", r"sinks?|wash ?basins?|basins?"),
    ("shower", r"showers?"),
    ("bathtub", r"bath ?tubs?|baths\b"),
    ("door", r"doors?|doorways?"),
    ("window", r"windows?|glazing|glazed"),
    ("wall", r"walls?|facades?|façades?"),
    ("stairs", r"stairs?|staircases?|stairways?|stairwells?"),
    ("column", r"columns?|pillars?"),
    ("beam", r"beams?|girders?"),
    ("slab", r"slabs?"),
    ("roof", r"roofs?"),
    ("railing", r"railings?|balustrades?|handrails?"),
    ("ceiling", r"ceilings?"),
    ("covering", r"coverings?"),
    ("pipe", r"pipes?|piping|ducts?"),
    ("furniture", r"furniture|furnishings?"),
    ("apartment", r"apartments?|flats?|dwellings?|units?"),
    ("room", r"rooms?|bedrooms?|bathrooms?|washrooms?|kitchens?|kitchenettes?|living rooms?|"
             r"spaces?|saunas?|corridors?|hallways?|balcon(?:y|ies)|loggias?|terraces?|offices?|"
             r"restrooms?|lobby|lobbies|closets?|pantr(?:y|ies)|storerooms?|zones?"),
    ("mep", r"mep|electrical|cooling|heating|hvac|plumbing|sanitary|lighting"),
    ("storey", r"storeys?|stories|levels?|floors(?!\s*(?:plan|slab|finish|area))"),
    ("dimension", r"dimensions?"),
    ("text", r"annotations?|labels? text|notes?"),
]
_KIND_RE = [(k, re.compile(r"\b(?:%s)(?![a-z])" % p if not p.startswith(r"\b") else p)) for k, p in KIND_TERMS]

# ---------------------------------------------------------------- cleaning
_QUOTED = re.compile(r"(?<![\w])'[^']*'(?!\w)|\"[^\"]*\"|“[^”]*”")
_PAREN = re.compile(r"\([^)]*\)")
_PREFIX = re.compile(
    r"^(on|in) (the )?(sheet|drawing|plan)\b[^,]*,\s*|^(could|can|would) you( please)? (provide|give|tell|show|list)( me)?( the)?\s*|"
    r"^please (provide|give|tell|show|list)( me)?( the)?\s*|^(i (want|need) to know|tell me|show me|give me)( the)?\s*", re.I)


def clean(q: str) -> str:
    s = _QUOTED.sub(" <q> ", q)
    s = _PAREN.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"[?!.]+$", "", s)
    return s


# ---------------------------------------------------------------- type rules
_COMPOUND_HARD = (r"\band what\b|, and (?:what|how|which|include|provide|list)|\bas well as\b|\band could you\b|\balso (?:provide|include|give)\b|"
                  r"\bhow many of each\b|\bcompared (?:with|to)\b|\bof each\b|^which\b.*\bhow many\b")
_COMPOUND_SOFT = r"\band how many\b|,[^,]+, and \w+"   # also what a multi-kind count looks like
RE_COMPOUND = re.compile(_COMPOUND_HARD + "|" + _COMPOUND_SOFT)
RE_COMPOUND_HARD = re.compile(_COMPOUND_HARD)
RE_SUPER = re.compile(r"\b(largest|smallest|biggest|narrowest|widest|highest|lowest|tallest|shortest|longest|greatest|top \d+|top (?:five|ten|three))\b")
RE_BREAKDOWN = re.compile(
    r"\b(breakdown|broken down|grouped|distribution|percentages?|quantities|by (?:system|type|level|storey|floor|material|category|function|"
    r"room|wall type)|per (?:floor|level|storey|room|type)|each (?:floor|level|storey|type|room|bathroom|window|door)|"
    r"with (?:their|its|the) (?:[a-z ]{0,20} )?(?:areas?|quantities|counts|dimensions)|\band areas\b|ratio|vs\b|versus)\b")
RE_LISTQ = re.compile(r"^(?:what|which) (?:are|were)\b|^(?:what|which) (?:kinds?|types?|materials?|furniture|software|mep|systems?)\b|^(?:list|describe|name|which)\b|"
                      r"^what (?:\w+ ){0,3}(?:types?|materials?|systems?|furniture|equipment|components|elements|railings|coverings|pipes?|standards) ")
RE_HOWMANY = re.compile(r"\bhow many\b|^count\b|\bnumber of\b|\bcount of\b|\bhow much\b(?= (?:doors|windows|rooms|walls))")
RE_AREA = re.compile(r"\b(?:area|areas|square met(?:er|re)s|sq\.? ?m)\b")
RE_LENGTH = re.compile(r"\blength\b|\bhow long\b|\bperimeter\b")
RE_VOLUME = re.compile(r"\bvolume\b|\bcubic\b|\bm³\b|\bm3\b")
RE_WEAK_TEXT = re.compile(
    r"\b(types?|materials?|finish(?:es)?|hardware|furniture|systems|software|standards|information|rating|names?|guid|layers?|elevations?|"
    r"heights?|widths?|thicknesses|thickness|depth|dimensions?|specified|schedule[ds]? for|usage|location|function|description|load-bearing)\b")
RE_AREA_CMD = re.compile(r"^(?:find|get|give(?: me)?|calculate|compute|tell me|work out)\b")
RE_WH = re.compile(r"^(?:what|which|who|where|when|how|is|are|does|do|can)\b")


@dataclass
class Parsed:
    type: str
    kind: str | None
    scope: str | None
    matched: bool
    reason: str = ""
    scope_ref: str | None = None
    kinds: list | None = None   # every kind asked about ("windows and doors" -> ["window", "door"]); kind stays the first

    def __post_init__(self):
        if self.kinds is None:
            self.kinds = [self.kind] if self.kind else []

    def as_dict(self) -> dict:
        return asdict(self)


def _kind(qc: str, after: str | None = None) -> str | None:
    """Earliest kind term (optionally only after the first occurrence of `after`)."""
    start = 0
    if after:
        m = re.search(after, qc)
        if m:
            start = m.end()
    best = None
    for kind, rx in _KIND_RE:
        m = rx.search(qc, start)
        if not m:
            continue
        key = (m.start(), -(m.end() - m.start()))
        if best is None or key < best[0]:
            best = (key, kind)
    return best[1] if best else None


_JOIN = re.compile(r"\s*(?:,\s*(?:and\s+)?|&\s*|\band\s+|\bplus\s+)(?:(?:also\s+)?(?:how many|the number of|the)\s+)?")


def _kind_at(qc: str, pos: int) -> tuple[str, int] | None:
    """The kind term that STARTS exactly at pos (longest wins), as (kind, end)."""
    best = None
    for kind, rx in _KIND_RE:
        m = rx.match(qc, pos)
        if m and (best is None or m.end() > best[1]):
            best = (kind, m.end())
    return best


def multi_kinds(qc: str, after: str = r"how many|number of|count of|^count") -> list[str]:
    """'how many windows and doors', 'how many X and how many Y', 'count the X, Y and Z' -> distinct kinds in order.
    Only terms chained by and/comma/& right after each other count, so 'doors in the room with the window' stays single."""
    m0 = re.search(after, qc)
    start = m0.end() if m0 else 0
    first = None
    for kind, rx in _KIND_RE:
        m = rx.search(qc, start)
        if m and (first is None or (m.start(), -(m.end() - m.start())) < first[0]):
            first = ((m.start(), -(m.end() - m.start())), kind, m.end())
    if not first:
        return []
    out, end = [first[1]], first[2]
    while True:
        j = _JOIN.match(qc, end)
        if not j:
            break
        nxt = _kind_at(qc, j.end())
        if not nxt:
            break
        if nxt[0] not in out:
            out.append(nxt[0])
        end = nxt[1]
    return out


def _scope(qc: str) -> tuple[str | None, str | None]:
    if re.search(r"\b(?:in|of|for|serve|serves|serving|at) (?:the )?(?:room|space)\b|\broom <q>|\bthe room\b <q>|\b(?:room|space) [a-z]?\d[\w.\-]*", qc):
        return "room", None
    if re.search(r"\b(?:on|in|at|of) (?:the |this |each |every )?(?:ground|first|second|third|fourth|fifth|top|basement|underground|upper|lower|1st|2nd|3rd)\b[\w ]{0,12}\b(?:floor|level|storey)\b|"
                 r"\b(?:on|at|of) level \w+|\b(?:on|in) (?:this|the) floor\b(?! plan)|\bon each (?:floor|level)\b|\bfor (?:the )?(?:ground|first|second|third) (?:floor|level)|"
                 r"\bon <q>|\bunderground level|\bground level|\bon this floor\b(?! plan)|\bon the (?:ground|underground)\b", qc):
        return "storey", None
    if re.search(r"\b(?:in|of) (?:the|this) (?:building|model|project|drawing|document|plan|sheet)\b|\bthis floor plan\b|\bfloor plan of\b|"
                 r"\bthe building\b|\bbuilding's\b|\bin total\b|\boverall\b|\bwhole\b|\bacross\b|\bsheet\b", qc):
        return "whole-doc", None
    return None, None


def parse(question: str) -> Parsed:
    q = question.strip()
    qc = clean(q)
    body = _PREFIX.sub("", qc).strip()
    scope, ref = _scope(qc)

    def done(t, kind, reason, matched=True):
        return Parsed(t, kind, scope, matched, reason, ref)

    # 0. several kinds in one count question: "how many windows and doors", "count the X and Y"
    if RE_HOWMANY.search(body) and not RE_COMPOUND_HARD.search(body) and not RE_BREAKDOWN.search(body) and not RE_SUPER.search(body):
        ks = multi_kinds(body)
        if len(ks) > 1:
            return Parsed("count", ks[0], scope, True, "how-many-multi", ref, kinds=ks)
    # 1. strong text markers
    if RE_COMPOUND.search(body):
        return done("text", _kind(body), "compound")
    if RE_SUPER.search(body) and not RE_HOWMANY.search(body):
        return done("text", _kind(body), "superlative")
    if RE_BREAKDOWN.search(body):
        return done("text", _kind(body), "breakdown")
    # 2. count
    if RE_HOWMANY.search(body):
        k = _kind(body, after=r"how many|number of|count of|^count")
        return done("count", k, "how-many", matched=k is not None)
    # 3. quantities
    if RE_VOLUME.search(body):
        return done("volume", _kind(body, after=r"volume of|volume"), "volume")
    if RE_LENGTH.search(body):
        k = _kind(body, after=r"length of|length")
        return done("length", k, "length", matched=k is not None)
    if RE_AREA.search(body) and (RE_WH.search(body) or RE_AREA_CMD.search(body)) and not RE_LISTQ.search(body):
        k = _kind(body, after=r"\barea (?:of|for)\b") or _kind(body)
        return done("area", k or "room", "area", matched=True)
    # 4. text
    if RE_LISTQ.search(body) or RE_WEAK_TEXT.search(body):
        return done("text", _kind(body), "text")
    if RE_WH.search(body):
        return done("text", _kind(body), "wh-default", matched=False)
    return done("other", _kind(body), "no-rule", matched=False)
