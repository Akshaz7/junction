"""A source-only overview for any indexed IFC; no reader or model required."""
import math
import re
import time
from collections import Counter
from pathlib import Path

from engine.ifc_levels import unique_levels, level_label
from engine.solvers.solve import _answer_obj, _step

OVERVIEW = re.compile(r'^\s*(?:what (?:is|are) (?:this|the|these)(?: drawing| model| building| document| file| project| plans?)?|(?:give (?:me|us) |provide )?(?:an? )?(?:overview|summary)(?: of (?:this|the)(?: drawing| model| building| document| file| project))?|(?:summarise|summarize|describe|identify) (?:this|the) (?:drawing|model|building|document|file|project))\s*[?.!]*\s*$', re.I)


def answer(question, doc, t0=None, root=None):
    if doc.mode != 'ifc' or not OVERVIEW.fullmatch(question):
        return None
    meta = doc.meta
    building = meta.get('building') or {}
    project = meta.get('project') or {}
    title = building.get('long_name') or building.get('name') or project.get('long_name') or project.get('name') or doc.title or 'Unnamed building'
    software = ', '.join(meta.get('applications') or []) or (meta.get('header') or {}).get('originating_system') or 'authoring software not recorded'
    schema = meta.get('schema') or 'schema not recorded'
    units = meta.get('indexed_units') or 'not recorded'
    levels = unique_levels(doc.storeys)
    counts = Counter(i.kind for i in doc.items if i.props.get('ifc_class'))
    class_counts = Counter(i.props['ifc_class'] for i in doc.items if i.props.get('ifc_class'))
    words = {'wall':'walls', 'door':'doors', 'window':'windows', 'room':'rooms', 'slab':'slabs', 'column':'columns', 'beam':'beams', 'stair':'stairs', 'stairs':'stairs', 'roof':'roofs'}
    main_counts = [(k,n) for k,n in counts.most_common() if k in words]
    other = sum(n for k,n in counts.items() if k not in words)
    count_text = ', '.join([f'{n:,} {words[k]}' for k,n in main_counts] + ([f'{other:,} other building elements'] if other else [])) or 'No building elements indexed'
    rooms = [i for i in doc.items if i.kind == 'room']
    areas, measured = [], []
    glb = Path(root) / doc.doc_id / 'scene.glb' if root else None
    for room in rooms:
        a = next((room.q[k] for k in ('area_m2','net_floor_area_m2','gross_floor_area_m2') if isinstance(room.q.get(k), (int,float)) and math.isfinite(room.q[k]) and room.q[k] > 0), None)
        if a is None and glb and glb.is_file() and len(rooms) <= 400:
            from engine.solvers.glbarea import room_floor_area_m2
            a = room_floor_area_m2(glb, room.item_id)
            if a is not None:
                measured.append(room.item_id)
        if a is not None:
            areas.append((room, a))
    missing = len(rooms) - len(areas)
    area = sum(v for _,v in areas)
    area_text = (f'{area:,.2f} m² '+('room floor area (measured from indexed room geometry where quantities are missing)' if measured else 'recorded room area') + (f' (subtotal; {missing} rooms have no usable area)' if missing else '') if areas else 'Room area is not recorded')
    cites = [dict(n=1, doc_id=doc.doc_id, page=1, kind='text', bbox_px=None, item_ids=[], quote=str({'building':building,'project':project,'applications':meta.get('applications'),'header':meta.get('header'),'schema':schema,'indexed_units':units})),
             dict(n=2, doc_id=doc.doc_id, page=1, kind='text', bbox_px=None, item_ids=[], quote='Recorded storeys: ' + str(doc.storeys)),
             dict(n=3, doc_id=doc.doc_id, page=1, kind='element', bbox_px=None, item_ids=[i.item_id for i in doc.items if i.props.get('ifc_class')], quote='Indexed element class counts: ' + str(dict(class_counts))),
             dict(n=4, doc_id=doc.doc_id, page=1, kind='element' if rooms else 'text', bbox_px=None, item_ids=[i.item_id for i in rooms], quote=area_text + '; sum of room areas from elements.json and, where missing, scene.glb floor geometry: ' + str({r.item_id:v for r,v in areas}))]
    level_text = '; '.join(level_label(s) for s in levels) or 'none recorded'
    text = f'**This is an IFC building model: {title}.** [1]\n\n- Project: {project.get("name") or "not recorded"}; {software}; {schema}; indexed units: {units}. [1]\n- {len(levels)} distinct levels: {level_text}. [2]\n- Indexed elements: {count_text}. [3]\n- {area_text}. Room areas are not gross building area. [4]'
    res = _answer_obj(question, [doc.doc_id], text, None, None, 1., False, [], cites,
                      {'doc_id':doc.doc_id,'highlight_item_ids':[],'camera_target_item_id':None},
                      [_step('ifc_overview','Overview from indexed project/building metadata, storeys, element classes and room areas; no model')], 'index', t0 or time.perf_counter())
    res['ifc_overview'] = {'levels':levels, 'class_counts':dict(class_counts), 'room_area_m2':area if areas else None, 'rooms_missing_area':missing}
    res['reasoning'] = {'steps':[{'kind':'read','title':'Model identity','text':f'{title}; {software}; {schema}.','cite':1,'ok':None},
                                {'kind':'found','title':'Levels and elements','text':f'{len(levels)} distinct levels; {sum(class_counts.values())} indexed building elements. Aliases at the same elevation are deduplicated.','cite':2,'ok':None},
                                {'kind':'calculated','title':'Recorded room areas','text':area_text + '; no missing areas inferred.','cite':4,'ok':None}],
                        'confidence':{'label':'Verified','pct':None,'reason':'Read directly from the cited IFC index; index completeness is not verified.','improve':None}}
    return res
