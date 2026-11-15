"""Manual labels projected into ordinary plan maps. No matching or model calls."""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata


def fold(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                            if not unicodedata.combining(c)).split())


# Exact phrases only: abbreviations are conventions, never substring guesses.
ALIASES = {
    'door': 'door|doors|dr|ovi|ovet|tür|türen|tur|turen|dörr|dörrar',
    'window': 'window|windows|win|ikkuna|ikkunat|fenster|fönster',
    'wall': 'wall|walls|seinä|seinät|wand|wände|vägg|väggar',
    'toilet': 'toilet|toilets|wc|water closet|toilette|toiletten|vessa|toalett',
    'sink': 'sink|sinks|washbasin|wash basin|pesuallas|allas|waschbecken|tvättställ',
    'shower': 'shower|showers|suihku|dusche|dusch',
    'bathtub': 'bathtub|bathtubs|bath tub|amme|kylpyamme|badewanne|badkar',
    'stairs': 'stair|stairs|staircase|portaat|treppe|trappa',
    'column': 'column|columns|pillar|pilari|säule|stütze|pelare',
    'duct': 'duct|ducts|air duct|ilmakanava|kanava|lüftungskanal|luftkanal|ventilationskanal',
    'terminal': 'terminal|terminals|air terminal|air terminals|supply air terminal|supply air terminals|extract air terminal|extract air terminals|diffuser|diffusers|tp|tuloilmapääte|tuloilmalaite|poistoilmalaite|luftauslass|luftdurchlass|tilluftsdon|frånluftsdon',
    'pipe': 'pipe|pipes|putki|rohr|rör',
    'valve': 'valve|valves|venttiili|ventil|fire damper|fire dampers|palopelti|brandschutzklappe|brandspjäll',
    'fixture': 'fixture|fixtures|kaluste|armatur',
    'other': 'other|muu|sonstige|övrigt',
}
SYNONYMS = {fold(a): k for k, names in ALIASES.items() for a in names.split('|')}


def canonical_kind(name):
    return SYNONYMS.get(fold(name))


def item_kind(name, canonical=None):
    return canonical or canonical_kind(name) or 'custom:' + fold(name)


def iou(a, b):
    if not a or not b:
        return 0
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0


def _centre(b):
    return ((b[0]+b[2])/2, (b[1]+b[3])/2)


def _inside(point, b):
    return b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]


def same_item(a, b):
    """Two same-kind boxes are one physical item: IoU >= 0.5, or either centre lies inside the other box.

    A box drawn loosely around an already detected door has a low IoU but contains its centre.
    """
    if not a or not b:
        return False
    return iou(a, b) >= .5 or _inside(_centre(a), b) or _inside(_centre(b), a)


def closeness(a, b):
    ca, cb = _centre(a), _centre(b)
    return (iou(a, b), -((ca[0]-cb[0])**2 + (ca[1]-cb[1])**2))


def existing_links(plan):
    """{taught symbol id: id of the detected item it merged with}, for the review panel."""
    out = {}
    for it in plan.get('items', []):
        if it.get('source') == 'taught':
            continue
        for label in (it.get('props') or {}).get('user_labels', []):
            if label.get('taught_symbol_id') is not None:
                out[str(label['taught_symbol_id'])] = it['item_id']
    return out


def project(plan, symbols, page, image=None):
    """Rebuild the manual layer; detector records remain intact and retain their ids.

    Same-kind boxes merge when IoU >= 0.5 or a centre lies inside the other box (see same_item).
    Links record both identities, including repeated manual marks of the same item.
    Legacy find-all records are deliberately excluded, even if previously confirmed.
    """
    plan = deepcopy(plan)
    plan.setdefault('page', page)
    plan.setdefault('image', image or {})
    plan.setdefault('scale', {'m_per_px': None, 'method': 'none', 'confidence': 0})
    items = []
    for it in plan.get('items', []):
        if it.get('source') == 'taught':
            continue
        props = it.setdefault('props', {})
        original = props.pop('_before_user_label', None)
        if original is not None:
            it['conf'] = original['conf']
            for key in ('user_labels', 'confirmed_by_user', 'linked_item_ids'):
                props.pop(key, None)
        items.append(it)
    for s in symbols:
        if not s.get('manual_selection') or s['page'] != page:
            continue
        # A manual teaching has exactly the selected box. Never read legacy matches.
        if not s.get('matches') or s['matches'][0]['status'] != 'confirmed':
            continue
        box, sid = list(s['template_bbox']), str(s['id'])
        kind = item_kind(s['name'], s.get('canonical_kind'))
        iid = 'taught-' + sid
        matches = [it for it in items if it['kind'] == kind and same_item(it.get('bbox_px'), box)]
        target = max(matches, key=lambda it: closeness(it['bbox_px'], box)) if matches else None
        label = {'taught_symbol_id': sid, 'item_id': iid, 'name': s['name'], 'note': s.get('note', ''),
                 'bbox_px': box, 'confirmed_by_user': True}
        if target is None:
            target = {'item_id': iid, 'kind': kind, 'label': s['name'], 'bbox_px': box, 'polygon_px': None,
                      'source': 'taught', 'taught_symbol_id': sid, 'confirmed_by_user': True, 'conf': 1.0, 'props': {}}
            items.append(target)
        props = target.setdefault('props', {})
        props.setdefault('_before_user_label', {'conf': target.get('conf', 0)})
        props.setdefault('user_labels', []).append(label)
        props['confirmed_by_user'] = True
        props['linked_item_ids'] = list(dict.fromkeys([target['item_id'], *props.get('linked_item_ids', []), iid]))
        target['conf'] = 1.0
    plan['items'] = items
    plan['manual_labels'] = True
    return plan


