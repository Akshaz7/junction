"""Describe the scan/reader method actually used; no new inference or writes."""
from __future__ import annotations

import copy
from pathlib import Path

from engine.scale_policy import LABEL
from engine.scale_proof import read_json


def describe(res, question, root, reader=None):
    from engine.router.parser import parse
    from engine.solvers.data import load_doc
    root = Path(root)
    pages, alternatives = [], []
    parsed = parse(question)
    for did in res.get('doc_ids') or []:
        doc = load_doc(did, root)
        if not doc or doc.mode != 'planmap':
            continue
        for page, scale in (doc.meta.get('page_scales') or {1: doc.scale}).items():
            pm = read_json(root / did / f'planmap-{page}.json')
            if not any(i.get('source') in ('det', 'seg', 'vlm', 'vision') for i in pm.get('items') or []):
                continue
            selection = copy.deepcopy((scale or {}).get('selection') or {})
            for alt in selection.get('alternatives') or []:
                alt.setdefault('label', LABEL.get(alt['id'], alt['id'].replace('-', ' ')))
                alt.setdefault('unit', 'm/px')
            pages.append({'doc_id': did, 'page': page, 'value': (scale or {}).get('m_per_px'),
                          'unit': 'm/px', **selection})
            alternatives.extend(selection.get('alternatives') or [])
            for name in ('planmap-det.json', 'planmap-seg.json'):
                alternate = read_json(root / did / name)
                items = alternate.get('items') or []
                if not items:
                    continue
                if parsed.type == 'count' and parsed.kind:
                    items = [i for i in items if i.get('kind') == parsed.kind]
                alternatives.append({'id': name.removesuffix('.json'), 'label': 'Saved ' + ('detector' if '-det.' in name else 'segmenter') + ' inventory',
                                     'value': len(items), 'unit': 'count', 'doc_id': did, 'page': alternate.get('page', 1),
                                     'rejected_because': 'Comparison extraction only; the answer uses the selected plan-map items and its recorded filters, not this inventory.'})
    if not pages and not reader:
        return None
    unit = (res.get('answer') or {}).get('unit')
    method = {'id': 'scan-inventory', 'label': 'Saved detector and segmenter inventory',
              'why_chosen': 'Describe the saved per-class items, scores and extraction settings; no new detector run or physical measurement is inferred.',
              'alternatives': alternatives, 'pages': pages}
    if len(pages) == 1:
        method['scale'] = {k: v for k, v in pages[0].items() if k not in ('doc_id', 'page')}
    if unit == 'count':
        method.update(id='scan-count', label='Count selected scan items after question filters',
                      why_chosen='The answer counts the selected saved items after the recorded class, scope, score and duplicate filters. Physical scale is not required for a count; alternate extractions remain comparisons.')
    elif unit in ('m', 'm2', 'm3'):
        label = method.get('scale', {}).get('label', 'page-specific physical scales')
        method.update(id='scan-pixel-measurement', label='Pixel geometry using ' + label,
                      why_chosen='The solver uses the ranked page scale selected before solving. Printed quantities, when present, retain their source values; pixel geometry uses that page’s scale. ' + method.get('scale', {}).get('why_chosen', 'Each page has its own scale selection.'))
    if reader:
        selected = set(reader.get('selected_refs') or [])
        measurements = [e for e in reader.get('calculations') or [] if e.get('tool') == 'measure' and e.get('evidence_ref') in selected]
        tools = sorted({e.get('tool') for e in reader.get('tool_calls') or [] if e.get('tool')})
        method.update(id='reader-tools', label='Drawing reader using ' + (', '.join(tools) or 'recorded source observations'),
                      why_chosen='This answer comes from the reader’s recorded tool observations and selected evidence. Model observations and planner-selected coordinates remain explicitly identified; they are not an independent survey.')
        if measurements:
            supplied = any(e.get('supplied_scale') or e.get('ratio') for e in measurements)
            method.update(id='reader-pixel-measurement', label='Reader-selected pixel geometry and explicit scale',
                          why_chosen='Replay the selected reader coordinates, unit conversions and recorded scale for this answer. ' +
                          ('A planner-supplied scale/ratio was used; it is not established as a printed dimension or verified physical scale.' if supplied else 'The highest ranked available page scale was used; scale selection is recorded with the measurement.'))
            method['measurements'] = [{'doc_id': e['doc_id'], 'page': e['page'], 'value': e['m_per_px'], 'unit': 'm/px',
                                       'scale_origin': e['scale_origin']} for e in measurements]
            if len(measurements) == 1:
                e = measurements[0]
                if e.get('supplied_scale') or e.get('ratio'):
                    old_scale = method.get('scale')
                    if old_scale:
                        alternatives.append({'id': old_scale['id'], 'label': old_scale['label'], 'value': old_scale.get('value'), 'unit': 'm/px',
                                             'rejected_because': 'The recorded reader measurement used the supplied planner scale/ratio; this is available page context, not the scale used for that result.'})
                    method['scale'] = {'id': 'reader-supplied-ratio' if e.get('ratio') else 'reader-supplied-scale',
                                       'label': 'Planner-supplied ratio and image DPI' if e.get('ratio') else 'Planner-supplied numeric scale',
                                       'value': e['m_per_px'], 'unit': 'm/px', 'why_chosen': method['why_chosen'], 'alternatives': []}
    return method
