"""View regions shared by scan ingestion, scale reading and count solvers.

annotate_views(pm, words, image=None, dpi=None, frames=None, views=None) is also
an optional hook for PDF owners. Words/frames use rendered page pixels; model
views use pixel boxes too. No PDF access, model calls or source-file writes.
Unresolved boundaries stay unknown instead of assigning elevation symbols to a
nearby floor plan. Regions and original detections remain available for boxing.
"""
from __future__ import annotations

import copy
import re
import unicodedata

from engine.scales import box_area, contains, positive, region_scale, scale_anchors, unknown, valid_box

VIEW_TYPES = ('plan', 'elevation', 'section', 'detail', 'site', 'unknown')
PLAN_KINDS = {'wall', 'door', 'window', 'room', 'toilet', 'sink', 'shower', 'bathtub', 'stairs', 'column'}


def view_type(title):
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(title).casefold()) if not unicodedata.combining(c))
    patterns = {
        'site': r'\b(?:site\s+plan|plot\s+plan|block\s+plan|location\s+plan|asemapiir\w*|lageplan|situationsplan)\b',
        'elevation': r'\b(?:elevations?|julkisivu\w*|fasad\w*|ansicht\w*|aufri\w*)\b',
        'section': r'\b(?:sections?|leikkaus\w*|sektion\w*|schnitt\w*|genomskarning)\b',
        'detail': r'\b(?:details?|detalj\w*|yksityiskohta\w*)\b',
        'plan': r'\b(?:plans?|pohjapiir\w*|pohjakaava\w*|pohja|grundriss\w*|grundplan\w*|kerros|kellarikerros|ullakkokerros|vaningsplan\w*|bottenplan)\b',
    }
    hits = [kind for kind, rx in patterns.items() if re.search(rx, text)]
    if 'site' in hits:
        return 'site'
    # A sheet title like "Plans, sections and elevations" is not a view title.
    if len(hits) > 1:
        return 'unknown'
    return hits[0] if hits else 'unknown'


def title_anchors(words):
    from engine.reader.text import PageText, build_segments
    pt = PageText('', 1, 0, 0, [w for w in words if valid_box(w.get('bbox_px'))])
    out = []
    for seg in build_segments(pt):
        kind = view_type(seg['text'])
        # Notes mentioning a plan are not drawing titles. Keep short labels only.
        if kind != 'unknown' and len(seg['text'].split()) <= 10:
            out.append({'bbox': seg['bbox_px'], 'title': seg['text'], 'view_type': kind})
    return out


def _scale_for(region, anchors, words, pm, dpi, only_view=False):
    from engine.scale_text import from_ratio, ratio_and_sheet, scalebar
    local = [a for a in anchors if contains(region['bbox'], a['bbox']) or a.get('view_id') == region.get('view_id')]
    # Scales printed below a view title can be outside a tightly framed view.
    # Callers supply a frame including the title and scale, never global proximity.
    explicit = region.get('printed_scale')
    if region.get('classification_source') == 'vlm' and pm.get('printed_scale_labels'):
        # The tight label boxes, rather than a model's view-wide scale guess,
        # determine ownership when spatial source labels are available.
        explicit = None
    if explicit:
        local += scale_anchors([{'text': explicit, 'bbox_px': region['bbox']}])
    ratios = {a['ratio'] for a in local}
    old = copy.deepcopy(region.get('scale') or pm.get('source_scale') or pm.get('scale') or {})
    if len(ratios) > 1:
        return unknown('Several printed scales share this view; its scale cannot be assigned safely')
    if not ratios:
        return old if only_view else unknown('No scale could be assigned to this view')
    ratio = next(iter(ratios))
    _, sheet = ratio_and_sheet(words)
    size = pm['image']
    sc = from_ratio(ratio, sheet, size['w'], size['h'], positive(dpi))
    local_words = [w for w in words if contains(region['bbox'], w.get('bbox_px'))]
    bar = scalebar(local_words)
    if bar:
        sc = bar
    if sc is None:
        from statistics import median
        dimensions = []
        for d in pm.get('dimension_evidence', []):
            b, length = d.get('bbox_px'), positive(d.get('meters'))
            if length and contains(region['bbox'], b):
                dimensions.append(length / max(b[2]-b[0], b[3]-b[1]))
        if len(dimensions) >= 2 and (max(dimensions)-min(dimensions))/median(dimensions) <= .25:
            sc = {'m_per_px': median(dimensions), 'method': 'dimension', 'confidence': .7,
                  'evidence': f'{len(dimensions)} local printed dimensions agree in this view'}
    if sc is None:
        if only_view and positive(old.get('m_per_px')):
            old['unverified_printed_ratio'] = ratio
            old['evidence'] = str(old.get('evidence') or 'Existing scale') + f'; printed 1:{ratio:g} could not be calibrated'
            return old
        sc = unknown('Printed ratio needs image DPI or a verified whole-sheet paper size; no physical size inferred')
    sc.update(ratio=ratio, boxes=[a['bbox'] for a in local], evidence=f"Printed scale 1:{ratio:g}. " + sc['evidence'])
    return sc


