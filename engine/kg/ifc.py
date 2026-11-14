"""IFC semantic relationships, across schemas (no geometry evaluation; optional dependency)."""
from pathlib import Path

from .build import read_dict
from .schema import norm


def source_path(doc_id, root):
    meta = read_dict(Path(root) / doc_id / 'doc.json')
    rel = (meta.get('files') or {}).get('ifc')
    if rel:
        for base in (Path(root).resolve().parent / 'data' / 'full' / 'junction-dataset',
                     Path(root).resolve().parent / 'data' / 'junction-dataset-preview', Path(root).resolve().parent,
                     Path(root).parent, Path.cwd()):
            p = base / rel
            if p.is_file():
                return p
    p = Path(root) / doc_id / 'source.ifc'
    return p if p.is_file() else None


def _by_type(model, cls):
    try:
        return model.by_type(cls)
    except RuntimeError:  # entity is not defined in some IFC schema editions
        return []


def _id(entity):
    return str(getattr(entity, 'GlobalId', None) or '')


def _materials(obj, seen=None):
    """Walk IFC2x3 layers and IFC4 constituent/profile material sets without geometry or pset evaluation."""
    if obj is None:
        return []
    seen = seen if seen is not None else set()
    if obj.id() in seen:
        return []
    seen.add(obj.id())
    if obj.is_a('IfcMaterial'):
        return [obj.Name] if obj.Name else []
    out = []
    for key in ('Material', 'Materials', 'ForLayerSet', 'MaterialLayers', 'ForProfileSet', 'MaterialProfiles', 'MaterialConstituents'):
        value = getattr(obj, key, None)
        for sub in value if isinstance(value, (list, tuple)) else [value]:
            if sub is not None and hasattr(sub, 'is_a'):
                out.extend(_materials(sub, seen))
    return list(dict.fromkeys(out))


def enrich_ifc(b):
    try:
        import ifcopenshell
    except ImportError:
        if any(i.doc and i.doc.mode == 'ifc' and not i.derived for i in b.combined.infos.values()):
            b.warnings.append({'note': 'IFC reader unavailable; semantic links use the stored index only.'})
        return
    for did, info in b.combined.infos.items():
        if not info.doc or info.doc.mode != 'ifc' or info.derived:
            continue
        path = source_path(did, b.root)
        if path is None:
            b.warnings.append({'doc_id': did, 'note': 'Original IFC unavailable; deeper semantic relationships cannot be read.'})
            continue
        try:
            model = ifcopenshell.open(str(path))
            _enrich_model(b, did, model)
        except Exception as exc:  # noqa: BLE001 - one odd or incomplete file cannot hide the rest of the project
            b.warnings.append({'doc_id': did, 'note': f'IFC semantic relationships partly unavailable ({type(exc).__name__}).'})


def _enrich_model(b, did, model):
    def node(obj):
        return b.lookup(did, _id(obj)) if obj is not None else None

    def edge(kind, a, z, rel, **extra):
        return b.edge(kind, a, z, 'ifc_relation', 1, {'relation': rel.is_a(), 'relation_id': _id(rel), **extra}, [did])

    for element in _by_type(model, 'IfcElement'):
        nid = node(element)
        if nid and getattr(element, 'Tag', None):
            b.nodes[nid]['props']['tag'] = element.Tag
    # Containment is authoritative. Spaces are often aggregated, rather than contained, under a storey.
    for rel in _by_type(model, 'IfcRelContainedInSpatialStructure') + _by_type(model, 'IfcRelAggregates'):
        parent = getattr(rel, 'RelatingStructure', None) or getattr(rel, 'RelatingObject', None)
        children = getattr(rel, 'RelatedElements', None) or getattr(rel, 'RelatedObjects', None) or []
        if parent is None:
            continue
        if parent.is_a('IfcBuildingStorey'):
            ln = b.level(did, parent.Name or 'Unnamed level')
            for child in children:
                cn = node(child)
                if cn:
                    if not b.nodes[cn].get('level'):
                        b.nodes[cn]['level'] = parent.Name or 'Unnamed level'
                    edge('on_level', cn, ln, rel)
                    if b.nodes[cn]['kind'] == 'room':
                        edge('contains', ln, cn, rel)
        elif parent.is_a('IfcSpace'):
            rn = node(parent)
            for child in children:
                edge('in_room', node(child), rn, rel)
    for rel in _by_type(model, 'IfcRelSpaceBoundary'):
        wall, room = node(rel.RelatedBuildingElement), node(rel.RelatingSpace)
        if wall and room:
            edge('bounds', wall, room, rel, boundary_type=getattr(rel, 'InternalOrExternalBoundary', None))
    voids = {_id(r.RelatedOpeningElement): r for r in _by_type(model, 'IfcRelVoidsElement')}
    for rel in _by_type(model, 'IfcRelFillsElement'):
        vr = voids.get(_id(rel.RelatingOpeningElement))
        if vr:
            edge('hosted_by', node(rel.RelatedBuildingElement), node(vr.RelatingBuildingElement), rel,
                 via_relation=vr.is_a(), via_relation_id=_id(vr), opening_id=_id(rel.RelatingOpeningElement))
    for rel in _by_type(model, 'IfcRelAssignsToGroup'):
        group = rel.RelatingGroup
        if not group.is_a('IfcSystem'):
            continue
        sn = b.node('system', did, _id(group) or norm(group.Name), group.Name or 'Building services system',
                    props={'system': getattr(group, 'PredefinedType', None)})
        edge('contains', b.doc_nodes[did], sn, rel)
        for child in rel.RelatedObjects or []:
            edge('part_of_system', node(child), sn, rel)
    for rel in _by_type(model, 'IfcRelDefinesByType'):
        typ = rel.RelatingType
        tn = b.node('type', did, norm(typ.Name) or _id(typ), typ.Name or 'Element type')
        edge('contains', b.doc_nodes[did], tn, rel)
        for child in rel.RelatedObjects or []:
            edge('has_type', node(child), tn, rel)
    for rel in _by_type(model, 'IfcRelAssociatesMaterial'):
        for material in _materials(rel.RelatingMaterial):
            mn = b.node('material', did, norm(material), material)
            edge('contains', b.doc_nodes[did], mn, rel)
            for child in rel.RelatedObjects or []:
                edge('made_of', node(child), mn, rel)