def evidence_step(items):
    marked = [it for it in items if it.props.get('confirmed_by_user')]
    if not marked:
        return None
    detected = sum(it.source != 'taught' for it in items)
    added = sum(it.source == 'taught' for it in items)
    names = list(dict.fromkeys(l['name'] for it in marked for l in it.props.get('user_labels', [])))
    detail = f'{len(items)} cited items = {detected} detected + {added} added by you; {len(marked)} marked by you'
    detail += ' (' + ', '.join('“' + n + '”' for n in names[:4]) + ').'
    return {'kind': 'checked', 'title': 'Marked by you', 'text': detail, 'ok': True}



def subtype(name):
    text = fold(name)
    if text in {'tp', 'tilluftsdon', 'tuloilmapaate', 'tuloilmalaite'} or 'supply air' in text:
        return 'supply'
    if text in {'franluftsdon', 'poistoilmalaite'} or 'extract air' in text:
        return 'extract'
    if text in {'palopelti', 'brandschutzklappe', 'brandspjall'} or 'fire damper' in text:
        return 'fire damper'
    return None


def subtype_matches(item, requested):
    return any(subtype(name) == requested for name in [item.label or '', item.name or '',
               *[label['name'] for label in item.props.get('user_labels', [])]])


def typed_count(question, doc, kind, requested, page=None, hidden=None):
    import time
    from engine.solvers.solve import _answer_obj, _evidence
    items = [it for it in doc.items if it.kind == kind and it.conf >= .5 and (not page or it.page == page)
             and it.item_id not in (hidden or {}) and subtype_matches(it, requested)]
    boxes,cites,scene = _evidence(doc, items)
    text = f'**{len(items)} items labelled as {requested}.**' + (' [1]' if cites else '')
    text += '\n\n- Counted only items with that label; unclassified items may be missing.'
    step = evidence_step(items)
    if step: text += '\n- ' + step['text']
    return _answer_obj(question,[doc.doc_id],text,len(items),'count',min((i.conf for i in items),default=.5),False,
                       boxes,cites,scene,[],'planmap' if doc.mode == 'planmap' else 'index',time.perf_counter())

