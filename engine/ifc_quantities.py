"""F-IFCQTY: filtered counts, reinforcement, room skirting and MEP families.

Narrow code routes before the broad legacy handlers. The sidecar is written at
IFC ingestion; old indexes can read the source IFC without changing artifacts.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import threading
import time

from engine.solvers.data import Doc, Item
from engine.solvers.filters import fold, room_filter, storey_requested
from engine.solvers.solve import _answer_obj, _evidence, _step, resolve_storey

_CACHE = OrderedDict()
_LOCK = threading.RLock()
BASEBOARD = re.compile(r'\b(?:base ?boards?|skirting(?: boards?)?|wall bases?|floor mouldings?|floor moldings?)\b', re.I)
REBAR = re.compile(r'\b(?:rebar|reinforc(?:ing|ement) (?:bars?|meshes|mesh)|tendons?)\b', re.I)
COUNT = re.compile(r'\b(?:how many|number of|count)\b', re.I)
LENGTH = re.compile(r'\b(?:length|long|linear|running|metres?|meters?|feet)\b', re.I)
MASS = re.compile(r'\b(?:weight|weigh|mass|kilograms?|kg|tonnes?)\b', re.I)
NUMBER = r'(\d+(?:[.,]\d+)?)'
LUNIT = r'(mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|m|met(?:er|re)s?|inches|inch|in|feet|foot|ft)'
FACTORS = {'mm': .001, 'cm': .01, 'm': 1., 'in': .0254, 'ft': .3048}


def _unit(u):
    u = u.lower()
    return 'mm' if u.startswith('milli') else 'cm' if u.startswith('centi') else 'm' if u.startswith('met') else 'in' if u.startswith('in') else 'ft' if u in ('feet', 'foot', 'ft') else u


def _artifacts():
    from engine.mep import _artifacts_dir
    return Path(os.environ.get('ARTIFACTS_DIR') or _artifacts_dir())


def _source(doc_id, root):
    from engine.mep import ROOT
    try:
        meta = json.loads((root / doc_id / 'doc.json').read_text())
        p = (meta.get('files') or {}).get('ifc')
        if not p:
            return None
        candidates = [Path(p), root / doc_id / p, ROOT / p,
                      ROOT / 'data/junction-dataset-preview' / p,
                      ROOT / 'data/full/junction-dataset' / p]
        return next((x.resolve() for x in candidates if x.is_file()), None)
    except (OSError, ValueError, TypeError):
        return None


def _snapshot_key(path):
    st = path.stat()
    return str(path.resolve()), st.st_mtime_ns, st.st_size


def _fallback(doc):
    rows = []
    from pipeline.ifc_quantities import REINFORCEMENT
    for it in doc.items:
        cls = it.props.get('ifc_class')
        if not cls:
            continue
        kind = REINFORCEMENT.get(cls, it.kind)
        q = dict(it.q)
        if 'thickness_m' not in q:
            key = 'depth_m' if kind == 'slab' else 'width_m'
            if key in q:
                q['thickness_m'] = q[key]
        rows.append({'item_id':it.item_id, 'ifc_class':cls, 'classes':[cls], 'kind':kind,
                     'name':it.name, 'type_name':it.type_name, 'long_name':it.props.get('long_name'),
                     'predefined_type':it.props.get('predefined_type'), 'quantities':q,
                     'sources':{k:'IFC element index' for k in q}, 'is_external':it.props.get('is_external'),
                     'storey':it.storey, 'systems':it.props.get('systems') or [],
                     'reference':it.props.get('reference'), 'bar_role':it.props.get('bar_role'),
                     'boundary_doors':it.props.get('boundary_doors') or {},
                     'boundaries_recorded':it.props.get('boundaries_recorded', False), 'groups':[]})
    return {'rows':rows, 'indexed_classes':['IfcWall','IfcSlab','IfcSpace','IfcDoor'], 'errors':[], 'source_available':False, 'fallback':True}


def load_index(doc):
    """Bounded, file-version keyed JSON snapshots. Never retain a parsed IFC file."""
    from pipeline.ifc_quantities import VERSION, build
    root = _artifacts()
    sidecar = root / doc.doc_id / 'ifc-quantities.json'
    source = _source(doc.doc_id, root)
    path = sidecar if sidecar.is_file() else source
    if path is None:
        return _fallback(doc)
    try:
        key = _snapshot_key(path)
        with _LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
            if path == sidecar:
                idx = json.loads(sidecar.read_text())
                if idx.get('version') != VERSION:
                    return _fallback(doc)
            else:
                import ifcopenshell
                idx = build(ifcopenshell.open(str(source)))
            idx['source_available'] = source is not None
            _CACHE[key] = idx
            while len(_CACHE) > 2:
                _CACHE.popitem(last=False)
            return idx
    except (OSError, ValueError, RuntimeError, ImportError, TypeError):
        return _fallback(doc)


def _items(doc, rows):
    by_id = {i.item_id:i for i in doc.items}
    return [replace(by_id[r['item_id']], kind=r['kind'], q={**by_id[r['item_id']].q, **r['quantities']})
            if r['item_id'] in by_id else Item(r['item_id'], r['kind'], name=r.get('name'),
                type_name=r.get('type_name'), storey=r.get('storey'), q=r['quantities'], source='ifc',
                props={'ifc_class':r['ifc_class']}) for r in rows]


def _result(question, doc, rows, value, unit, formula, filters, t0, *, notes=(), detail_rows=None, confidence=1.):
    items = _items(doc, rows)
    boxes, cites, scene = _evidence(doc, items)
    marks = ''.join(f'[{c["n"]}]' for c in cites)
    label = ('reinforcing bars' if REBAR.search(question) else 'baseboard' if BASEBOARD.search(question)
             else 'slabs' if re.search(r'\bslabs?\b', question, re.I) else 'walls' if re.search(r'\bwalls?\b', question, re.I)
             else 'service elements')
    if label == 'service elements':
        from engine.mep import KIND_WORDS
        kinds = list(dict.fromkeys(r['kind'] for r in rows))
        if len(kinds) == 1 and kinds[0] in KIND_WORDS:
            label = KIND_WORDS[kinds[0]][1]
        elif re.search(r'\bflow terminals?\b', question, re.I):
            label = 'service outlets and fixtures'
        elif re.search(r'\bflow controllers?\b', question, re.I):
            label = 'service controls'
        elif kinds:
            label = ' and '.join(KIND_WORDS.get(k,(k,k.replace('_',' ')+'s'))[1] for k in kinds)
    if REBAR.search(question) and rows:
        label = {'reinforcing_mesh':'reinforcing meshes','tendon':'tendons'}.get(rows[0]['kind'], label)
    if value is None:
        headline = '**Quantity unavailable.**'
    elif unit == 'count':
        headline = f'**{value:,} {label}.** {marks}'
    else:
        headline = f'**{value:,.2f} {unit} of {label}.** {marks}'
    lines = [headline]
    if filters:
        lines.append('- Filter: ' + '; '.join(filters) + '.')
    if BASEBOARD.search(question) and value is not None:
        lines.append('- Rule: room floor perimeter minus widths of doors bounding that room.')
    if detail_rows and (re.search(r'\b(?:per|by|each|every|breakdown)\b', question, re.I) or BASEBOARD.search(question)):
        shown = detail_rows[:max(0, 3 - len(lines) + 1)]
        lines.extend('- ' + d['label'] + ': ' + f'{d["value"]:,.2f} {unit}.' for d in shown)
    for note in list(notes)[:max(0, 5-len(lines))]:
        lines.append('- ' + note)
    trace = [_step('route','IFC quantities -> code, no model'),
             _step('filter','; '.join(filters) or 'all matching model elements'), _step('calc',formula)]
    res = _answer_obj(question, [doc.doc_id], '\n\n'.join([lines[0], '\n'.join(lines[1:])]).rstrip(),
                      value, unit, confidence, value is None, boxes,cites,scene,trace,'index',t0)
    res['quantity_rows'] = detail_rows or []
    # Keep calculation notes in the existing trace entry shape and build the
    # evidence card from the same operands, including on unavailable answers.
    steps = [{'kind':'found','title':'Found','text':f'{len(rows)} matching model elements.', 'cite':cites[0]['n'] if cites else None,'ok':None},
             {'kind':'measured','title':'Filtered','text':'; '.join(filters) or 'All matching elements in the model.','cite':None,'ok':None},
             {'kind':'calculated','title':'Calculated','text':formula,'cite':None,'ok':None}]
    if notes:
        steps.append({'kind':'checked','title':'Check before ordering','text':' '.join(notes),'cite':None,'ok':False if value is None else None})
    pct = round(confidence*100) if value is not None else 0
    res['reasoning'] = {'steps':steps[:4], 'confidence':{'label':'Verified' if pct >= 92 else 'Cross-checked' if pct >= 80 else 'Estimate',
        'pct':pct,'reason':'Calculated from the cited model data.' if value is not None else 'The source does not provide complete evidence.',
        'improve':None if confidence >= .92 and value is not None else 'Check the stated missing information in the source model.'}}
    return res


def _outside_type_label(question):
    # A type can itself be named "Floor 2", "Basement" or a storey name.
    # Only the question outside its explicit type/size/role label sets scope.
    return re.sub(r'\b(?:predefined type|type|size|role)\s+(?:"[^"]*"|\'[^\']*\')', '', question, flags=re.I)


def _scoped(question, doc, rows):
    question = _outside_type_label(question)
    st = resolve_storey(question, doc.storeys)
    explicit = re.search(r'\b(?:storey|story|floor|level)\s+[\'\"]([^\'\"]+)', question, re.I)
    if explicit:
        st = next((s['name'] for s in doc.storeys if fold(s['name']) == fold(explicit[1])), None)
    if st is None and (storey_requested(question) or explicit):
        return [], [], 'The requested floor was not found in the model.'
    return ([r for r in rows if r.get('storey') == st] if st else rows), ([f'floor {st}'] if st else []), None


def _thickness(question):
    m = re.search(NUMBER + r'\s*' + LUNIT + r'\s*(?:[- ]?thick|thickness)', question, re.I)
    if not m:
        m = re.search(r'\bthickness(?:\s+of)?\s*(?:=|is)?\s*' + NUMBER + r'\s*' + LUNIT, question, re.I)
    return (float(m[1].replace(',','.')) * FACTORS[_unit(m[2])], f'thickness {m[1]} {m[2]}') if m else None


def _type_filter(question, rows, scope_names=()):
    """Explicit type / size / role labels, including unquoted exporter codes."""
    quoted = [a or b for a,b in re.findall(r'"([^"]+)"|\'([^\']+)\'', question)]
    scope = re.findall(r'\b(?:floor|storey|story|level)\s+[\'\"]([^\'\"]+)', question, re.I)
    quoted = [x for x in quoted if x not in scope and fold(x) not in {fold(s) for s in scope_names}]
    explicit = re.search(r'\b(?:of\s+)?(?:type|size|role|predefined type)\s+(?:is\s+|=\s*)?[\'\"]?([^?\n,;]+)', question, re.I)
    target = quoted[0] if quoted else re.split(r'\s+(?:on|in|with|and|that|are|is)\b', explicit[1], flags=re.I)[0].strip(' \t\'\".') if explicit else None
    if target is None:
        for candidate in re.findall(r'\(([^()]+)\)', question):
            if any(re.search(rf'(?<!\w){re.escape(fold(candidate))}(?!\w)', fold(r.get(k)))
                   for r in rows for k in ('type_name','reference')):
                target = candidate
                break
    if target and fold(target) not in ('the model', 'this model', 'building'):
        field = ('bar_role' if explicit and 'role' in explicit[0].lower() else
                 'predefined_type' if explicit and 'predefined' in explicit[0].lower() else None)
        def match(r):
            vals = [r.get(field)] if field else [r.get(k) for k in ('type_name','reference','predefined_type','name','bar_role')]
            return any(v and re.search(rf'(?<!\w){re.escape(fold(target))}(?!\w)',fold(v)) for v in vals)
        return [r for r in rows if match(r)], f'{"bar role" if field == "bar_role" else "predefined type" if field else "type/size"} {target}'
    # Unquoted codes embedded in the question are matched only against actual
    # type labels, never against room or document names.
    matches = [str(r.get(k)) for r in rows for k in ('type_name','reference','predefined_type')
               if r.get(k) and len(fold(r[k])) >= 3 and re.search(rf'(?<!\w){re.escape(fold(r[k]))}(?!\w)',fold(question))]
    if matches:
        target = max(matches,key=len)
        return [r for r in rows if any(fold(r.get(k)) == fold(target) for k in ('type_name','reference','predefined_type'))], f'type {target}'
    codes = [x for x in re.findall(r'\b[\w-]+\b', question) if len(x) >= 3
             and re.search(r'[A-Za-z]',x) and re.search(r'[_\d]',x)]
    for target in sorted(codes,key=len,reverse=True):
        hit = [r for r in rows if any(re.search(rf'(?<!\w){re.escape(fold(target))}(?!\w)',fold(r.get(k)))
                                     for k in ('type_name','reference','predefined_type'))]
        if hit:
            return hit, f'type {target}'
    return rows, None


def filtered_counts(question, doc, t0):
    if not COUNT.search(question) or BASEBOARD.search(question) or re.search(r'\bhow many (?:linear |running )?(?:metres?|meters?|feet)\b',question,re.I):
        return None
    m = re.search(r'\b(walls?|slabs?)\b',question,re.I)
    if not m:
        return None
    condition_question = _outside_type_label(question)
    thickness = _thickness(condition_question)
    explicit = bool(re.search(r'\b(?:type|external|exterior|internal|interior|predefined)\b|[()\'\"]|\b[A-Za-z_]\w*\d\w*',question,re.I))
    if not thickness and not explicit:
        return None
    kind = m[1].lower().rstrip('s')
    idx = load_index(doc)
    rows = [r for r in idx['rows'] if r['kind'] == kind]
    rows, filters, error = _scoped(question,doc,rows)
    if error:
        return _result(question,doc,[],None,'count','No count computed.',[],t0,notes=[error],confidence=0.)
    missing = 0
    notes = []
    rows, label = _type_filter(question,rows,[doc.title, *[s['name'] for s in doc.storeys]])
    if label:
        filters.append(label)
    if thickness:
        val, label = thickness
        missing = sum(r['quantities'].get('thickness_m') is None for r in rows)
        if missing:
            notes.append(f'{missing} elements have no recorded thickness and are excluded; this is a count of recorded matches.')
        rows = [r for r in rows if r['quantities'].get('thickness_m') is not None and abs(r['quantities']['thickness_m'] - val) <= .0005]
        filters.append(label)
    ext = re.search(r'\b(external|exterior|internal|interior)\b',condition_question,re.I)
    if ext:
        missing = sum(r.get('is_external') is None for r in rows)
        if missing:
            return _result(question,doc,rows,None,'count','Exterior filter cannot be completed.',filters,t0,
                           notes=[f'{missing} elements do not record whether they are external.'],confidence=0.)
        want = ext[1].lower() in ('external','exterior')
        rows = [r for r in rows if r.get('is_external') is want]
        filters.append(ext[1].lower())
    if not filters:
        return None
    sources = sorted({r['sources'].get('thickness_m','IFC element properties') for r in rows}) if thickness else ['IFC class, type and property assignments']
    return _result(question,doc,rows,len(rows),'count',f'Count matching {kind} elements after filters = {len(rows)}. Sources: ' + '; '.join(sources) + '. ' + ' '.join(notes),filters,t0,
                   notes=notes,confidence=.85 if notes else 1.)


def reinforcement(question, doc, t0):
    if not REBAR.search(question) or not (COUNT.search(question) or LENGTH.search(question) or MASS.search(question)):
        return None
    if re.search(r'\bslabs?\b', question, re.I):
        return None  # a slab reinforcement schedule needs hosted bars / a schedule, not all bars
    cls = 'IfcReinforcingMesh' if re.search(r'\bmesh(?:es)?\b',question,re.I) else 'IfcTendon' if re.search(r'\btendons?\b',question,re.I) else 'IfcReinforcingBar'
    idx = load_index(doc)
    rows = [r for r in idx['rows'] if cls in r.get('classes',[]) or r['ifc_class'] == cls]
    if cls not in idx['indexed_classes'] and not rows:
        return _result(question,doc,[],None,None,'No quantity computed: kind not indexed.',[],t0,
                       notes=['This kind of reinforcement is not indexed, and its source IFC is unavailable.'],confidence=0.)
    rows, filters, error = _scoped(question,doc,rows)
    if error:
        return _result(question,doc,rows,None,None,'No quantity computed.',filters,t0,notes=[error],confidence=0.)
    rows,label = _type_filter(question,rows)
    if label:
        filters.append(label)
    diameter = re.search(r'(?:diameter|[ØøΦ⌀])\s*(?:of\s+|=\s*)?' + NUMBER + r'\s*' + LUNIT, question,re.I)
    if not diameter:
        diameter = re.search(NUMBER + r'\s*' + LUNIT + r'\s+(?:diameter\s+)?(?:bars?|rebar|reinforcing bars?)',question,re.I)
    if diameter:
        val = float(diameter[1].replace(',','.')) * FACTORS[_unit(diameter[2])]
        def diameters(r):
            return [r['quantities'][k] for k in ('diameter_m','longitudinal_diameter_m','transverse_diameter_m') if r['quantities'].get(k) is not None]
        missing = sum(not diameters(r) for r in rows)
        if missing:
            return _result(question,doc,rows,None,None,'Diameter filter incomplete.',filters,t0,notes=[f'{missing} elements have no recorded diameter.'],confidence=0.)
        rows = [r for r in rows if any(abs(d-val)<=1e-6 for d in diameters(r))]
        filters.append(f'diameter {diameter[1]} {diameter[2]}')
    key, unit = ('mass_kg','kg') if MASS.search(question) else ('length_m','m') if LENGTH.search(question) else (None,'count')
    missing = sum(r['quantities'].get(key) is None for r in rows) if key else 0
    if missing or idx.get('errors'):
        note = f'{missing} elements lack the requested measurement.' if missing else 'Some IFC elements could not be indexed.'
        if key == 'mass_kg':
            note += ' Weight needs a recorded mass, or a recorded density and volume/section; no steel density is assumed.'
        return _result(question,doc,rows,None,unit,'No complete total can be computed.',filters,t0,notes=[note],confidence=0.)
    value = round(sum(r['quantities'][key] for r in rows),4) if key else len(rows)
    formula = f'Sum {key} for {len(rows)} reinforcing elements = {value} {unit}.' if key else f'Count reinforcement after filters = {value}.'
    if key:
        formula += ' Sources: ' + '; '.join(sorted({r['sources'].get(key,'not recorded') for r in rows})) + '.'
    details=[]
    if re.search(r'\bby (?:diameter|role|type)\b',question,re.I):
        field = 'bar_role' if re.search(r'\bby role\b',question,re.I) else 'type_name' if re.search(r'\bby type\b',question,re.I) else 'diameter_m'
        groups=defaultdict(list)
        for r in rows:
            v=r['quantities'].get(field) if field == 'diameter_m' else r.get(field)
            label=f'{v*1000:g} mm' if field == 'diameter_m' and v is not None else str(v or 'Not recorded')
            groups[label].append(r)
        details=[{'label':label,'value':sum(r['quantities'][key] for r in rs) if key else len(rs),'item_ids':[r['item_id'] for r in rs]} for label,rs in sorted(groups.items())]
    return _result(question,doc,rows,value,unit,formula,filters,t0,detail_rows=details)


def room_baseboard(question, doc, t0):
    if not BASEBOARD.search(question):
        return None
    idx = load_index(doc)
    all_rooms = [r for r in idx['rows'] if r['kind']=='room']
    rows, filters, error = _scoped(question,doc,all_rooms)
    # A room identifier takes precedence over a shared room type in parentheses.
    explicit = re.search(r'\broom\s+[\'\"]?([\w.-]+)',question,re.I)
    if explicit and explicit[1].lower() not in ('on','in','of','for','per','floor','type','names'):
        target=explicit[1].strip('?.')
        rows=[r for r in rows if fold(r.get('name')) == fold(target) or fold(r.get('long_name')) == fold(target)]
        filters.append(f'room {target}')
        if not rows:
            error='The requested room was not found; no other rooms were substituted.'
    else:
        selected=room_filter(question,_items(doc,rows))
        if selected:
            label,items=selected
            ids={i.item_id for i in items}
            rows=[r for r in rows if r['item_id'] in ids]
            filters.append(f'rooms matching {label}')
    # Only explicit IFC assignments / aggregates can identify an apartment.
    # A room's identifier prefix is not proof of which unit it belongs to.
    unit=re.search(r'\b(?:unit|apartment|dwelling)\s+[\'\"]?([\w.-]+)',question,re.I)
    if unit:
        target=fold(unit[1].strip('?.'))
        rows=[r for r in rows if any(fold(x)==target or fold(x) in (f'unit {target}',f'apartment {target}',f'dwelling {target}') for x in r.get('groups',[]))]
        filters.append('unit '+unit[1])
        if not rows:
            error='The model does not assign these rooms to the requested unit. Room identifier prefixes alone are not verified unit assignments.'
    if error or not rows:
        return _result(question,doc,rows,None,'m','No room perimeter computed.',filters,t0,
                       notes=[error or 'No matching room footprints are indexed.'],confidence=0.)
    source=_source(doc.doc_id,_artifacts())
    need=[r for r in rows if not str(r['sources'].get('perimeter_m','')).startswith('union of IfcSpace')]
    if need and source:
        import ifcopenshell
        from pipeline.ifc_quantities import footprint_perimeter
        f=ifcopenshell.open(str(source))
        rows=[{**r,'quantities':dict(r['quantities']),'sources':dict(r['sources'])} for r in rows]
        for r in rows:
            if not str(r['sources'].get('perimeter_m','')).startswith('union of IfcSpace'):
                perimeter,src=footprint_perimeter(f.by_guid(r['item_id']))
                if perimeter is not None:
                    r['quantities']['perimeter_m']=perimeter
                    r['sources']['perimeter_m']=src
    details,missing=[],[]
    for r in rows:
        per=r['quantities'].get('perimeter_m')
        doors=r.get('boundary_doors',{})
        if per is None or not r.get('boundaries_recorded') or any(v is None for v in doors.values()):
            missing.append(r)
            continue
        widths=sum(doors.values())
        if widths > per:
            missing.append(r)
            continue
        details.append({'label':' '.join(str(r.get(k) or '') for k in ('name','long_name')).strip() or 'Room',
                        'item_id':r['item_id'],'value':per-widths,'perimeter_m':per,'door_width_m':widths,
                        'door_item_ids':list(doors),'perimeter_source':r['sources']['perimeter_m']})
    if missing:
        return _result(question,doc,rows,None,'m','Complete floor perimeters and door-boundary widths are required.',filters,t0,
                       notes=[f'{len(missing)} rooms lack a footprint, space boundaries, or a boundary door width.'],confidence=0.,detail_rows=details)
    total=round(sum(d['value'] for d in details),4)
    per=sum(d['perimeter_m'] for d in details)
    op=sum(d['door_width_m'] for d in details)
    formula=f'Room floor perimeters {per:.4f} m minus deduplicated boundary door widths {op:.4f} m = {total:.4f} m.'
    door_ids={i for d in details for i in d['door_item_ids']}
    proof=rows+[r for r in idx['rows'] if r['item_id'] in door_ids]
    return _result(question,doc,proof,total,'m',formula,filters,t0,detail_rows=details,confidence=.90,
                   notes=['This is a measured baseboard allowance; actual finish specifications and other openings are not recorded.'])


def mep_families(question,doc,t0):
    """MEP class unions and family filters; never collapse terminals into air only."""
    if not COUNT.search(question) and not LENGTH.search(question):
        return None
    q=question.lower()
    if re.search(r'\b(?:where|sizes?|cost|waste|power|voltage|flow rate|pressure|room|area)\b',q):
        return None
    # The explicit broad IFC terms request all descendants, across service trades.
    classes=[]
    if re.search(r'\bflow terminals?\b',q):
        classes=['IfcFlowTerminal']
    elif re.search(r'\bflow controllers?\b',q):
        classes=['IfcFlowController']
    elif re.search(r'\bflow fittings?\b',q):
        classes=['IfcFlowFitting']
    subjects=[]
    for kind,rx in [('pipe_fitting',r'\bpipe fittings?\b'),('duct_fitting',r'\bduct fittings?\b'),
                    ('pipe',r'\bpipes?\b|\bpiping\b'),('duct',r'\bducts?\b|\bductwork\b'),
                    ('valve',r'\bvalves?\b'),('damper',r'\bdampers?\b'),('air_terminal',r'\bair terminals?\b|\bdiffusers?\b|\bgrilles?\b')]:
        if re.search(rx,q):
            subjects.append(kind)
    if 'pipe_fitting' in subjects:
        subjects=[k for k in subjects if k!='pipe']
    if 'duct_fitting' in subjects:
        subjects=[k for k in subjects if k!='duct']
    if not classes and not subjects:
        return None
    idx=load_index(doc)
    rows=([r for r in idx['rows'] if any(c in r.get('classes',[]) for c in classes)]
          if classes else [r for r in idx['rows'] if r['kind'] in subjects])
    if not rows and not idx['source_available'] and 'IfcDistributionElement' not in idx['indexed_classes']:
        return None  # the older MEP sidecar may still hold evidence
    rows,filters,error=_scoped(question,doc,rows)
    if error:
        return _result(question,doc,rows,None,None,'No quantity computed.',filters,t0,notes=[error],confidence=0.)
    # All family adjectives are retained. Parenthetical enumeration of *all*
    # shapes means a union rather than an accidental rectangular-only filter.
    if not (re.search(r'\ball\b',q) and re.search(r'rectangular.*round.*flex',q)):
        for label,rx in [('rectangular',r'\brectangular\b'),('round',r'\bround\b|\bcircular\b'),('flexible',r'\bflex(?:ible)?\b')]:
            if re.search(rx,q) and 'duct' in subjects:
                if label=='flexible':
                    test=lambda r: bool(re.search(r'flex|flexibel|flexible|joustava',str(r.get('name') or '')+' '+str(r.get('type_name') or ''),re.I)) or r.get('predefined_type')=='FLEXIBLESEGMENT'
                elif label=='rectangular':
                    test=lambda r: bool(re.search(r'rectang|rechteck|suorakaide|rektang',str(r.get('name') or '')+' '+str(r.get('type_name') or ''),re.I)) or all(r['quantities'].get(k) for k in ('width_m','height_m'))
                else:
                    test=lambda r: not re.search(r'flex|rectang|rechteck|suorakaide|rektang',fold(str(r.get('name') or '')+' '+str(r.get('type_name') or ''))) and (bool(re.search(r'round|circular|rund|pyorea',fold(str(r.get('name') or '')+' '+str(r.get('type_name') or '')))) or bool(r['quantities'].get('diameter_m')))
                rows=[r for r in rows if test(r)]
                filters.append(label+' duct family')
    system_names = {str(s) for r in rows for s in r.get('systems',[])}
    system=re.search(r'\b(?:in|on|of|for)\s+(?:the\s+)?(?:system\s+)[\'\"]?([^?\n,]+)',question,re.I)
    if system:
        target=system[1].strip(' \t\'\".')
        rows=[r for r in rows if any(fold(target)==fold(s) for s in r.get('systems',[]))]
        filters.append('system '+target)
    elif re.search(r'\bsystem\b',q) and not re.search(r'\bby system\b',q):
        named=[s for s in system_names if re.search(rf'(?<!\w){re.escape(fold(s))}(?!\w)',fold(question))]
        if named:
            target=max(named,key=len)
            rows=[r for r in rows if target in r.get('systems',[])]
            filters.append('system '+target)
    diameter=re.search(r'\bDN\s*'+NUMBER,question,re.I)
    explicit_diameter=re.search(r'(?:diameter|[ØøΦ⌀])\s*(?:of\s+|=\s*)?'+NUMBER+r'\s*'+LUNIT,question,re.I)
    if diameter or explicit_diameter:
        val=(float(diameter[1].replace(',','.'))*.001 if diameter else
             float(explicit_diameter[1].replace(',','.'))*FACTORS[_unit(explicit_diameter[2])])
        missing=sum(r['quantities'].get('diameter_m') is None for r in rows)
        if missing:
            return _result(question,doc,rows,None,None,'Size filter cannot be completed.',filters,t0,
                           notes=[f'{missing} elements have no recorded diameter.'],confidence=0.)
        rows=[r for r in rows if abs(r['quantities']['diameter_m']-val)<=1e-6]
        filters.append(f'diameter {val*1000:g} mm')
    rows,label=_type_filter(question,rows,[doc.title,*[s['name'] for s in doc.storeys],*system_names])
    if label:
        filters.append(label)
    count=bool(COUNT.search(question)) and not re.search(r'\bhow many (?:linear |running )?(?:metres?|meters?|feet)\b',q)
    key,unit=(None,'count') if count else ('length_m','m')
    missing=sum(r['quantities'].get(key) is None for r in rows) if key else 0
    if missing and not count and any((_artifacts() / doc.doc_id / n).is_file() for n in ('piping.json', 'mep.json')):
        return None  # no recorded lengths in the IFC, but a measured piping/MEP sidecar exists: that solver answers instead of a refusal
    if missing or idx.get('errors'):
        return _result(question,doc,rows,None,unit,'No complete total can be computed.',filters,t0,
                       notes=[f'{missing} elements have no recorded length.' if missing else 'Some IFC elements could not be indexed.'],confidence=0.)
    value=len(rows) if count else round(sum(r['quantities'][key] for r in rows),4)
    groups=defaultdict(list)
    by_system=bool(re.search(r'\bby system\b',q))
    by_predefined=bool(re.search(r'\bby predefined\b',q))
    for r in rows:
        system_label='; '.join(r.get('systems') or []) or 'System not recorded'
        type_label=r.get('type_name') or r.get('reference') or r.get('name') or 'Type not recorded'
        size=r.get('size_label')
        if not size and r['quantities'].get('diameter_m'):
            size=f'diameter {r["quantities"]["diameter_m"]*1000:g} mm'
        if not size and all(r['quantities'].get(k) for k in ('width_m','height_m')):
            size=f'{r["quantities"]["width_m"]*1000:g} x {r["quantities"]["height_m"]*1000:g} mm'
        from engine.wording import clean_type_name
        type_label=clean_type_name(type_label,False)
        group=system_label if by_system else (r.get('predefined_type') or 'Predefined type not recorded') if by_predefined else f'{system_label}; {type_label}; {r.get("predefined_type") or "Predefined type not recorded"}; {size or "Size not recorded"}'
        groups[group].append(r)
    details=[{'label':label,'value':len(rs) if count else sum(r['quantities'][key] for r in rs),'item_ids':[r['item_id'] for r in rs]} for label,rs in sorted(groups.items())]
    formula=f'Count after filters = {value}.' if count else f'Sum recorded lengths of {len(rows)} elements = {value} m. Sources: '+ '; '.join(sorted({r['sources'].get(key,'not recorded') for r in rows}))+'.'
    return _result(question,doc,rows,value,unit,formula,filters,t0,detail_rows=details)


def answer(question: str, doc: Doc, t0=None):
    if doc.mode!='ifc':
        return None
    t0=t0 or time.perf_counter()
    if re.search(r'\b(?:remove|delete|hide|add|move|change|compare|versus)\b',question,re.I):
        return None
    for fn in (room_baseboard,reinforcement,filtered_counts,mep_families):
        res=fn(question,doc,t0)
        if res is not None:
            return res
    return None
