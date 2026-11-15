"""Prioritize the actual scan evidence; retain every replay operand as detail.

The steps form a graph keyed by id. Importance order is intentionally different
from evaluation order; calc.validate resolves and checks that graph.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from engine.calc import input_value, number, step, step_source


def attach(res, question):
    card = res.get('reasoning') or {}
    calc = card.get('calc') or {}
    method = calc.get('method') or {}
    if not str(method.get('id', '')).startswith(('scan-', 'reader-')):
        return
    detail = [s for s in calc.get('steps') or [] if not s['id'].startswith('scan-overview-')]
    for s in detail:
        s['level'] = 'detail'
    by_id = {s['id']: s for s in detail}
    overview = []

    def promote(s, section):
        s.update(level='main', section=section)
        overview.append(s)

    def alias(sid, original, label, section, note=None):
        if original not in by_id:
            return
        s = by_id[original]
        promote(step(sid, label, s['expr'], s['value'], s['unit'],
                     [input_value(s['label'], s['value'], s['unit'], step_source(original))],
                     s.get('note', '') if note is None else note, 'source'), section)

    # The real answer and its selected method always precede image metadata.
    result = calc.get('result') or {}
    if number(result.get('value')):
        alias('scan-overview-result', 'result', 'Result · ' + method['label'], 'result', method['why_chosen'])
    elif isinstance(result.get('value'), dict):
        for kind in list(result['value'])[:2]:
            alias('scan-overview-result-' + kind, 'category-' + kind, 'Result · ' + kind, 'result', method['why_chosen'])

    from engine.router.parser import parse
    parsed = parse(question)
    groups = defaultdict(list)
    for row in calc.get('inventory_rows') or []:
        values = row.get('values') or {}
        if not values.get('alternative') and values.get('kind') not in (None, 'text', 'dimension', 'other'):
            groups[values['kind']].append(row)
    filters = defaultdict(list)
    for t in res.get('trace') or []:
        data = t.get('data') or {}
        if data.get('method') == 'score_filter':
            filters[data.get('kind')].append(data)
    extraction = defaultdict(dict)
    for s in detail:
        if s.get('label', '').startswith('Alternative saved extraction'):
            continue
        for inp in s.get('inputs') or []:
            ref = inp.get('source') or {}
            field = ref.get('field', '')
            prefix = 'provenance.extraction.classes.'
            if field.startswith(prefix) and '.' in field[len(prefix):]:
                kind, name = field[len(prefix):].split('.', 1)
                extraction[(kind, ref.get('doc_id'), ref.get('page'))][name] = s['value']
    # Requested class first; other inventory classes provide background context.
    for kind in sorted(groups, key=lambda k: (k != parsed.kind, k))[:6]:
        rows = groups[kind]
        values = [r['values'].get('score') for r in rows if number(r['values'].get('score'))]
        note = 'Saved class inventory before question scope and score filters; not an additional answer total.'
        if values:
            note += f' Retained scores: min {min(values):.3g}, median {median(values):.3g}; not calibrated accuracy.'
        if filters[kind]:
            note += ' Actual answer selection: ' + '; '.join(
                f"score ≥ {d['score_threshold']:g}: {d['retained']} kept, {d['rejected']} dropped of {d['before']} saved items"
                for d in filters[kind]) + '.'
        else:
            note += ' No runtime score filter for this class was recorded.'
        recorded = [(did, page, stats) for (k, did, page), stats in extraction.items() if k == kind]
        if recorded:
            for did, page, stats in recorded:
                note += f' Extraction page {page}: ' + ', '.join(f'{k.replace("_", " ")} {v:g}' for k, v in stats.items()) + '.'
        else:
            note += ' Extraction score threshold and dropped proposals were not recorded; saved item scores cannot reconstruct them.'
        promote(step('scan-overview-class-' + kind, 'Detections · ' + kind,
                     'Σ(1 per selected saved class item)', len(rows), 'count',
                     [input_value('saved ' + kind, 1, 'count', r['source']) for r in rows], note, 'sum'), 'detections')

    pages = method.get('pages') or []
    # One scale overview; complete per-page proofs and candidates stay in detail.
    page = next((p for p in pages if number(p.get('value'))), None)
    scale = method.get('scale') or page
    if scale and number(scale.get('value')):
        ref = {'kind': 'measurement', 'doc_id': (page or {}).get('doc_id') or next(iter(res.get('doc_ids') or []), ''),
               'record': scale, 'text': 'Actual selected page scale; candidates and source operands are retained in scale proofs.'}
        note = scale.get('why_chosen', '')
        if (res.get('answer') or {}).get('unit') == 'count':
            note = 'Scale is not used to count items. ' + note
        if len(pages) > 1:
            note += ' Other page scales and their operands are retained in detail.'
        promote(step('scan-overview-scale', 'Scale · ' + scale.get('label', scale.get('id', 'selected method')),
                     'selected physical scale', scale['value'], 'm/px',
                     [input_value('chosen metres per pixel', scale['value'], 'm/px', ref)], note, 'source'), 'scale')

    alias('scan-overview-recount', 'scan-recount-difference', 'Second look · difference and reconciliation', 'recount')
    alias('scan-overview-margin', 'scan-margin-total', 'Margin · supported variation', 'margin', (card.get('margin') or {}).get('why', ''))
    conf = card.get('confidence') or {}
    if number(conf.get('pct')) and conf.get('factors'):
        did = next(iter(res.get('doc_ids') or []), '')
        ref = {'kind': 'measurement', 'doc_id': did, 'record': conf,
               'text': 'Final confidence factors; signed percentage points, not detection scores.'}
        promote(step('scan-overview-confidence', 'Confidence · ' + conf.get('pct_kind', 'recorded score').replace('_', ' '),
                     'Σ(signed confidence factors)', conf['pct'], '%',
                     [input_value(f['label'], f['delta'], '% points', ref) for f in conf['factors']],
                     conf.get('reason', ''), 'sum'), 'confidence')
    # At most 12 prominent steps, including multi-class answer results.
    calc['steps'] = overview[:12] + detail
