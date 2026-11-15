"""Schema-neutral IFC quantity sidecar. All measurements retain their source.

No model calls, assumed material densities or bounding-box room perimeters.
Imports of IfcOpenShell stay in ingestion / the optional source-file fallback.
"""
from __future__ import annotations

import math
import re

VERSION = 1
CLASSES = ('IfcWall', 'IfcSlab', 'IfcDoor', 'IfcSpace', 'IfcReinforcingBar',
           'IfcReinforcingMesh', 'IfcTendon', 'IfcDistributionElement',
           'IfcFlowSegment', 'IfcFlowFitting', 'IfcFlowController', 'IfcFlowTerminal')
REINFORCEMENT = {'IfcReinforcingBar': 'rebar', 'IfcReinforcingMesh': 'reinforcing_mesh', 'IfcTendon': 'tendon'}


def norm(s):
    return re.sub(r'[^\w]', '', str(s or '').casefold())


def finite(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)


def project_scale(f, unit_type):
    import ifcopenshell.util.unit as U
    unit = U.get_project_unit(f, unit_type, use_cache=True)
    return U.get_unit_scale(unit) if unit is not None else None


def measured(el, ps, names, unit_type):
    """Return a physical quantity / typed property in SI, with explicit units winning.

    Untyped IfcReal values are deliberately unavailable: some exporters use
    internal feet even when the project declares millimetres.
    """
    import ifcopenshell.util.unit as U
    for name in names:
        for pn, vals in sorted(ps.items(), key=lambda x: not x[0].startswith('Qto_')):
            if not isinstance(vals, dict):
                continue
            for key, entry in vals.items():
                if norm(key) != norm(name) or not isinstance(entry, dict) or not finite(entry.get('value')):
                    continue
                prop = el.file.by_id(entry['id'])
                unit = U.get_property_unit(prop, el.file, use_cache=True)
                if unit is None or unit.UnitType != unit_type:
                    continue
                scale = U.get_unit_scale(unit)
                # IfcOpenShell normalises mass to grams (the IFC SI base name),
                # while our contract records kilograms, including kg/m3.
                if unit_type in ('MASSUNIT', 'MASSDENSITYUNIT'):
                    scale /= 1000.
                v = float(entry['value']) * scale
                if math.isfinite(v) and v >= 0:
                    return v, f'{pn}.{key} (declared unit converted to SI)'
    return None, None


def text_prop(ps, names):
    for name in names:
        for vals in ps.values():
            if not isinstance(vals, dict):
                continue
            for key, entry in vals.items():
                if norm(key) == norm(name) and isinstance(entry, dict):
                    val = entry.get('value')
                    if val not in (None, ''):
                        return val
    return None


def attribute(el, name, unit_type):
    v = getattr(el, name, None)
    scale = project_scale(el.file, unit_type)
    if finite(v) and v >= 0 and scale is not None:
        return float(v) * scale, f'{el.is_a()}.{name} (project unit converted to SI)'
    return None, None


def _storey(el):
    import ifcopenshell.util.element as E
    cur, seen = el, set()
    while cur is not None and cur.id() not in seen:
        seen.add(cur.id())
        if cur.is_a('IfcBuildingStorey'):
            return cur.Name or 'Unnamed level'
        cur = E.get_container(cur) or E.get_aggregate(cur)
    return None


def _layers(el):
    import ifcopenshell.util.element as E
    scale = project_scale(el.file, 'LENGTHUNIT')
    if scale is None:
        return None, None
    mat = E.get_material(el)
    if mat is not None and mat.is_a('IfcMaterialLayerSetUsage'):
        mat = mat.ForLayerSet
    if mat is not None and mat.is_a('IfcMaterialLayerSet'):
        vals = [l.LayerThickness for l in mat.MaterialLayers]
        if vals and all(finite(v) and v >= 0 for v in vals) and sum(vals) > 0:
            return sum(vals) * scale, 'sum of material layer thicknesses (project length unit)'
    return None, None


def _body_items(el):
    reps = getattr(getattr(el, 'Representation', None), 'Representations', ()) or ()
    return [i for r in reps if r.RepresentationIdentifier in ('Body', None, '') for i in r.Items]


def geometry_length(el):
    """Swept centreline length, including bends. A mesh extent is never a bar length."""
    import ifcopenshell.geom as G
    import ifcopenshell.util.unit as U
    scale = project_scale(el.file, 'LENGTHUNIT')
    if scale is None:
        return None, None
    total = 0.
    stack = [(i, 1.) for i in _body_items(el)]
    n = 0
    while stack and n < 100:
        n += 1
        item, factor = stack.pop()
        if item.is_a('IfcMappedItem'):
            target = item.MappingTarget
            s1 = float(getattr(target, 'Scale', None) or 1.)
            if any(getattr(target, k, None) not in (None, s1) for k in ('Scale2', 'Scale3')):
                return None, None
            stack.extend((x, factor * s1) for x in item.MappingSource.MappedRepresentation.Items)
        elif item.is_a('IfcSweptDiskSolid'):
            try:
                sh = G.create_shape(G.settings(), item.Directrix)
                verts = list(zip(*(iter(sh.verts),) * 3))
                edges = list(zip(*(iter(sh.edges),) * 2))
                total += factor * sum(math.dist(verts[a], verts[b]) for a, b in edges)
            except (RuntimeError, AttributeError, ValueError):
                return None, None
        elif item.is_a('IfcExtrudedAreaSolid'):
            total += float(item.Depth) * scale * factor
        else:
            return None, None  # unknown body: never report an incomplete centreline
    return (total, 'swept body centreline geometry in metres') if total > 0 and not stack else (None, None)


