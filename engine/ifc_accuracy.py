"""ACC-IFC: hierarchy-aware counts and measured room areas for old/new indexes.

Only JSON snapshots are cached. Source IFC fallback is optional; no artifacts
are modified, and missing geometry remains explicitly unverified.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import re
import threading
from functools import wraps

_CACHE = OrderedDict()
_LOCK = threading.RLock()
MEASUREMENT_COUNT = re.compile(r'\bhow many\s+(?:(?:square|cubic|linear|running)\s+)?(?:m[²³23]?|metres?|meters?|feet|foot|ft|inches?|litres?|liters?|gallons?|kilograms?|kg|tonnes?|tons?|pounds?|lbs?)\b', re.I)


def type_class(cls):
    return str(cls or '').endswith(('Type', 'Style')) or cls in ('IfcTypeObject', 'IfcTypeProduct')


def is_item_count(question):
    from engine.router.parser import parse
    p = parse(question)
    # People/capacity are not model occurrences, even when a room is named.
    capacity = re.search(r'\b(?:people|persons?|occupants?|occupancy|capacity|seating)\b', question, re.I)
    return p.type == 'count' and p.kind is not None and not capacity and not MEASUREMENT_COUNT.search(question)


def default_root():
    from engine.solvers.solve import ARTIFACTS
    return Path(os.environ.get('ARTIFACTS_DIR') or ARTIFACTS)


def checked_solver(fn):
    @wraps(fn)
    def checked(question, doc_id, parsed=None, root=None, page=None, hidden=None):
        root = Path(root) if root is not None else default_root()
        res = fn(question, doc_id, parsed=parsed, root=root, page=page, hidden=hidden)
        from engine.solvers.data import load_doc, load_sheet_parent
        doc = load_doc(doc_id, root) or load_sheet_parent(doc_id, root)
        if doc is not None and doc.mode == 'ifc':
            doc = prepare_doc(doc, root, geometry=wants_room_geometry(question), question=question)
            if hidden:
                doc = replace(doc, items=[i for i in doc.items if i.item_id not in hidden])
            res = annotate(res, question, doc, root)
        return res
    return checked


def checked_analytics(fn):
    @wraps(fn)
    def checked(question, doc, t0, solve_fn=None):
        if doc.mode == 'ifc':
            doc = prepare_doc(doc, default_root(), for_count=is_item_count(question),
                              geometry=wants_room_geometry(question), question=question)
        res = fn(question, doc, t0, solve_fn)
        return annotate(res, question, doc, default_root()) if res is not None else None
    return checked


def source_path(doc_id, root):
    root = Path(root)
    source = root / doc_id / 'source.ifc'
    if source.is_file():
        return source
    try:
        meta = json.loads((root / doc_id / 'doc.json').read_text())
        path = (meta.get('files') or {}).get('ifc')
        if not path:
            return None
        repo = Path(__file__).resolve().parents[1]
        dataset = Path(os.environ.get('DATASET_ROOT') or repo / 'data/full/junction-dataset')
        return next((p for p in (Path(path), dataset / path, repo / path,
                                repo / 'data/junction-dataset-preview' / path, root / doc_id / path)
                     if p.is_file()), None)
    except (OSError, ValueError, TypeError):
        return None


def load_index(doc, root, *, geometry=False):
    from pipeline.ifc_accuracy import VERSION, build
    did = doc.meta.get('sheet_of') or doc.doc_id
    sidecar = Path(root) / did / 'ifc-accuracy.json'
    source = source_path(did, root)
    path = sidecar if sidecar.is_file() else source
    if path is None:
        return None
    try:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size, geometry)
        with _LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
            if path == sidecar:
                idx = json.loads(sidecar.read_text())
                if (idx.get('version') != VERSION or not isinstance(idx.get('rows'), list)
                        or any(not isinstance(r, dict) or not isinstance(r.get('item_id'), str)
                               or not isinstance(r.get('ifc_class'), str) for r in idx['rows'])):
                    return None
                # A metadata-only sidecar must not mask an available source mesh.
                need = geometry and any(r['ifc_class'] == 'IfcSpace' and
                                        ('space_area' not in r or 'stored_gross_m2' not in (r.get('space_area') or {}))
                                        for r in idx['rows'])
                if need and source is not None:
                    import ifcopenshell
                    idx = build(ifcopenshell.open(str(source)), geometry=True)
            else:
                import ifcopenshell
                idx = build(ifcopenshell.open(str(source)), geometry=geometry)
            _CACHE[key] = idx
            while len(_CACHE) > 2:
                _CACHE.popitem(last=False)
            return idx
    except (OSError, ValueError, TypeError, RuntimeError, ImportError, AttributeError, KeyError):
        return None


def prepare_doc(doc, root, *, for_count=False, geometry=False, question=''):
    """Recover unindexed IfcSpaces and apply metadata without mutating a cached Doc."""
    if doc.mode != 'ifc':
        return doc
    from engine.solvers.data import Item
    idx = load_index(doc, root, geometry=geometry)
    rows = {r['item_id']: r for r in (idx or {}).get('rows', [])}
    items = list(doc.items)
    from engine.solvers.filters import room_filter
    net_requested = bool(re.search(r'\bnet\b', question, re.I))
    gross_requested = bool(re.search(r'\bgross\b', question, re.I))
    total_requested = bool(re.search(r'\b(?:total|sum|overall|whole|entire)\b', question, re.I))
    # An unqualified whole-model/floor total uses gross Qto when available.
    # Named room areas and room filters retain their declared net quantities.
    from engine.router.parser import parse
    gross_requested |= (total_requested and parse(question).type == 'area'
                        and room_filter(question, [i for i in items if i.kind == 'room']) is None)
    present = {i.item_id for i in items}
    # A floor sheet stays on that floor. Other selected files are never searched
    # or combined: discipline models with no spaces must say so.
    levels = {s['name'] for s in doc.storeys}
    for gid, row in rows.items():
        if row['ifc_class'] == 'IfcSpace' and gid not in present and (not doc.meta.get('sheet_of') or row.get('storey') in levels):
            items.append(Item(gid, 'room', name=row.get('name'), storey=row.get('storey'), source='ifc',
                              props={'ifc_class': 'IfcSpace', 'long_name': row.get('long_name')}))
    from engine.space_dedupe import split_spaces
    kept_rooms, excluded_spaces = split_spaces([i for i in items if i.kind == 'room'])
    drop = {r.item_id for r, _ in excluded_spaces}
    items = [i for i in items if i.item_id not in drop]
    result = []
    for it in items:
        row = rows.get(it.item_id, {})
        props = {**it.props, **{k: row[k] for k in ('aggregate_ancestors', 'count_component_of', 'count_status', 'proxy_kind') if k in row}}
        if it.kind == 'room' and row.get('long_name'):
            props['long_name'] = row['long_name']
        q = dict(it.q)
        check = row.get('space_area') or props.get('space_area')
        check = check if isinstance(check, dict) else None
        if check:
            props['space_area'] = check
            if check.get('stored_gross_m2') is not None:
                q['gross_floor_area_m2'] = check['stored_gross_m2']
            if check.get('stored_net_m2') is not None:
                q['net_floor_area_m2'] = check['stored_net_m2']
            if check.get('measured_m2') is not None:
                q['measured_floor_area_m2'] = check['measured_m2']
        if it.kind == 'room':
            # A space body can describe gross extent rather than usable net area.
            # If its footprint matches gross Qto but conflicts with net Qto,
            # keep the declared net value for net requests and flag the check.
            gross = q.get('gross_floor_area_m2')
            measured = (check or {}).get('measured_m2')
            stored_net = q.get('net_floor_area_m2')
            gross_geometry = (gross is not None and measured is not None and measured > 0
                              and abs(gross - measured) / measured <= .02 + 1e-12
                              and (check or {}).get('status') == 'flag')
            if not net_requested and gross_requested and gross is not None:
                selected, basis = gross, 'stored gross floor area'
            elif net_requested and measured is not None and not gross_geometry:
                selected, basis = measured, 'measured footprint'
            elif stored_net is not None and gross is not None:
                selected, basis = stored_net, 'stored net floor area'
            elif gross is not None:
                selected, basis = gross, 'stored gross floor area'
            else:
                selected, basis = measured, 'measured footprint'
            if gross_geometry:
                props['footprint_basis'] = 'Footprint agrees with gross floor area; it does not independently measure the declared net area.'
            if selected is None:
                selected = q.get('net_floor_area_m2', q.get('area_m2'))
                basis = 'stored area (geometry unavailable)'
            if selected is not None:
                q['selected_floor_area_m2'] = selected
                props['selected_area_basis'] = basis
        if for_count and props.get('count_component_of'):
            continue
        if for_count and type_class(props.get('ifc_class')):
            continue
        # Proxies never masquerade as native occurrences; counts report them
        # separately, only when their occurrence label explicitly identifies one.
        kind = 'proxy' if props.get('ifc_class') == 'IfcBuildingElementProxy' else it.kind
        result.append(replace(it, kind=kind, props=props, q=q))
    complete = (not idx.get('errors')) if idx is not None else bool(items) and all(i.props.get('count_status') == 'verified' for i in items)
    return replace(doc, items=result, meta={**doc.meta, 'ifc_accuracy_complete': complete,
                                           'space_inventory_complete': bool(idx and idx.get('space_inventory_complete')),
                                           'excluded_spaces': [{'item_id': r.item_id, 'name': r.name, 'reason': w} for r, w in excluded_spaces]})


def count_rows(rows, doc, root):
    """Apply the same hierarchy to MEP/quantity rows, preserving every other field."""
    checked = prepare_doc(doc, root)
    props = {i.item_id: i.props for i in checked.items}
    idx = load_index(doc, root)
    by = {r['item_id']: r for r in (idx or {}).get('rows', [])}
    return [r for r in rows if not by.get(r.get('item_id') or r.get('id'),
                                        props.get(r.get('item_id') or r.get('id'), {})).get('count_component_of')]


def count_index(index, doc):
    if index is None:
        return None
    return {**index, **{key: count_rows(index[key], doc, default_root()) for key in ('services', 'structure') if key in index}}


def wants_room_geometry(question):
    from engine.router.parser import parse
    p = parse(question)
    return p.kind == 'room' and (p.type == 'area' or bool(re.search(r'\barea|\bm2\b|m²|\b(?:largest|biggest|smallest)\b', question, re.I)))


def annotate(res, question, doc, root):
    """Use the exact cited operands in the calculation trace and evidence card."""
    if doc.mode != 'ifc' or any(s.get('step') == 'ifc_accuracy' for s in res.get('trace', [])):
        return res
    from engine.solvers.solve import _step
    ids = {gid for c in res.get('citations', []) for gid in c.get('item_ids', [])}
    cited = [i for i in doc.items if i.item_id in ids]
    notes, flags, unavailable = [], 0, 0
    geometry_wanted = wants_room_geometry(question)
    rooms = [i for i in cited if i.kind == 'room']
    missing = (res.get('measurement_coverage') or {}).get('missing', 0)
    gone = doc.meta.get('excluded_spaces') or []
    if gone and rooms and res.get('answer', {}).get('text_md'):
        from engine.space_dedupe import note as _note
        class _R:  # name/item_id view for the shared sentence
            def __init__(self, g): self.name, self.item_id = g.get('name'), g['item_id']
        res['answer']['text_md'] += _note([(_R(g), g['reason']) for g in gone])
        notes.append(f"{len(gone)} duplicate or MEP/HVAC space(s) were excluded so each footprint counts once.")
    if geometry_wanted and missing:
        unavailable += missing
        notes.append(f'{missing} selected rooms have no usable area; the reported sum is partial.')
    if geometry_wanted and is_item_count(question):
        # An area-bound count must disclose candidates that cannot be tested,
        # including when no known room satisfies the bound (no counted IDs).
        from engine.solvers.filters import room_filter
        from engine.solvers.solve import resolve_storey
        candidates = [i for i in doc.items if i.kind == 'room' and not i.props.get('count_component_of')]
        st = resolve_storey(question, doc.storeys)
        if st:
            candidates = [i for i in candidates if i.storey == st]
        selected = room_filter(question, candidates)
        if selected:
            candidates = selected[1]
        unchecked = sum((i.props.get('space_area') or {}).get('measured_m2') is None for i in candidates)
        if unchecked:
            unavailable += unchecked
            notes.append(f'{unchecked} candidate rooms have no measured footprint; the area-filtered count is incomplete.')
            res['answer']['text_md'] += f' {unchecked} candidate room(s) lack a measured footprint, so this count may be incomplete.'
        if not rooms:
            rooms = candidates  # Show the inspected operands for a verified zero count.
    if geometry_wanted:
        for i in rooms:
            check = i.props.get('space_area') or {}
            measured, stored = check.get('measured_m2'), check.get('stored_net_m2')
            if measured is None:
                unavailable += 1
                notes.append('Room footprint unavailable; stored quantity is unverified.')
                continue
            label = str(i.props.get('long_name') or i.name or 'Room')
            detail = f'{label}: measured footprint {measured:.6g} m²'
            if i.props.get('selected_area_basis'):
                detail += f'; answer uses {i.props["selected_area_basis"]}: {i.q["selected_floor_area_m2"]:.6g} m²'
            if i.props.get('footprint_basis'):
                detail += '; ' + i.props['footprint_basis']
            if stored is not None:
                detail += f'; stored net area {stored:.6g} m²; {check["difference_pct"]:.4g}% difference -> {check["status"]}'
            else:
                detail += '; no stored net area to cross-check'
            notes.append(detail)
            flags += check.get('status') == 'flag'
        if flags:
            res['answer']['text_md'] += f' {flags} stored room area(s) differ from the measured footprint by over 2%; check the model.'
        if unavailable:
            res['answer']['text_md'] += ' Room geometry is unavailable; the stored areas could not be cross-checked.'
    from engine.router.parser import parse
    p = parse(question)
    if p.type == 'count':
        count = res['answer'].get('value')
        if p.kind == 'room':
            notes.append('Count covers only spaces in the selected model and requested floor(s); other discipline files were not combined.')
            if count == 0:
                res['answer']['text_md'] += ' The selected discipline model may omit rooms; check the architectural model.'
        proxies = [i for i in doc.items if i.kind == 'proxy' and i.props.get('proxy_kind') in (p.kinds or [])]
        # Scope recognized proxies to the same requested floor, never add them
        # to the native-class scalar count.
        from engine.solvers.solve import resolve_storey
        storey = resolve_storey(question, doc.storeys)
        if storey:
            proxies = [i for i in proxies if i.storey == storey]
        if proxies:
            n = len(proxies)
            notes.append(f'{n} explicitly labelled generic objects reported separately; excluded from the native-class count.')
            res['answer']['text_md'] += f' Separately, {n} generic object(s) are labelled as {p.kind}; verify their classification.'
            # Evidence for the separate candidates stays separate from counted
            # item_ids, so the displayed count still equals its proof.
            res['proxy_candidates'] = [{'item_id': i.item_id, 'kind': i.props['proxy_kind']} for i in proxies]
            n = max((c['n'] for c in res.get('citations', [])), default=0) + 1
            res.setdefault('citations', []).append({'n': n, 'doc_id': doc.doc_id, 'page': 1,
                'kind': 'element', 'item_ids': [i.item_id for i in proxies], 'bbox_px': None,
                'item_kind': 'proxy', 'quote': 'Separately reported generic objects; excluded from the native-class count.'})
            res['answer']['text_md'] += f' [{n}]'
        if not doc.meta.get('ifc_accuracy_complete'):
            unavailable += 1
            notes.append('Source aggregate relationships unavailable; count hierarchy could not be verified.')
        if any(i.props.get('count_status') not in (None, 'verified') for i in doc.items):
            unavailable += 1
            notes.append('The model has a malformed aggregate hierarchy; affected occurrences were preserved for checking.')
        unknown = [i for i in doc.items if i.kind == 'proxy' and not i.props.get('proxy_kind')]
        if unknown:
            unavailable += 1
            notes.append(f'{len(unknown)} generic objects have no recognized occurrence classification; class counts may be incomplete.')
    if notes:
        res['trace'].extend(_step('calc', detail) for detail in dict.fromkeys(notes))
        res['trace'].append(_step('ifc_accuracy', 'Occurrence hierarchy / footprint cross-check applied.'))
        from engine import reasoning
        card = res.get('reasoning') or reasoning.build(res, question, Path(root)) or {'steps': [], 'confidence': {}}
        if geometry_wanted and rooms:
            checks = [i.props.get('space_area') or {} for i in rooms]
            measured = [c['measured_m2'] for c in checks if c.get('measured_m2') is not None]
            stored = [c['stored_net_m2'] for c in checks if c.get('stored_net_m2') is not None]
            # The old evidence builder reloads the legacy JSON. Supply the
            # measured operands directly so its stored quantities cannot be
            # mistaken for the new geometry-based answer.
            cite = next((c['n'] for c in res.get('citations', []) if c.get('item_kind') != 'proxy'), None)
            measured_text = (f'{len(measured)} room footprints measured from source geometry: {sum(measured):.6g} m².'
                             if measured else 'Room geometry unavailable; stored quantities remain unverified.')
            if stored:
                measured_text += f' Stored net areas available for {len(stored)} rooms: {sum(stored):.6g} m².'
            from engine.ifc_why import area_basis_text   # IFC-WHY: which area was used and why
            basis = area_basis_text(rooms)
            if basis:
                measured_text += ' ' + basis
            card['steps'] = [
                {'kind': 'found', 'title': 'Found', 'text': f'{len(rooms)} cited rooms in the selected scope.', 'cite': cite, 'ok': None},
                {'kind': 'measured', 'title': 'Measured', 'text': measured_text, 'cite': cite, 'ok': None},
                {'kind': 'calculated', 'title': 'Calculated', 'text': (f'Reported {res["answer"]["value"]} {res["answer"].get("unit") or ""} from the matching rooms.'
                    if res['answer'].get('value') is not None else 'Compared the measured footprints of the cited rooms.'), 'cite': None, 'ok': None},
            ]
        check_text = ('Stored net room areas disagree with measured footprints.' if flags else
                      'Geometry or aggregate relationships could not be fully verified.' if unavailable else
                      'Measured footprints and available stored net areas were compared.' if geometry_wanted else
                      'Only model occurrences were counted; related parts were excluded.')
        if geometry_wanted and rooms:
            counts = {s: sum((i.props.get('space_area') or {}).get('status') == s for i in rooms)
                      for s in ('agree', 'flag', 'no stored net area', 'unavailable')}
            counts['unavailable'] += missing
            check_text += f' Within 2%: {counts["agree"]}; flagged: {counts["flag"]}; no stored net area: {counts["no stored net area"]}; geometry unavailable: {counts["unavailable"]}.'
        step = {'kind': 'checked', 'title': 'Cross-check', 'text': check_text, 'cite': None,
                'ok': False if flags or unavailable else True}
        card['steps'] = [s for s in card['steps'] if s.get('kind') != 'checked'][:3] + [step]
        cap = .6 if unavailable else .8 if flags or res.get('proxy_candidates') else 1.
        res['answer']['confidence'] = min(res['answer'].get('confidence', 0), cap)
        card_pct = (card.get('confidence') or {}).get('pct')
        if not isinstance(card_pct, (int, float)) or isinstance(card_pct, bool) or not math.isfinite(card_pct):
            card_pct = 100
        pct = min(card_pct, round(res['answer'].get('confidence', 0)*100), round(cap * 100))
        card['confidence'] = {'label': 'Verified' if pct >= 92 else 'Cross-checked' if pct >= 80 else 'Estimate',
                              'pct': pct, 'reason': check_text,
                              'improve': 'Check the model quantities and object classifications.' if cap < 1 else None}
        res['reasoning'] = card
    return res


def guard(res, question, doc_ids, root):
    """A count route cannot return an area, a fractional count, or component counts."""
    from engine.router.parser import parse
    p = parse(question)
    if not is_item_count(question) or len(doc_ids) != 1:
        return res
    from engine.solvers.data import load_doc, load_sheet_parent
    doc = load_doc(doc_ids[0], Path(root)) or load_sheet_parent(doc_ids[0], Path(root))
    if doc is None or doc.mode != 'ifc':
        return res
    a = res['answer']
    if a.get('abstained'):
        return res
    value = a.get('value')
    valid = res.get('route') == 'index' and a.get('unit') == 'count' and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 and int(value) == value
    if isinstance(value, dict) and a.get('unit') == 'count':
        valid = res.get('route') == 'index' and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in value.values())
    if not valid:
        # Earlier broad analytics sometimes return a room's area for a service
        # count. Retry only code count routes; never coerce that area to int.
        import time
        candidate = None
        if p.kind == 'mep':
            from engine import mep
            scoped = prepare_doc(doc, root, for_count=True)
            candidate = mep.answer(question, scoped, time.perf_counter())
        elif p.kind is not None:
            from engine.solvers.solve import solve
            candidate = solve(question, doc_ids[0], parsed=p, root=root)
        if candidate is not None:
            ca = candidate['answer']
            cv = ca.get('value')
            if ca.get('unit') == 'count' and isinstance(cv, int) and not isinstance(cv, bool) and not ca.get('abstained'):
                candidate['cost'] = res.get('cost', candidate['cost'])
                candidate['trace'] = [*res.get('trace', []), *candidate['trace']]
                candidate['trace'].insert(0, {'step': 'count_guard', 'detail': 'Re-routed incompatible quantity answer to the item count solver.', 'ms': 0, 'model': None, 'cost_usd': 0.})
                return annotate(candidate, question, prepare_doc(doc, root), root)
    if valid:
        if not isinstance(value, dict):
            a['value'] = int(value)
        checked = prepare_doc(doc, root)
        ids = {gid for c in res.get('citations', []) for gid in c.get('item_ids', [])}
        excluded = {i.item_id for i in checked.items if i.props.get('count_component_of')
                    or type_class(i.props.get('ifc_class'))
                    or (i.props.get('ifc_class') == 'IfcBuildingElementProxy' and p.kind != 'proxy')}
        if isinstance(value, (int, float)) and ids & excluded and len(ids) == value:
            from engine.solvers.solve import _evidence, _step, _plural
            remaining = [i for i in checked.items if i.item_id in ids - excluded]
            boxes, cites, scene = _evidence(checked, remaining)
            a['value'] = len(remaining)
            marks = ''.join(f'[{c["n"]}]' for c in cites)
            a['text_md'] = f'**{len(remaining)} {_plural(p.kind or "element", len(remaining))}** match the requested filters. {marks}'
            res['citations'], res['evidence'] = cites, {'boxes': boxes, 'scene': scene}
            res['trace'].append(_step('calc', f'{int(value)} matched occurrences minus {len(ids & excluded)} components/generic objects = {len(remaining)}.'))
            res.pop('reasoning', None)
            # Grouped old quantity rows contain the pre-filter operands.
            res.pop('quantity_rows', None)
        return annotate(res, question, checked, root)
    # Reject dimensional mistakes rather than round/parse a number out of prose.
    from engine.solvers.solve import _step
    a.update(value=None, unit='count', abstained=True, confidence=0.,
             text_md='**Count unavailable.** The selected model did not provide a verified item count for this question.')
    res['trace'].append(_step('count_guard', 'Rejected a count answer with an incompatible unit or non-integer value.'))
    res.pop('reasoning', None)
    return res
