"""Robust English check for question text (many questions have fi/da/de/fr copies)."""
import re

_EN = re.compile(r"\b(the|how|what|is|are|of|in|on|this|total|many|does|which|and|to|for|there|shown|drawn|floor|plan)\b", re.I)
_FOREIGN_WORDS = re.compile(
    r"\b(kuinka|monta|onko|paljon|mik[aä]|pohjapiirustu\w*|on|hvad|hvor|mange|er|det|rum|wie|viele|ist|sind|welche|"
    r"grundriss|eingezeichnet|quelle|combien|sont|dessin\w*|surface|plan|quel|quelles?|cuant\w*|cu[aá]ntos|"
    r"quanti|quante|disegnat\w*)\b", re.I)
_STRONG_FOREIGN = re.compile(
    r"\b(kuinka|monta|onko|paljon|pohjapiirustu\w*|hvad|hvor|mange|wie viele|grundriss|eingezeichnet|"
    r"quelle|combien|dessin[ée]\w*|nettoarealet|cu[aá]ntos|quanti|quante|disegnat\w*|v[aä]ltt\w*)\b", re.I)
_FOREIGN_CHARS = re.compile(r"[äöåæøéèêàçüßñ]", re.I)


def is_english(text: str) -> bool:
    t = text.strip()
    if _STRONG_FOREIGN.search(t):
        return False
    en_hits = len(_EN.findall(t))
    if _FOREIGN_CHARS.search(t) and en_hits < 3:
        return False
    if en_hits >= 3:
        return True
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
        langs = detect_langs(t)
        return langs[0].lang == "en" and langs[0].prob > 0.6 and en_hits >= 1
    except Exception:
        return en_hits >= 2
