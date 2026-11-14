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
    named_area = re.search(r'\barea (?:of|for) (?:the |all |this |a )?(.+)', q)
    if area and named_area and not re.match(r'(?:whole |entire |total |net |gross )*(?:building|floor|storey|level|plan|sheet|first|second|third|ground|\d)', named_area[1]):
        return None  # a room/type-specific area is not the printed whole-floor total.
    if not (count or area):
        return None
    whole = bool(re.search(r'\b(?:whole|entire) building\b|\ball (?:floors|storeys|levels)\b', q))
    floor = level(question, title)
    matches, candidates = [], []
    for pt in pts:
        for text, bb in _rows(pt):
            if count:
                m = _COUNT_ROW.search(text)
                if not m:
                    continue
                label = compact(m[1])
                candidates.append((pt.page, bb, m.group(0)))
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
                if label.startswith(('TOTAL','SUBTOTAL','GRANDTOTAL')):
                    candidates.append((pt.page, bb, m.group(0)))
                desired = 'TOTAL' + floor if floor else 'TOTAL'
                if label not in {desired, 'GRAND' + desired}:
                    continue
                val = float(m[2].replace(',',''))
                unit = 'm²' if m[3].upper().startswith('M') else 'SF'
                matches.append((val,'area',pt.page,bb,m.group(0),m[1],unit))
    if not matches:
        if candidates:
            result = _obj(question,doc_id,"**No printed total matches the requested scope.** The table contains other totals; I have not substituted a floor count, wing total or subtotal. Check the cited rows or specify the floor.",None,None,candidates[:8],"printed totals: requested scope unavailable; no subtotal substituted",t0,conf=.5)
            result["reasoning_hint"] = {"steps":[{"kind":"found","title":"Found","text":f"{len(candidates)} printed table rows with other scopes","cite":1,"ok":None},
                                                {"kind":"checked","title":"Checked","text":"No complete total matches the requested floor or building","cite":None,"ok":False}],
                                        "pct_cap":60,"reason":"The requested total is missing or ambiguous; no partial total was substituted.",
                                        "improve":"Identify the full-floor or building total in the cited table."}
            return result
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


def cite_sheet_numbers(result, question, root):
    """Add the actual title-block sheet IDs for pages already cited in a sheet lookup."""
    if not re.search(r'\bwhich (?:sheets?|pages?)\b', question, re.I) or not result.get('citations'):
        return result
    from engine.reader.text import load_page_text
    from engine.titleblock import _sheet
    seen=set()
    additions=[]
    for citation in list(result['citations']):
        doc_id,page=citation.get('doc_id'),citation.get('page')
        if not doc_id or not isinstance(page,int) or (doc_id,page) in seen:
            continue
        seen.add((doc_id,page))
        try:
            block=_sheet(load_page_text(doc_id,page,root))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
        if block is not None and block['text'] not in result['answer'].get('text_md',''):
            additions.append((doc_id,page,block))
    if not additions:
        return result
    labels=[]
    for doc_id,page,block in additions:
        n=max((c.get('n',0) for c in result['citations']),default=0)+1
        result['citations'].append({'n':n,'doc_id':doc_id,'page':page,'kind':'text','bbox_px':block['bbox_px'],'item_ids':[],
                                    'quote':block['text']})
        result['evidence']['boxes'].append({'item_id':f'sheet-text-{page}-{n}','page':page,'bbox_px':block['bbox_px'],'label':str(n)})
        labels.append(f"**{block['text']}** (page {page}) [{n}]")
    result['answer']['text_md']+='\n\nSheet numbers: '+', '.join(labels)+'.'
    result['trace'].append({'step':'text_lookup','detail':'sheet identifiers taken from the title blocks of the already-cited pages',
                            'ms':0,'model':None,'cost_usd':0})
    return result
