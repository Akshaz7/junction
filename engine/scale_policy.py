"""Choose a physical scale from recorded evidence, before solving quantities.

No OCR, models, native-file reads or writes. Producers can supply candidates via
scale.candidates: {method, m_per_px, inputs, formula, note?, independent?}.
Known-size objects require a measured physical width, never a class-size guess.
Agreement is corroboration, not measured accuracy or a physical error bound.
"""
from __future__ import annotations

import copy

from engine.scale_proof import enrich, positive

RANK = {'ifc': 0, 'ifc-units': 0, 'dxf-units': 0, 'dxf_units_fit': 0,
        'dxf-units-fit': 0, 'dxf_render': 0, 'dimension': 1, 'dimensions': 1, 'ratio-dpi': 1,
        'ratio-sheet': 2, 'scalebar': 3, 'scale-bar': 3,
        'known-size': 4, 'door-prior': 5}
LABEL = {'ifc': 'IFC model projection in metres', 'dxf_units_fit': 'Declared CAD units and page registration',
         'dxf-units': 'Declared CAD units and page registration', 'dimension': 'Printed dimension matched to its line',
         'ratio-dpi': 'Printed ratio and recorded render resolution', 'ratio-sheet': 'Printed ratio and full paper size',
         'scalebar': 'Printed scale bar', 'known-size': 'Measured known-size object', 'door-prior': 'Assumed door-width prior'}


def difference(a, b):
    return 100 * abs(a - b) / max(abs(a), abs(b))


def family(c):
    m = c.get('method', '')
    if m.startswith('ratio'): return 'printed-ratio'
    if m in ('dimension', 'dimensions'): return 'dimension'
    if m in ('scalebar', 'scale-bar'): return 'scale-bar'
    return m


def independent(a, b):
    return (family(a) != family(b) and a.get('independent') is not False
            and b.get('independent') is not False and not a.get('stored_only') and not b.get('stored_only'))


def rank(c):
    return (.5 if RANK[c['method']] == 0 else 6) if c.get('stored_only') else RANK[c['method']]


def select(candidates):
    """Rank available evidence; independent agreement breaks quality ties.

    Native units outrank raster inference. Conflicting equally supported top
    candidates have no global winner (often multiple detail scales on a sheet).
    Never average competing scales or treat a door prior as independent proof.
    """
    cs = [copy.deepcopy(c) for c in candidates if isinstance(c, dict)
          and positive(c.get('m_per_px')) and c.get('inputs') and c.get('method') in RANK]
    for c in cs:
        c['m_per_px'] = positive(c['m_per_px'])
        c['support'] = len({family(b) for b in cs if independent(c, b)
                            and difference(c['m_per_px'], positive(b['m_per_px'])) <= 1})
    if not cs:
        return None, {'id': 'unknown', 'label': 'No supported physical scale',
                      'why_chosen': 'No candidate with a positive scale and recorded operands is available.', 'alternatives': []}
    cs.sort(key=lambda c: (rank(c), -c['support'], c['method'], c['m_per_px']))
    winner = cs[0]
    tied = [c for c in cs if rank(c) == rank(winner) and c['support'] == winner['support']]
    ambiguous = any(difference(c['m_per_px'], winner['m_per_px']) > 5 for c in tied)
    comparisons = [{'id': c['method'], 'value': c['m_per_px'], 'unit': 'm/px',
                    'diff_pct': difference(c['m_per_px'], winner['m_per_px']),
                    'independent': independent(winner, c),
                    'rejected_because': ('Conflicting equally supported scales; a region association is required.' if ambiguous
                                        else 'Same evidence/value; duplicate reading.' if c['method'] == winner['method'] and c['m_per_px'] == winner['m_per_px']
                                        else 'Lower physical-evidence rank.' if rank(c) > rank(winner)
                                        else 'Less independent agreement within 1%.' if c['support'] < winner['support']
                                        else 'Equivalent rank; deterministic selection, no averaging.')}
                   for c in cs[1:]]
    conflicts = [c for c in comparisons if c['diff_pct'] > 5]
    method = {'id': 'ambiguous' if ambiguous else winner['method'],
              'label': 'Conflicting page scales' if ambiguous else LABEL.get(winner['method'], winner['method']),
              'why_chosen': ('No global choice: equally ranked readings disagree by more than 5%.' if ambiguous else
                             f"Highest available evidence rank ({rank(winner)}); {winner['support']} independent method families agree within 1%."
                             + (' Original derivation is unavailable; retained from the source artifact.' if winner.get('stored_only') else '')),
              'alternatives': comparisons, 'disagreement': bool(conflicts or ambiguous),
              'agreement_definition': '100 × |a − b| / max(|a|, |b|); agreement ≤1%, disagreement >5%; not an accuracy guarantee'}
    return (None if ambiguous else winner), method