def query(question, doc_ids, root, hidden=None):
    """Use the ordinary solver for simple counts of a manually labelled kind.

    Unknown qualifiers return None, so a request is never silently narrowed. This
    path prevents a vision recount from replacing the user's explicit items.
    """
    from engine.solvers.data import load_doc
    from engine.router.parser import Parsed
    from engine.solvers.solve import solve, SolverUnsupported
    if len(doc_ids) != 1:
        return None
    doc = load_doc(doc_ids[0], root)
    if not doc:
        return None
    marked = [it for it in doc.items if it.props.get('confirmed_by_user')]
    if not marked:
        return None
    q = fold(question)
    if not re.search(r'\b(how many|count|number of|order|take.?off)\b', q):
        return None
    page_match = re.search(r'\bpage\s+(\d+)\b', q)
    # Exact saved labels and general synonyms resolve to the ordinary kind.
    phrases = {a: k for a, k in SYNONYMS.items() if k in {it.kind for it in marked}}
    phrases.update({fold(l['name']): it.kind for it in marked for l in it.props.get('user_labels', [])})
    for phrase, kind in sorted(phrases.items(), key=lambda p: -len(p[0])):
        pattern = r'(?<!\w)' + re.escape(phrase) + r'(?:s)?(?!\w)'
        if not re.search(pattern, q):
            continue
        rest = re.sub(pattern, '', q)
        rest = re.sub(r'\bpage\s+\d+\b', '', rest)
        rest = re.sub(r'["“”‘’`]', '', rest)
        rest = re.sub(r'\b(how many|number of|count|are|is|there|in|on|this|the|drawing|sheet|document|total|please|should|i|we|order|need|to|takeoff|take-off|on|of|are|do|we|have|mark|marks|marked|label|labels|labelled|labeled|named|called|tagged|saved|taught|my|item|items|instances|instance)\b', '', rest)
        # Resolve a named room only against real enclosing polygons.
        room_scope = re.search(r'\b(?:in|inside)\s+(?:the\s+)?(.+?)(?:[?.!]|$)', q)
        if room_scope and fold(room_scope.group(1)).strip(' ?.!') in {'drawing', 'sheet', 'document', 'this drawing', 'this sheet', 'this document'}:
            room_scope = None
        group_rooms = bool(re.search(r'\b(?:per|by|in each) room\b', q))
        if group_rooms or room_scope:
            prefix = re.split(r'\b(?:per|by|in each) room\b|\b(?:in|inside)\s+(?:the\s+)?', re.sub(pattern, '', q), maxsplit=1)[0]
            prefix = re.sub(r'\b(how many|number of|count|are|is|there|total|please)\b', '', prefix)
            if not prefix.strip(' ?.!,:;'):
                return room_count(question, doc, kind, room_scope.group(1).strip(' ?.!') if room_scope and not group_rooms else None,
                                  int(page_match[1]) if page_match else None, hidden, subtype(phrase))
        if rest.strip(' ?.!,:;'):
            continue
        if subtype(phrase):
            return typed_count(question, doc, kind, subtype(phrase), int(page_match[1]) if page_match else None, hidden)
        try:
            result = solve(question, doc.doc_id, parsed=Parsed('count', kind, None, True), root=root,
                           page=int(page_match[1]) if page_match else None, hidden=hidden)
            result['answer']['text_md'] += '\n\n- Includes items marked by you. Other items may be missing from the drawing data.'
            return result
        except SolverUnsupported:
            return None
    return None


def room_count(question, doc, kind, target=None, page=None, hidden=None, requested_subtype=None):
    """Pixel containment only; absent room polygons are an explicit abstention."""
    import time
    from engine.solvers.solve import _answer_obj, _evidence, _abstain
    from engine.symbol_teach import room_for
    rooms = [it for it in doc.items if it.kind == 'room' and (not page or it.page == page)]
    if target:
        text = re.sub(r'^room\s+', '', fold(target))
        rooms = [it for it in rooms if text in {fold(it.label or ''), fold(str(it.props.get('number') or '')), fold(it.item_id)}]
    rooms = [it for it in rooms if it.polygon_px and len(it.polygon_px) >= 3]
    trace = [{'step':'user_label','detail':'Count indexed items inside room polygons, no model call','ms':0,'model':None,'cost_usd':0}]
    if not rooms:
        return _abstain(question, doc.doc_id, 'I do not have a matching room outline, so I cannot count items in that room.', trace, 'planmap', time.perf_counter())
    candidates = [it for it in doc.items if it.kind == kind and it.conf >= .5 and it.bbox_px and it.item_id not in (hidden or {})
                  and (not requested_subtype or subtype_matches(it, requested_subtype))]
    selected, counts = [], []
    assigned = set()
    for room in rooms:
        count = 0
        geometry = [{'label':room.label or room.item_id, 'polygon_px':room.polygon_px}]
        for it in candidates:
            if it.page == room.page and it.item_id not in assigned and room_for(it.bbox_px, geometry):
                selected.append(it); assigned.add(it.item_id); count += 1
        counts.append((room.label or room.item_id, count))
    boxes,cites,scene = _evidence(doc, selected)
    text = f'**{len(selected)} indexed {kind.removeprefix("custom:")} items inside the room outlines.**'
    if cites: text += ' [1]'
    text += '\n\n' + '\n'.join('- ' + name + ': ' + str(n) for name,n in counts[:3])
    step = evidence_step(selected)
    if step: text += '\n- ' + step['text']
    unknown = len(candidates) - len(selected)
    if not target and unknown: text += f'\n- {unknown} items have no enclosing room outline.'
    return _answer_obj(question, [doc.doc_id], text, len(selected), 'count', min((it.conf for it in selected), default=.5),
                       False, boxes,cites,scene,trace,'planmap',time.perf_counter())
