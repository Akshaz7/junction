"""Select explicitly scoped printed totals without confusing them with subtotals.

Consumes extracted page text only. No PDF ingestion or document-specific values.
"""
from __future__ import annotations
import re

_LEVEL = r'(?:ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)'
_AREA_ROW = re.compile(r'(.+?)\s*=?\s*(\d[\d,]*(?:\.\d+)?)\s*(SF|SQ\.?\s*FT\.?|M[²2])\b', re.I)
_COUNT_ROW = re.compile(r'\b(TOTAL|(?:' + _LEVEL + r')\s*FLOOR)\s*=\s*(\d+)\s*(DORMS?|ROOMS?|APARTMENTS?|UNITS?|BEDS?)\b', re.I)


def compact(s):
    return re.sub(r'[^A-Z0-9]+', '', s.upper())


def level(question, title):
    title = re.sub(r"[_-]+", " ", title)
    found = re.findall(r'\b(' + _LEVEL + r')\s*[- ]?floor\b', question, re.I)
    if not found and re.search(r'\b(?:this|the) floor\b|\bfloor area\b', question, re.I):
        found = re.findall(r'\b(' + _LEVEL + r')\s*[- ]?floor\b', title, re.I)
    return compact(found[0] + 'FLOOR') if len(set(x.lower() for x in found)) == 1 else None


def printed_total(question, doc_id, pts, title, t0):
    """A matched full-floor/whole-building row wins over any partial wing total."""
    from engine.sheetqa import _obj, _rows, M2_PER_SF
    q = question.lower()
    if re.search(r'\b(?:accessible|aba|single|double|disabled|ensuite|wheelchair|each|by type|wing|circulation)\b', q):
        return None
    count = bool(re.search(r'\bhow many\b', q) and re.search(r'\b(?:dorms?|rooms?|apartments?|units?|beds?)\b', q))
    area = bool(re.search(r'\b(?:total|gross|overall|net)\b.*\b(?:area|square metres|square meters|m2|m²)\b', q))
    if not (count or area):
        return None
    whole = bool(re.search(r'\b(?:whole|entire) building\b|\ball (?:floors|storeys|levels)\b', q))
    floor = level(question, title)
    matches = []
    for pt in pts:
        for text, bb in _rows(pt):
            if count:
                m = _COUNT_ROW.search(text)
                if not m:
                    continue
                label = compact(m[1])
                if label != ('TOTAL' if whole else floor):
                    continue
                noun = m[3].lower()
                # Do not turn a bed count into a room count.
                request = 'dorm' if re.search(r'\bdorm', q) else 'room' if re.search(r'\broom',q) else 'bed' if re.search(r'\bbed',q) else 'unit'
                recorded = 'dorm' if noun.startswith('dorm') else 'room' if noun.startswith('room') else 'bed' if noun.startswith('bed') else 'unit'
                if request != recorded and {request,recorded} != {'dorm','room'}:
                    continue
                matches.append((float(m[2]), 'count', pt.page, bb, m.group(0), m[1], noun))
            else:
                m = _AREA_ROW.fullmatch(text.strip())
                if not m:
                    continue
                label = compact(m[1])
                desired = 'TOTAL' + floor if floor else 'TOTAL'
                if label not in {desired, 'GRAND' + desired}:
                    continue
                val = float(m[2].replace(',',''))
                unit = 'm²' if m[3].upper().startswith('M') else 'SF'
                matches.append((val,'area',pt.page,bb,m.group(0),m[1],unit))
    if not matches:
        return None
    # Repeated rows only agree when their labels, units AND quantities agree.
    signatures={(v,typ,compact(label),unit) for v,typ,pg,bb,txt,label,unit in matches}
    if len(signatures) != 1:
        return None
    val,typ,pg,bb,txt,label,unit=matches[0]
    hits=[(p,b,t) for _,_,p,b,t,_,_ in matches]
    if typ == 'count':
        text=f'**{val:g} {unit}** ' + ('in the whole building' if whole else 'on ' + re.sub(r'(?i)(floor)$', r' floor', label.lower()).strip()) + ', from the printed count table. {marks}'
        return _obj(question,doc_id,text,int(val),'count',hits,'matched printed count scope; no floor count substituted for a building total',t0)
    m2=val*M2_PER_SF if unit=='SF' else val
    text=f'**{m2:,.1f} m²**, from the printed **{label.strip()}** row' + (f' ({val:,.0f} SF × 0.09290304)' if unit=='SF' else '') + '. {marks}'
    if re.search(r'\b(?:net|gross)\b',q) and not re.search(r'\b(?:net|gross)\b',label,re.I):
        text+=' The table does not identify that total as net or gross.'
    return _obj(question,doc_id,text,round(m2,4),'m2',hits,'matched the full printed total label, not a wing subtotal',t0)


def answer_printed(question, doc_ids, root, t0):
    if len(doc_ids) != 1 or not re.search(r'\b(?:area|dorms?|rooms?|apartments?|units?|beds?)\b', question,re.I):
        return None
    import json
    from pathlib import Path
    from engine.reader.text import load_page_text
    d = Path(root)/doc_ids[0]
    if (d/'elements.json').exists():
        return None
    try:
        meta=json.loads((d/'doc.json').read_text())
    except (OSError,ValueError):
        return None
    n=meta.get('pages') or 1
    n=len(n) if isinstance(n,list) else int(n)
    pts=[load_page_text(doc_ids[0],pg,root) for pg in range(1,min(n,12)+1)]
    return printed_total(question,doc_ids[0],pts,meta.get('title') or '',t0)