def footprint_perimeter(space):
    """Perimeter of the union of lowest horizontal floor faces, including holes.

    Weld geometric coordinates before counting triangle edges: exporters may
    split identical vertices at face/material boundaries. No bounding box.
    """
    if project_scale(space.file, 'LENGTHUNIT') is None:
        return None, None
    try:
        import ifcopenshell.geom as G
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        st = G.settings()
        st.set('use-world-coords', True)
        sh = G.create_shape(st, space)
        verts = list(zip(*(iter(sh.geometry.verts),) * 3))
        faces = list(zip(*(iter(sh.geometry.faces),) * 3))
        if not verts:
            return None, None
        z0 = min(v[2] for v in verts)
        # IFC precision defaults to 1e-5 m in the geometry kernel. Tolerance is
        # geometric precision, independent of room size or document identity.
        polygons = [Polygon([(verts[i][0], verts[i][1]) for i in face]) for face in faces
                    if all(abs(verts[i][2] - z0) <= 1e-5 for i in face)]
        polygons = [p for p in polygons if p.is_valid and p.area > 1e-10]
        if not polygons:
            return None, None
        floor = unary_union(polygons)
        return float(floor.length), 'union of IfcSpace lowest floor faces (metres)'
    except (RuntimeError, ValueError, AttributeError):
        return None, None


def _systems(f):
    result = {}
    for system in f.by_type('IfcSystem'):
        name = system.Name or getattr(system, 'LongName', None)
        if not name:
            continue
        pending, seen = [system], set()
        while pending:
            group = pending.pop()
            if group.id() in seen:
                continue
            seen.add(group.id())
            for rel in getattr(group, 'IsGroupedBy', ()) or ():
                for obj in rel.RelatedObjects:
                    if obj.is_a('IfcGroup'):
                        pending.append(obj)
                    elif getattr(obj, 'GlobalId', None):
                        result.setdefault(obj.GlobalId, set()).add(name)
    return result


def _space_groups(space):
    import ifcopenshell.util.element as E
    names, cur, seen = [], space, set()
    while cur is not None and cur.id() not in seen:
        seen.add(cur.id())
        for rel in getattr(cur, 'HasAssignments', ()) or ():
            if rel.is_a('IfcRelAssignsToGroup'):
                group = rel.RelatingGroup
                names.extend(x for x in (group.Name, getattr(group, 'LongName', None)) if x)
        cur = E.get_aggregate(cur)
        if cur is not None and cur.is_a('IfcSpace'):
            names.extend(x for x in (cur.Name, cur.LongName) if x)
    return list(dict.fromkeys(names))


