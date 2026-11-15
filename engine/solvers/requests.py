"""Narrow quantity/spatial requests that must run before generic property totals.

Uses contract quantities and scene tags only. No document names or model calls.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re

from .data import Doc, Item, load_doc
from .filters import room_filter, room_name, storey_requested
from .solve import _answer_obj, _evidence, _qty, _step, resolve_storey

_DIM = re.compile(r'(\d+(?:\.\d+)?)\s*(mm|cm|m|inches|inch|in|feet|foot|ft)\s*(wide|width|high|height|tall)\b', re.I)
_TO_M = {'mm': .001, 'cm': .01, 'm': 1., 'inches': .0254, 'inch': .0254, 'in': .0254,
         'feet': .3048, 'foot': .3048, 'ft': .3048}


def _number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None


def _result(q, doc, text, items, t0, *, value=None, unit=None, confidence=None, detail):
    boxes, cites, scene = _evidence(doc, items)
    marks = ''.join(f"[{c['n']}]" for c in cites)
    result = _answer_obj(q, [doc.doc_id], text.replace('{marks}', marks), value, unit,
                       confidence if confidence is not None else (1. if doc.mode == 'ifc' else .7),
                       False, boxes, cites, scene, [_step('route', detail)],
                       'index' if doc.mode == 'ifc' else 'planmap', t0)
    result["reasoning_hint"] = {
        "steps": [{"kind":"found", "title":"Found", "text":f"{len(items)} source elements matched the request", "cite":cites[0]["n"] if cites else None, "ok":None},
                  {"kind":"calculated", "title":"Calculated", "text":detail, "cite":None, "ok":None}],
        "pct_cap":round(confidence*100) if confidence is not None and confidence < 1 else 99,
        "reason":"The answer includes missing measurements or inferred geometry; check the stated limits.",
        "improve":"Check the cited source measurements and shared walls on the drawing."}
    return result


def _scoped(q, doc, hidden):
    st = resolve_storey(q, doc.storeys) if doc.mode == 'ifc' else None
    if doc.mode == 'ifc' and storey_requested(q) and st is None:
        return None, st
    return [i for i in doc.items if i.item_id not in hidden and (not st or i.storey == st)
            and (doc.mode == 'ifc' or i.conf >= .5)], st


def dimension_request(q, doc, items, st, t0):
    kind = 'door' if re.search(r'\bdoors?\b', q, re.I) else 'window' if re.search(r'\bwindows?\b', q, re.I) else None
    if not kind:
        return None
    scope = [i for i in items if i.kind == kind]
    where = f' on **{st}**' if st else ''
    if re.search(r'\b(?:fire[- ]rated|acoustic|load[- ]bearing|material|except|excluding|without)\b',q,re.I):
        return None  # let the property/filter solver retain these extra predicates.
    exterior = re.search(r'\b(external|exterior|outer|internal|interior|inner)\b', q, re.I)
    if exterior:
        if any(i.props.get('is_external') is None for i in scope):
            return _result(q,doc,'**The requested inside/outside filter cannot be verified** because some elements lack that property. No unfiltered size schedule is substituted.',scope,t0,confidence=.5,detail='dimension request: external status incomplete')
        want = exterior[1].lower() in ('external','exterior','outer')
        scope = [i for i in scope if bool(i.props['is_external']) == want]
        where += f', {exterior[1].lower()} only'
    # Tags are the very same stable tags displayed in 3D; never search the IFC name for D34.
    tag = re.search(r'\b(?:door|window)\s+([DW]\d+)\b', q, re.I)
    if tag and re.search(r'\b(?:how wide|how high|how tall|width|height|dimensions?|size)\b', q, re.I):
        from engine.scene_cmds import tags
        mapping = tags(doc)
        match = [i for i in scope if mapping.get(i.item_id, '').casefold() == tag[1].casefold()]
        if len(match) != 1:
            return _result(q, doc, f'**No unique {kind} matches {tag[1].upper()}**{where}. Check the tag or selected floor.', [], t0, detail='scene tag lookup; no substituted total')
        item = match[0]
        keys = [('width_m', 'width'), ('height_m', 'height')]
        if re.search(r'\b(?:wide|width)\b', q, re.I): keys = keys[:1]
        elif re.search(r'\b(?:high|tall|height)\b', q, re.I): keys = keys[1:]
        vals = [(k, label, _number(item.q.get(k))) for k, label in keys]
        text = f'**{tag[1].upper()}**: ' + '; '.join(_dim_text(q, label, v) if v is not None else f'{label} is not recorded' for _, label, v in vals) + '. {marks}'
        return _result(q, doc, text, match, t0, value=vals[0][2] if len(vals) == 1 else None, unit='m' if len(vals) == 1 else None, detail='dimension from scene tag -> element quantities')
    dims = {('width_m' if m[3].lower() in ('wide', 'width') else 'height_m'): float(m[1]) * _TO_M[m[2].lower()] for m in _DIM.finditer(q)}
    if len(dims) > 1:
        if re.search(r'\b(?:at least|at most|wider|narrower|taller|shorter|more than|less than|over|under)\b',q,re.I):
            return None  # these bounds are not exact-size equalities.
        known = [i for i in scope if all(_number(i.q.get(k)) is not None for k in dims)]
        hit = [i for i in known if all(math.isclose(float(i.q[k]), v, abs_tol=.0005, rel_tol=0) for k, v in dims.items())]
        label = ' and '.join(f'{k.split("_")[0]} {v:g} m' for k, v in dims.items())
        text = f'**{len(hit)} {kind}s**{where} have **{label}**. {{marks}}'
        if len(known) < len(scope):
            text += f' {len(scope)-len(known)} have incomplete dimensions and are excluded.'
        return _result(q, doc, text, hit, t0, value=len(hit), unit='count', confidence=1. if len(known)==len(scope) else .6, detail='all requested dimensions applied together; tolerance 0.5 mm')
    schedule = re.search(r'\b(?:each width|by width|of each size|by size|width schedule)\b|\bdoor schedule\b', q, re.I)
    if not schedule:
        return None
    keys = ['width_m'] if re.search(r'\bwidth\b', q, re.I) else ['width_m', 'height_m']
    groups = defaultdict(list)
    missing = []
    for i in scope:
        vals = tuple(_number(i.q.get(k)) for k in keys)
        if any(v is None for v in vals):
            missing.append(i)
        else:
            groups[tuple(round(v, 4) for v in vals)].append(i)
    if not scope or not groups:
        return _result(q, doc, f'**No complete {kind} dimensions are recorded**{where}; I cannot make this schedule.', scope, t0, confidence=.5, detail='dimension schedule: missing measurements')
    rows = []
    for size, its in sorted(groups.items()):
        label = ' × '.join(f'{v:g}' for v in size) + ' m'
        rows.append(f'| {label} | {len(its)} |')
    text = (f'**{len(scope)} {kind}s**{where}, grouped by ' + ('width' if len(keys) == 1 else 'width × height') + '. {marks}\n\n'
            '| Size | Count |\n|---|---|\n' + '\n'.join(rows))
    if missing:
        text += f'\n\n{len(missing)} {kind}s have incomplete dimensions; they are outside the size groups.'
    return _result(q, doc, text, scope, t0, value=len(scope), unit='count', confidence=1. if not missing else .6, detail=f'quantity schedule: {len(groups)} size groups, {len(missing)} incomplete')


def summary_request(q, doc, items, st, t0):
    if not re.search(r'\b(?:take[- ]?off|quantit(?:y|ies)|boq)\b', q, re.I):
        return None
    # An explicitly enumerated summary must not become a single wall/door answer.
    specs = []
    for rx, label, kind, quantity, unit in (
        (r'\bfloor area\b', 'Net floor area', 'room', 'area', 'm²'),
        (r'\bwall length\b', 'Wall length', 'wall', 'length', 'm'),
        (r'\bdoors\b', 'Doors', 'door', None, 'count'),
        (r'\bwindows\b', 'Windows', 'window', None, 'count'),
    ):
        if re.search(rx, q, re.I): specs.append((label, kind, quantity, unit))
    if len(specs) < 2:
        return None
    selected_rooms = room_filter(q, [i for i in items if i.kind == 'room'])
    if selected_rooms:
        return _result(q,doc,'**Room-specific take-off needs element-to-room links.** I can identify the room, but cannot apply every requested wall/opening quantity reliably. No whole-floor total is substituted.',selected_rooms[1],t0,confidence=.5,detail='take-off room filter: source associations incomplete')
    rows, evidence, complete = [], [], True
    for label, kind, qty, unit in specs:
        its = [i for i in items if i.kind == kind]
        if qty:
            have = [(i, _qty(i, kind, qty)) for i in its]
            measured = [(i, v) for i, v in have if v is not None]
            v = sum(v for _, v in measured) if measured else None
            missing = len(its)-len(measured)
            amount = f'{v:,.1f}' if v is not None else 'not recorded'
            if missing: amount += f' ({missing} missing)'
            complete = complete and not missing and v is not None
            evidence += [i for i, _ in measured]
        else:
            amount = str(len(its))
            evidence += its
        rows.append(f'| {label} | {amount} | {unit} |')
    text = f'**Quantity take-off**' + (f' for **{st}**' if st else ' for the selected model') + '. {marks}\n\n| Item | Quantity | Unit |\n|---|---|---|\n' + '\n'.join(rows)
    if not complete: text += '\n\nMissing quantities are excluded; those rows are partial.'
    return _result(q, doc, text, list({i.item_id:i for i in evidence}.values()), t0, confidence=1. if complete and doc.mode=='ifc' else .6, detail='explicit take-off: every named quantity reported separately')


def adjacent_request(q, doc, items, st, t0):
    if doc.mode != 'ifc' or not re.search(r'\b(?:next to|adjacent to|adjoin(?:ing)?|neighbou?ring)\b', q, re.I) or not re.search(r'\brooms?\b', q, re.I):
        return None
    rooms = [i for i in items if i.kind == 'room']
    selected = room_filter(q, rooms)
    if not selected or len(selected[1]) != 1:
        return _result(q, doc, '**Name one room to find its neighbours.** I cannot identify a unique room from this question.', selected[1] if selected else [], t0, detail='adjacency: room selection ambiguous or missing')
    name, [target] = selected
    if not target.bbox_m:
        return _result(q, doc, f'**{room_name(target)} has no room position recorded**, so I cannot identify its neighbours.', [target], t0, detail='adjacency: missing geometry')
    b = target.bbox_m
    widths = [_number(i.q.get('thickness_m', i.q.get('width_m'))) for i in items if i.kind == 'wall' and i.storey == target.storey]
    widths = [w for w in widths if w is not None]
    if not widths:
        return _result(q, doc, '**Wall separation is not recorded**, so bounding rectangles alone cannot verify which rooms adjoin.', [target], t0, detail='adjacency: wall thickness missing')
    tolerance = max(widths) + .001  # wall thickness plus one millimetre for rounded exported boxes
    hit = []
    for r in rooms:
        if r.item_id == target.item_id or r.storey != target.storey or not r.bbox_m:
            continue
        c = r.bbox_m
        dx = max(b[0][0]-c[1][0], c[0][0]-b[1][0], 0.)
        dz = max(b[0][2]-c[1][2], c[0][2]-b[1][2], 0.)
        ox = min(b[1][0],c[1][0])-max(b[0][0],c[0][0])
        oz = min(b[1][2],c[1][2])-max(b[0][2],c[0][2])
        # A shared side, never a diagonal corner or an overlapping bounding rectangle.
        if (0 <= dx <= tolerance and ox <= .001 and oz > .001) or (0 <= dz <= tolerance and oz <= .001 and ox > .001):
            hit.append(r)
    if hit:
        text = f'**Rooms beside {room_name(target)} by position:** ' + '; '.join(f'{room_name(r)} ({r.name})' for r in hit) + '. {marks}'
    else:
        text = f'**No adjoining room could be identified beside {room_name(target)}** from the recorded rectangles. {{marks}}'
    text += ' This uses room bounding rectangles and recorded wall thicknesses; shared walls and door connections need checking on the plan.'
    return _result(q, doc, text, [target,*hit], t0, confidence=.6, detail=f'adjacency candidates on the same storey; gap <= recorded wall thickness ({tolerance:g} m)')


def _dim_text(q, label, v):
    from engine import units
    base = f'{label} **{v:g} m**'
    return base + (f' ({units.feet_inches(v)}; {v / 0.3048:,.4g} ft)' if units.imperial_requested(q) else '')


def answer_request(q, doc_ids, root, t0, hidden=()):
    if len(doc_ids) != 1:
        return None
    # Keep ordinary counts/areas on their established routes.
    if not re.search(r'\b(?:schedule|width|height|wide|high|tall|size|take[- ]?off|quantit(?:y|ies)|boq|next to|adjacent|adjoin\w*|neighbou?ring|scale|face)\b', q, re.I):
        return None
    doc = load_doc(doc_ids[0], root)
    if doc is None or doc.mode != 'ifc':
        return None
    items, st = _scoped(q, doc, set(hidden))
    if items is None:
        return _result(q, doc, '**No matching floor was found.** Storeys present: ' + ', '.join(s['name'] for s in doc.storeys) + '.', [], t0, detail='explicit storey filter: no match; no total substituted')
    # F-IMPERIAL: "not a guessed image scale" is an instruction about method, not a request for the drawing scale.
    if re.search(r'\b(?:what|which)\b(?:\s+\w+){0,4}?\s+scale\b', q, re.I) and not re.search(r'\b(?:not|no|never|without|instead of|rather than)\b[^.?]*\bscale\b', q, re.I):
        return _result(q, doc, '**This is an IFC model at real-world size in metres.** A printed drawing scale belongs to an exported sheet, rather than to the 3D model.', [], t0, detail='IFC contract units: metres; no printed sheet scale inferred')
    return dimension_request(q, doc, items, st, t0) or summary_request(q, doc, items, st, t0) or adjacent_request(q, doc, items, st, t0) or wall_face_request(q, doc, items, st, t0)


def quantity_followup(question, history):
    """Retain the previous quantity AND waste when a pronoun asks its unit cost."""
    if not re.search(r'\b(?:those|these|that|them|it)\b', question, re.I) or not re.search(r'\b(?:cost|price)\b', question, re.I):
        return None
    if not re.search(r'(?:EUR|USD|GBP|euros?|dollars?|€|\$|£).*\b(?:per|m2|m²|m3|m³)\b', question, re.I):
        return None
    previous = next((str(h.get('content') or '') for h in reversed(history or []) if h.get('role') == 'user'), '')
    if not re.search(r'\b(?:area|m2|m²|square|volume|length)\b', previous, re.I) or not re.search(r'\b(?:tiles?|flooring|paint|baseboard|skirting|concrete)\b', previous, re.I):
        return None
    return previous.rstrip('?.! ') + '. ' + question


def wall_face_request(q, doc, items, st, t0):
    """An explicit one-face quantity uses the source's one-side area, not both faces."""
    if not re.search(r'\b(?:one|single|a) face\b',q,re.I) or not re.search(r'\bwalls?\b',q,re.I) or not re.search(r'\b(?:net|gross)\b',q,re.I):
        return None
    walls=[i for i in items if i.kind=='wall']
    exterior=re.search(r'\b(external|exterior|outer|internal|interior|inner)\b',q,re.I)
    if exterior:
        want=exterior[1].lower() in ('external','exterior','outer')
        known=[w for w in walls if w.props.get('is_external') is not None]
        if len(known)!=len(walls):
            return None  # the geometry route may have space boundaries; never drop an unknown flag.
        walls=[w for w in known if bool(w.props['is_external'])==want]
    key='gross_side_area_m2' if re.search(r'\bgross\b',q,re.I) else 'net_side_area_m2'
    vals=[(w,_number(w.q.get(key))) for w in walls]
    if not walls or any(v is None for _,v in vals):
        return None
    total=sum(v for _,v in vals)
    text=f'**{total:,.2f} m²** for **one face** of the ' + (exterior[1].lower()+' ' if exterior else '') + 'walls' + (f' on **{st}**' if st else '') + f', using the model’s {key.split("_")[0]} side-area quantities. {{marks}}'
    return _result(q,doc,text,walls,t0,value=round(total,4),unit='m²',detail='sum source one-side wall areas; openings already deducted in net quantities')


