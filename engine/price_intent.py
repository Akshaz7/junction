"""F-TABLEOPS: a price/cost question is not an order quantity.

Drawings and IFC quantity data rarely carry prices. When the question asks for a price or cost, supplies none,
and the document text/properties contain no price data, say so and abstain (never answer with a count/order).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ASK = re.compile(r"\b(?:purchase |unit |total |retail |market )?(?:prices?|pricing|costs?|costing|how much (?:does|do|is|are|would|will)\b[^?]*\b(?:cost|pay|charge))\b", re.I)
# Not a price question: asks for a quantity/order list, or about the app's own running cost.
NOT_PRICE = re.compile(r"\b(?:order (?:list|quantit\w*)|how many|quantit(?:y|ies)|take-?off|waste|inference|api|token|credits?|this (?:answer|app|query)\b|costs? of (?:this|the) (?:answer|question|query))\b", re.I)
SUPPLIED = re.compile(r"(?:€|\$|£|\b(?:eur|euros?|usd|dollars?|gbp|pounds?|sek|chf)\b)\s*\d|\d\s*(?:€|\$|£|eur|euros?|usd|dollars?|gbp|pounds?|sek|chf)\b|\bper\s+(?:m|sq|square|metre|meter|unit|item|piece)", re.I)
PRICE_DATA = re.compile(r"€|\$|£|\b(?:eur|usd|gbp|sek|chf)\b|\b(?:price|prices|unit cost|cost|costs|hinta|preis|pris|kosten)\b", re.I)


def asks_price(question: str) -> bool:
    return bool(ASK.search(question)) and not NOT_PRICE.search(question) and not SUPPLIED.search(question)


def doc_has_price_data(doc_id: str, root) -> bool:
    d = Path(root) / doc_id
    try:
        for f in sorted(d.glob("text-*.json")):
            words = json.loads(f.read_text()).get("words") or []
            if PRICE_DATA.search(" ".join(str(w.get("text", "")) for w in words)):
                return True
        el = d / "elements.json"
        if el.is_file() and re.search(r'"[^"]*(?:price|cost)[^"]*"\s*:', el.read_text(), re.I):
            return True
    except (OSError, ValueError, AttributeError):
        return True  # unreadable: do not claim absence
    return False


NO_PRICE = ("**There is no price in the drawings.** I can give quantities (counts, areas, lengths, volumes) and an order list "
            "with waste, but no unit price or cost is recorded in this document. Give me a unit price and I will calculate the total.")