def build(f, *, space_geometry=False):
    """Compact rows covering every supported class, even when a class has zero instances."""
    import ifcopenshell.util.element as E
    from engine.mep import _classify0
    entities, indexed = {}, []
    for cls in CLASSES:
        try:
            ents = f.by_type(cls)
        except RuntimeError:  # class absent in this schema
            continue
        indexed.append(cls)
        entities.update((e.GlobalId, e) for e in ents)
    systems = _systems(f)
    rows, errors = [], []
    for gid, el in entities.items():
        try:
            try:
                ps = E.get_psets(el, verbose=True)
            except KeyError:   # ifcopenshell cannot describe an unusual quantity entity: keep the property sets, drop that element's Qto
                ps = E.get_psets(el, psets_only=True, verbose=True)
            typ = E.get_type(el)
            classes = [c for c in indexed if el.is_a(c)]
            kind = next((k for c, k in REINFORCEMENT.items() if el.is_a(c)), None)
            if kind is None:
                kind = next((k for c, k in [('IfcSpace', 'room'), ('IfcWall', 'wall'), ('IfcSlab', 'slab'), ('IfcDoor', 'door')] if el.is_a(c)), None)
            if kind is None:
                kind = _classify0(el, typ, E.get_psets(el))
            q, sources = {}, {}
            def put(key, result):
                value, source = result
                if value is not None:
                    q[key], sources[key] = value, source
            put('length_m', measured(el, ps, ('Length', 'BarLength', 'NetLength', 'LongitudinalBarLength'), 'LENGTHUNIT'))
            if 'length_m' not in q:
                put('length_m', attribute(el, 'BarLength', 'LENGTHUNIT'))
            if kind in REINFORCEMENT.values() and 'length_m' not in q:
                put('length_m', geometry_length(el))
            for key, names, unit in [
                ('width_m', ('OverallWidth', 'Width'), 'LENGTHUNIT'),
                ('diameter_m', ('NominalDiameter', 'BarDiameter', 'Diameter'), 'LENGTHUNIT'),
                ('height_m', ('Height', 'OverallHeight'), 'LENGTHUNIT'),
                ('area_m2', ('GrossArea', 'NetArea', 'Area'), 'AREAUNIT'),
                ('volume_m3', ('NetVolume', 'GrossVolume', 'Volume'), 'VOLUMEUNIT'),
                ('cross_section_m2', ('CrossSectionArea',), 'AREAUNIT'),
                ('mass_kg', ('NetWeight', 'GrossWeight', 'Weight', 'Mass'), 'MASSUNIT'),
                ('density_kg_m3', ('MassDensity', 'Density'), 'MASSDENSITYUNIT'),
                ('perimeter_m', ('NetPerimeter', 'Perimeter', 'GrossPerimeter'), 'LENGTHUNIT')]:
                put(key, measured(el, ps, names, unit))
            for key, attr, unit in [('diameter_m', 'NominalDiameter', 'LENGTHUNIT'),
                                    ('cross_section_m2', 'CrossSectionArea', 'AREAUNIT'),
                                    ('longitudinal_diameter_m', 'LongitudinalBarNominalDiameter', 'LENGTHUNIT'),
                                    ('transverse_diameter_m', 'TransverseBarNominalDiameter', 'LENGTHUNIT'),
                                    ('width_m', 'OverallWidth', 'LENGTHUNIT')]:
                if key not in q:
                    put(key, attribute(el, attr, unit))
            if kind in ('wall', 'slab'):
                put('thickness_m', _layers(el))
                if 'thickness_m' not in q:
                    put('thickness_m', measured(el, ps, ('Thickness', 'Depth', 'Width') if kind == 'slab' else ('Thickness', 'Width'), 'LENGTHUNIT'))
            # Density may be attached to the material rather than the occurrence.
            if kind in REINFORCEMENT.values() and 'density_kg_m3' not in q:
                for material in E.get_materials(el):
                    try:
                        mps = E.get_psets(material, verbose=True)
                    except KeyError:
                        mps = E.get_psets(material, psets_only=True, verbose=True)
                    value = measured(material, mps, ('MassDensity', 'Density'), 'MASSDENSITYUNIT')
                    if value[0] is not None and len(E.get_materials(el)) == 1:
                        put('density_kg_m3', value)
            if kind in REINFORCEMENT.values() and 'mass_kg' not in q and q.get('density_kg_m3'):
                volume = q.get('volume_m3')
                source = sources.get('volume_m3')
                if volume is None and q.get('length_m') is not None:
                    area = q.get('cross_section_m2')
                    source = sources.get('cross_section_m2')
                    if area is None and q.get('diameter_m') is not None and kind in ('rebar', 'tendon'):
                        area = math.pi * q['diameter_m'] ** 2 / 4
                        source = sources['diameter_m'] + '; circular section'
                    if area is not None:
                        volume = area * q['length_m']
                        source = f'{source}; multiplied by {sources["length_m"]}'
                if volume is not None:
                    put('mass_kg', (volume * q['density_kg_m3'], f'{source}; multiplied by {sources["density_kg_m3"]}'))
            boundary_doors = {}
            if kind == 'room':
                for rel in getattr(el, 'BoundedBy', ()) or ():
                    door = rel.RelatedBuildingElement
                    if door is not None and door.is_a('IfcDoor'):
                        boundary_doors[door.GlobalId] = attribute(door, 'OverallWidth', 'LENGTHUNIT')[0]
                if space_geometry:
                    put('perimeter_m', footprint_perimeter(el))
            row = {'item_id': gid, 'kind': kind, 'ifc_class': el.is_a(), 'classes': classes,
                   'name': el.Name, 'long_name': getattr(el, 'LongName', None),
                   'type_name': typ.Name if typ is not None else getattr(el, 'ObjectType', None),
                   'reference': text_prop(ps, ('Reference', 'Family and Type', 'Family')),
                   'predefined_type': E.get_predefined_type(el),
                   'bar_role': text_prop(ps, ('BarRole', 'Bar Role', 'Role')) or getattr(el, 'BarRole', None),
                   'storey': _storey(el), 'quantities': q, 'sources': sources,
                   'is_external': text_prop(ps, ('IsExternal',)),
                   'systems': sorted(systems.get(gid, ())) or [str(v) for v in [text_prop(ps, ('System Name', 'SystemName', 'System'))] if v],
                   'size_label': text_prop(ps, ('Size', 'Overall Size')),
                   'boundary_doors': boundary_doors,
                   'boundaries_recorded': bool(getattr(el, 'BoundedBy', ()) or ()),
                   'groups': _space_groups(el) if kind == 'room' else []}
            rows.append(row)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            errors.append({'item_id': gid, 'ifc_class': el.is_a(), 'reason': type(exc).__name__})
    return {'version': VERSION, 'schema': f.schema, 'indexed_classes': indexed, 'rows': rows, 'errors': errors}