def ensure_answer_text(res):
    """A grounded numeric reader result can still omit prose; always display it."""
    a=res.get('answer') or {}
    text=re.sub(r'\[\d+\]|\W','',a.get('text_md') or '')
    if text:
        return res
    value=a.get('value')
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and not a.get('abstained') and res.get('citations'):
        marks=''.join(f"[{c['n']}]" for c in res['citations'])
        a['text_md']=f'**{value:g}' + (f" {a['unit']}" if a.get('unit') else '') + f'**, from the cited source. {marks}'
    else:
        a.update(text_md='I could not verify a readable answer from the selected drawing. Please name the item or a specific sheet.',value=None,confidence=.3)
    return res


def translate_count(question):
    """Bounded common count grammar; unknown qualifiers are left to the full reader."""
    kinds={'ovea':'doors','ovia':'doors','ikkunaa':'windows','ikkunoita':'windows','huonetta':'rooms','seinaa':'walls',
           'turen':'doors','fenster':'windows','raume':'rooms','wande':'walls',
           'dorrar':'doors','fonster':'windows','rum':'rooms','vaggar':'walls'}
    floors={'pohjakerroksessa':'ground floor','maantasokerroksessa':'ground floor','kellarissa':'basement',
            'erdgeschoss':'ground floor','keller':'basement','bottenvaningen':'ground floor','kallaren':'basement'}
    from .filters import fold
    q=fold(question)
    patterns=[r'(?:kuinka monta|montako) (?P<kind>\w+)(?: (?P<floor>\w+))?(?: on)?',
              r'wie viele (?P<kind>\w+)(?: gibt es)?(?: (?:im|in dem) (?P<floor>\w+))?',
              r'hur manga (?P<kind>\w+)(?: finns det)?(?: (?:pa|i) (?P<floor>\w+))?']
    for pat in patterns:
        m=re.fullmatch(pat,q)
        if m and m['kind'] in kinds and (not m['floor'] or m['floor'] in floors):
            return f"How many {kinds[m['kind']]} are there" + (f" on the {floors[m['floor']]}" if m['floor'] else '') + '?'
    return None