def annotate_views(pm, words, image=None, dpi=None, frames=None, views=None):
    """Return an independent map with classified regions and item membership.

    Explicit view boxes (from the existing ingest call) take precedence. OCR
    titles otherwise require an actual frame or blank gutter to separate them.
    Repeated titles in a cell remain ambiguous; nearest text alone is not proof
    of the drawing boundary.
    """
    out = copy.deepcopy(pm)
    if out.get('view_analysis', {}).get('version') == 1:
        return out
    existing = out.get('regions') or []
    typed = [r for r in existing if r.get('view_type') in VIEW_TYPES]
    regions = copy.deepcopy(views or typed)
    if not regions:
        titles = title_anchors(words)
        if not titles:
            return out
        from pipeline.scale_regions import _frames, _partitions
        width, height = pm['image']['w'], pm['image']['h']
        boxes = [list(b) for b in (frames or _frames(image, titles, width, height)) if valid_box(b)]
        boxes += _partitions(image, titles, width, height)
        chosen = []
        for title in titles:
            owners = [b for b in boxes if contains(b, title['bbox'])]
            if owners:
                b = min(owners, key=box_area)
                if b not in chosen:
                    chosen.append(b)
        for b in chosen:
            local = [t for t in titles if contains(b, t['bbox']) and not any(contains(sm, t['bbox']) for sm in chosen if box_area(sm) < box_area(b))]
            if not local:
                continue
            kinds = {t['view_type'] for t in local}
            regions.append({'bbox': b, 'title': ' / '.join(dict.fromkeys(t['title'] for t in local)),
                            'view_type': next(iter(kinds)) if len(kinds) == 1 else 'unknown',
                            'classification_source': 'ocr-title', 'title_boxes': [t['bbox'] for t in local]})
    regions = [r for r in regions if valid_box(r.get('bbox')) and r.get('view_type') in VIEW_TYPES]
    if not regions:
        return out
    label_words = [*words, *pm.get('printed_scale_labels', [])]
    anchors = scale_anchors(label_words)
    for n, region in enumerate(regions, 1):
        region.setdefault('view_id', f'view-{n:03d}')
    # A scale printed just below a frame still belongs to that view. Associate
    # only a uniquely nearest boundary within four text heights; remote labels
    # and labels equidistant between views remain unassigned.
    for anchor in anchors:
        if any(contains(r['bbox'], anchor['bbox']) for r in regions):
            continue
        a = anchor['bbox']
        distances = []
        for region in regions:
            b = region['bbox']
            dx = max(b[0]-a[2], a[0]-b[2], 0)
            dy = max(b[1]-a[3], a[1]-b[3], 0)
            distances.append(((dx*dx+dy*dy)**.5, region))
        distances.sort(key=lambda row: row[0])
        distance, nearest = distances[0]
        if distance <= 4*(a[3]-a[1]) and (len(distances) == 1 or distance + .5*(a[3]-a[1]) < distances[1][0]):
            anchor['view_id'] = nearest['view_id']
    for region in regions:
        region['scale'] = _scale_for(region, anchors, words, pm, dpi, only_view=len(regions) == 1)
    out.setdefault('source_scale', copy.deepcopy(pm.get('scale') or {}))
    out['regions'] = regions
    out['view_analysis'] = {'version': 1, 'source': 'view-boxes' if views else 'ocr-title',
                            'note': 'Counts use only fully contained plan detections; unknown and overlapping views need checking.'}
    plan_regions = [r for r in regions if r['view_type'] == 'plan']
    out['scale'] = copy.deepcopy(max(plan_regions, key=lambda r: box_area(r['bbox']))['scale']) if plan_regions else unknown('No floor-plan view was identified')
    for item in out.get('items', []):
        _, owner = region_scale(out, item.get('bbox_px'))
        props = item.setdefault('props', {})
        props['view_id'] = owner['view_id'] if owner else None
        props['view_type'] = owner['view_type'] if owner else 'unknown'
        props['view_title'] = owner.get('title') if owner else None
        if item.get('kind') in PLAN_KINDS:
            props['excluded_from_plan_counts'] = props['view_type'] != 'plan'
    return out


def filter_plan_items(items, pm):
    """Keep legacy maps unchanged. Explicit mixed sheets never count other views."""
    if not pm.get('view_analysis'):
        return items
    return [i for i in items if i.kind not in PLAN_KINDS or not i.props.get('excluded_from_plan_counts', True)]


def count_views(doc, items, kind=None, page=None):
    """Per-view counts, including plans with zero matching detections."""
    rows = []
    for region in doc.meta.get('view_regions', []):
        if region.get('view_type') != 'plan' or (page and region['page'] != page):
            continue
        n = sum(i.page == region['page'] and i.props.get('view_id') == region['view_id'] and (kind is None or i.kind == kind) for i in items)
        rows.append({**region, 'count': n})
    return rows


def count_note(doc, items, kind, page=None):
    rows = count_views(doc, items, kind, page)
    if not rows:
        return ''
    listing = '; '.join(f"{r.get('title') or 'Plan view'} (page {r['page']}): {r['count']}" for r in rows)
    return f' Plan views used: {listing}. Elevations, sections and unassigned detections are excluded.'


def multi_count_note(doc, answers):
    rows = []
    for view in doc.meta.get('view_regions', []):
        if view.get('view_type') != 'plan':
            continue
        parts = []
        for kind, answer in answers:
            cited = {(c['page'], iid) for c in answer['citations'] for iid in c.get('item_ids', [])}
            count = sum(i.kind == kind and i.page == view['page'] and i.props.get('view_id') == view['view_id'] and (i.page, i.item_id) in cited for i in doc.items)
            parts.append(f"{count} {kind if count == 1 else kind + 's'}")
        rows.append(f"{view.get('title') or 'Plan view'} (page {view['page']}): {', '.join(parts)}")
    return (' Plan views used: ' + '; '.join(rows) + '. Elevations, sections and unassigned detections are excluded.') if rows else ''