def _choose(pm, folder=None, effective_scale=None):
    """Return the chosen scale plus every evidenced candidate; do not mutate pm."""
    sc = enrich(pm, folder, effective_scale=effective_scale, save_crops=False)
    sc['m_per_px'] = positive(sc.get('m_per_px'))
    # enrich reports cross-method spread. Older margin consumers treat the
    # legacy spread_pct field as an error budget; never feed agreement into it.
    observed_spread = sc.pop('spread_pct', None)
    if observed_spread is not None: sc['method_spread_pct'] = observed_spread
    candidates = list(sc.get('available_candidates') or []) + known_objects(pm) + native_registration(pm, sc)
    old_method, old_value = sc.get('method'), positive(sc.get('m_per_px'))
    # Legacy native-unit artifacts remain native, with missing provenance stated.
    # A bare stored raster estimate cannot outrank a newly evidenced measurement.
    if old_value and old_method in RANK and not any(c['method'] == old_method and difference(c['m_per_px'], old_value) < 1e-7 for c in candidates):
        candidates.append({'method': old_method, 'm_per_px': old_value, 'stored_only': True,
                           'inputs': [{'name': 'stored page scale', 'value': old_value, 'unit': 'm/px',
                                       'source': {'doc_id': pm.get('doc_id'), 'page': pm.get('page', 1),
                                                  'file': f"planmap-{pm.get('page', 1)}.json", 'pointer': '/scale/m_per_px'}}],
                           'formula': 'recorded page scale; original operands unavailable', 'independent': False})
    selected, method = select(candidates)
    sc['selection'], sc['candidates'] = method, candidates
    if selected:
        sc.update(m_per_px=selected['m_per_px'], method=selected['method'],
                  derivation={k: v for k, v in selected.items() if k in ('formula', 'inputs', 'note')},
                  selection_rule=method['why_chosen'])
        # Retain confidence only when the same evidence/scale was used before.
        if selected['method'] != old_method or not old_value or difference(selected['m_per_px'], old_value) > 1e-7:
            for key in ('relative_error', 'uncertainty_m_per_px', 'fit_residual_px', 'scale_bar_px', 'door_width_relative_error'):
                sc.pop(key, None)
            sc['confidence'] = .3 if selected['method'] == 'door-prior' else .8
    elif method['id'] == 'ambiguous':
        sc.update(m_per_px=None, method='none', confidence=0, selection_rule=method['why_chosen'])
    # Refresh the proof after selection so no consumer sees an old scale result
    # next to a new method. Cross-method spread remains sensitivity only.
    sc = enrich(pm, folder, effective_scale=sc, save_crops=False)
    spread = sc.pop('spread_pct', None)
    if spread is not None: sc['method_spread_pct'] = spread
    return sc


def choose(pm, folder=None, effective_scale=None):
    """Odd/missing producer metadata cannot break a structured-data answer."""
    try:
        return _choose(pm, folder, effective_scale)
    except (TypeError, ValueError, KeyError, AttributeError, ArithmeticError, OSError) as exc:
        original = effective_scale if effective_scale is not None else (pm.get('scale') if isinstance(pm, dict) else {})
        sc = copy.deepcopy(original) if isinstance(original, dict) else {}
        sc['m_per_px'] = positive(sc.get('m_per_px'))
        sc['selection'] = {'id': 'unavailable', 'label': 'Scale evidence unavailable',
                           'why_chosen': f'Candidate provenance could not be read ({type(exc).__name__}); no new conversion was applied.', 'alternatives': []}
        sc['candidates'] = []
        return sc


def known_objects(pm):
    """Producer hook: an actual measured width linked to image endpoints.

    props.known_width_m and props.known_width_line_px must be provided together.
    A generic object/door class does not supply a physical measurement.
    """
    import math
    from engine.scale_proof import candidate, operand
    out = []
    for i, it in enumerate(pm.get('items') or []):
        props = it.get('props') or {}
        width, line = positive(props.get('known_width_m')), props.get('known_width_line_px')
        if not width or not isinstance(line, list) or len(line) != 2: continue
        try:
            px = positive(math.dist(*line))
        except (ValueError, TypeError):
            continue
        if not px: continue
        src = {'file': f"planmap-{pm.get('page', 1)}.json", 'pointer': f'/items/{i}/props',
               'item_id': it.get('item_id'), 'bbox': it.get('bbox_px'), 'endpoints_px': line}
        out.append(candidate('known-size', width / px, 'scale = recorded physical width / matched pixel span',
                             [operand('recorded physical width', width, 'm', src),
                              operand('metres per metre', 1, 'm/m', {'definition': 'Recorded physical width is already in metres'}),
                              operand('matched pixel span', px, 'px', src)],
                             'Physical width supplied by the source producer; object class averages are not measurements.'))
    return out


def native_registration(pm, scale):
    """Recompute a CAD pixel mapping when both recorded operands exist."""
    from engine.scale_proof import candidate, operand
    native = scale.get('native_units') or {}
    factor = positive(native.get('m_per_unit'))
    signed = (pm.get('registration') or {}).get('a')
    a = positive(abs(signed)) if isinstance(signed, (int, float)) and not isinstance(signed, bool) else None
    if factor and a and native.get('method') == 'dxf-units':
        return [candidate('dxf-units', factor / a, 'scale = metres per drawing unit / abs(registered pixels per drawing unit)',
                          list(native.get('inputs') or []) + [
                              operand('metres per drawing unit', factor, 'm/native unit', {'file': f"planmap-{pm.get('page', 1)}.json", 'pointer': '/scale/native_units/m_per_unit'}),
                              operand('registered signed pixels per drawing unit', signed, 'px/native unit', {'file': f"planmap-{pm.get('page', 1)}.json", 'pointer': '/registration/a'})],
                          'Uses declared insertion units and the recorded registration; no unitless-to-metre default.', independent=False)]
    return []
