"""Plain source IFC quantities before text-sheet and named-room heuristics."""
from dataclasses import replace
from pathlib import Path
import re
import time

from engine.solvers.data import load_doc, load_sheet_parent


NOUNS = {
    'rooms': 'room', 'spaces': 'room', 'doors': 'door', 'windows': 'window',
    'walls': 'wall', 'stairs': 'stairs', 'staircases': 'stairs', 'columns': 'column',
    'beams': 'beam', 'slabs': 'slab', 'roofs': 'roof', 'railings': 'railing',
    'light fixtures': 'light', 'sanitary fixtures': 'sanitary',
}
PLAIN_COUNT = re.compile(
    r'^\s*(?:how many|(?:what is the )?(?:total )?number of|count(?: all| the)?)\s+'
    r'(?:all (?:the )?)?(' + '|'.join(NOUNS) + r')(?:\s*\(\s*(?:rooms?|spaces?)\s*\))?'
    r'\s*(?:[?.]?\s*$|(?:are there|are shown|are present|are modelled|are modeled|in|on)\b)', re.I)


def query_doc(doc_id, root, question):
    whole = bool(re.search(r'\b(?:in|of|across) (?:the|this) (?:(?:whole|entire) )?(?:model|building)\b', question, re.I))
    return load_doc(doc_id, Path(root)) or load_sheet_parent(doc_id, Path(root), whole=whole)


def answer(question, doc_ids, root, t0=None, hidden=()):
    """Only unqualified occurrence counts; detailed/filtered questions keep their routes."""
    if len(doc_ids) != 1:
        return None
    from engine.router.parser import parse
    from engine.solvers.solve import requested_area_key, solve
    parsed = parse(question)
    if parsed.type == 'area' and requested_area_key(question, parsed.kind):
        doc = query_doc(doc_ids[0], root, question)
        if doc is not None and doc.mode == 'ifc':
            return solve(question, doc_ids[0], parsed=parsed, root=root,
                         hidden={iid: iid for iid in hidden})
        return None
    if not (match := PLAIN_COUNT.search(question)):
        return None
    # Do not silently discard filters following the generic noun.
    tail = question[match.end(1):]
    if re.search(r'\b(?:with|without|wider|narrower|larger|smaller|external|internal|exterior|interior|than|types?|each|per)\b',
                 re.sub(r"'[^']*'|\"[^\"]*\"|“[^”]*”", '', tail), re.I):
        return None
    doc = query_doc(doc_ids[0], root, question)
    if doc is None or doc.mode != 'ifc':
        return None
    t0 = t0 or time.perf_counter()
    from engine.ifc_accuracy import prepare_doc, annotate
    from engine.solvers.solve import _answer_obj, _evidence, _step, resolve_storey, _abstain
    from engine.solvers.filters import storey_requested
    doc = prepare_doc(doc, root, for_count=True)
    kind = NOUNS[match[1].lower()]
    storey = resolve_storey(question, doc.storeys)
    if storey_requested(question) and not storey:
        return _abstain(question, doc.doc_id, 'No matching floor was found in the selected model.', [], 'index', t0)
    items = [i for i in doc.items if i.item_id not in hidden and (not storey or i.storey == storey)]
    scoped = replace(doc, items=items)
    if kind in ('light', 'sanitary'):
        from engine import mep
        source = replace(scoped, doc_id=doc.meta.get('sheet_of') or doc.doc_id)
        index = mep.load_index(source)
        if index is None:
            return None  # No typed service inventory: keep the guarded fallback.
        kinds = {'light'} if kind == 'light' else mep._kinds_of(['fixture'])
        selected = {r['id'] for r in index['services'] if r['k'] in kinds}
        items = [i for i in items if i.item_id in selected]
    else:
        items = [i for i in items if i.kind == kind]
    boxes, cites, scene = _evidence(doc, items)
    scope = f'on **{storey}**' if storey else 'in the selected model'
    text = f'**{len(items)} {match[1].lower()}** {scope}. ' + ''.join(f'[{c["n"]}]' for c in cites)
    if kind == 'room' and not items:
        text += ' This model has no indexed rooms; a separate architectural model may contain them.'
    trace = [_step('route', 'plain IFC occurrence count before text-sheet and named-room heuristics'),
             _step('calc', f'Count {len(items)} matching occurrences after floor, hidden-item and aggregate filters.')]
    result = _answer_obj(question, doc_ids, text, len(items), 'count', 1., False, boxes, cites, scene, trace, 'index', t0)
    return annotate(result, question, scoped, root)
