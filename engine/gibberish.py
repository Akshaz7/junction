"""Keyboard-mash / nonsense detector: a short question with no known word and a mash-looking token gets "I didn't understand", never a carried-over answer."""
from __future__ import annotations

import re

STEMS = ("what", "how", "where", "which", "who", "when", "why", "is", "are", "can", "could", "do", "does", "show", "list", "give", "tell", "find", "count", "compare",
         "door", "window", "room", "stair", "wall", "floor", "storey", "story", "level", "area", "size", "slab", "pipe", "plan", "draw", "scale", "sheet", "model", "3d",
         "ar", "exit", "toilet", "kitchen", "bath", "bed", "total", "table", "upload", "help", "hello", "hi", "hey", "thank", "yes", "no", "ok", "please", "export",
         "view", "open", "visuali", "measure", "length", "width", "height", "metre", "meter", "baseboard", "column", "beam", "roof", "elevator", "lift", "fire", "rule",
         "compl", "summar", "explain", "name", "number", "many", "much", "more", "less", "again", "that", "this", "it", "the", "a", "and", "or", "of", "in", "on", "for")
MASH = re.compile(r"asdf|sdfg|dfgh|fghj|ghjk|hjkl|qwer|wert|erty|rtyu|zxcv|xcvb|cvbn|uiop|(.)\1{3,}|[bcdfghjklmnpqrstvwxz]{5,}", re.I)


def is_gibberish(q: str) -> bool:
    q = (q or "").strip()
    if not q or len(q) > 60 or re.search(r"\d", q):
        return False
    toks = re.findall(r"[A-Za-z']+", q)
    if not toks:
        return len(q) <= 12  # "???" , "...", "!!!"
    if len(toks) > 5:
        return False
    if any((t.lower() in STEMS) if len(t) <= 3 else t.lower().startswith(tuple(x for x in STEMS if len(x) > 3)) for t in toks):
        return False
    return any(MASH.search(t) or not re.search(r"[aeiouy]", t, re.I) for t in toks)


MESSAGE = ("I didn't understand that. Try asking, for example: \"How many doors are there?\", \"What is the area of the kitchen?\" "
           "or \"Where are the stairs?\".")
