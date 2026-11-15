"""Generated-for-demo geometry: preserve identity, units, voids and GLB bytes."""
import json
from pathlib import Path

import ifcopenshell
from ifcopenshell import geom
import numpy as np
import pytest

from pipeline.ifc_facets import mesh, triangulate
from pipeline.ifc_fragments import Fragments, references


def box_model(schema='IFC4', imperial=False, mapped=False):
    f = ifcopenshell.file(schema=schema)
    def point(xyz): return f.create_entity('IfcCartesianPoint', tuple(map(float, xyz)))
    axis = f.create_entity('IfcAxis2Placement3D', Location=point((0, 0, 0)))
    context = f.create_entity('IfcGeometricRepresentationContext', ContextType='Model', CoordinateSpaceDimension=3,
                              Precision=1e-6, WorldCoordinateSystem=axis)
    metre = f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE')
    length = metre
    if imperial:
        dimensions = f.create_entity('IfcDimensionalExponents', 1, 0, 0, 0, 0, 0, 0)
        measure = f.create_entity('IfcMeasureWithUnit', f.create_entity('IfcLengthMeasure', .3048), metre)
        length = f.create_entity('IfcConversionBasedUnit', dimensions, 'LENGTHUNIT', 'foot', measure)
    units = f.create_entity('IfcUnitAssignment', [length])
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), RepresentationContexts=[context], UnitsInContext=units)
    coords = [(0,0,0),(2,0,0),(2,1,0),(0,1,0),(0,0,3),(2,0,3),(2,1,3),(0,1,3)]
    points = [point(c) for c in coords]
    faces = []
    for loop in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
        poly = f.create_entity('IfcPolyLoop', [points[i] for i in loop])
        bound = f.create_entity('IfcFaceOuterBound', poly, True)
        faces.append(f.create_entity('IfcFace', [bound]))
    brep = f.create_entity('IfcFacetedBrep', f.create_entity('IfcClosedShell', faces))
    rep = f.create_entity('IfcShapeRepresentation', context, 'Body', 'Brep', [brep])
    if mapped:
        origin = f.create_entity('IfcAxis2Placement3D', Location=point((1,0,0)))
        mapping = f.create_entity('IfcRepresentationMap', origin, rep)
        target = f.create_entity('IfcCartesianTransformationOperator3D', LocalOrigin=point((4,5,6)), Scale=2.)
        mapped_item = f.create_entity('IfcMappedItem', mapping, target)
        rep = f.create_entity('IfcShapeRepresentation', context, 'Body', 'MappedRepresentation', [mapped_item])
    placement = f.create_entity('IfcLocalPlacement', RelativePlacement=f.create_entity('IfcAxis2Placement3D', Location=point((10,20,30))))
    element = f.create_entity('IfcBuildingElementProxy', GlobalId=ifcopenshell.guid.new(), Name="generated for demo ; #999999 ' quote",
                              ObjectPlacement=placement, Representation=f.create_entity('IfcProductDefinitionShape', Representations=[rep]))
    return f, element


def test_step_references_ignore_quotes_and_comments():
    assert references(b"#1=IFCTHING('do not read #88; '' #99',#2,/*#77*/#3);") == [1,2,3]


@pytest.mark.parametrize('holes', [False, True])
def test_constrained_facets_preserve_concavity_and_holes(holes):
    outer = [(0,0,0),(3,0,0),(3,3,0),(0,3,0)] if holes else [(0,0,0),(2,0,0),(2,1,0),(1,1,0),(1,2,0),(0,2,0)]
    inner = [[(1,1,0),(2,1,0),(2,2,0),(1,2,0)]] if holes else []
    triangles = triangulate(outer, inner)
    points = np.asarray([*outer, *[p for ring in inner for p in ring]])
    area = sum(np.linalg.norm(np.cross(points[b]-points[a], points[c]-points[a]))/2 for a,b,c in triangles)
    assert area == pytest.approx(8 if holes else 3)


@pytest.mark.parametrize('schema', ['IFC2X3','IFC4','IFC4X3'])
@pytest.mark.parametrize('imperial,mapped', [(False,False),(True,True)])
def test_fragments_and_facets_preserve_native_geometry(tmp_path, schema, imperial, mapped):
    f, element = box_model(schema, imperial, mapped)
    source = tmp_path / 'source.ifc'
    f.write(str(source))
    fragments = Fragments(source, tmp_path / 'step.sqlite')
    try:
        batches = list(fragments.batches(max_products=1))
        assert len(batches) == 1 and batches[0][0] == [element.id()]
        fragments.write(tmp_path / 'part.ifc', batches[0][1])
    finally:
        fragments.close()
    part = ifcopenshell.open(str(tmp_path / 'part.ifc'), lazy=True)
    actual = part.by_guid(element.GlobalId)
    assert actual.Name == element.Name
    vertices, faces = mesh(actual)
    assert len(faces) == 36
    settings = geom.settings()
    settings.set('use-world-coords', True)
    native = geom.create_shape(settings, element)
    expected = np.asarray(native.geometry.verts).reshape(-1,3)
    assert vertices.min(axis=0) == pytest.approx(expected.min(axis=0))
    assert vertices.max(axis=0) == pytest.approx(expected.max(axis=0))


def test_product_openings_are_retained_and_force_native_subtraction(tmp_path):
    f, host = box_model()
    opening = f.create_entity('IfcOpeningElement', GlobalId=ifcopenshell.guid.new(), Representation=host.Representation,
                              ObjectPlacement=host.ObjectPlacement)
    relation = f.create_entity('IfcRelVoidsElement', GlobalId=ifcopenshell.guid.new(), RelatingBuildingElement=host, RelatedOpeningElement=opening)
    f.write(str(tmp_path / 'source.ifc'))
    fragments = Fragments(tmp_path / 'source.ifc', tmp_path / 'step.sqlite')
    try:
        ids, selected = next(fragments.batches())
        assert ids == [host.id()]
        assert {relation.id(), opening.id()} <= selected
        fragments.write(tmp_path / 'part.ifc', selected)
    finally:
        fragments.close()
    part = ifcopenshell.open(str(tmp_path / 'part.ifc'))
    assert len(part.by_guid(host.GlobalId).HasOpenings) == 1
    assert mesh(part.by_guid(host.GlobalId)) is None


def test_scene_reuses_index_and_streams_unchanged_binary(tmp_path, monkeypatch):
    from pipeline import ifc_index, ifc_scene
    from pipeline.ifc_scene_indexed import read_header
    f, element = box_model()
    source = tmp_path / 'source.ifc'
    f.write(str(source))
    doc = {'doc_id': 'generated-for-demo', 'licence': 'CC-BY-4.0'}
    ifc_index.process(source, doc, tmp_path)
    index = json.loads((tmp_path / 'elements.json').read_text())
    index['elements'][0]['quantities'] = {'width_m': 17.25}
    index['elements'][0]['quantity_source'] = {'width_m': 'qto'}
    (tmp_path / 'elements.json').write_text(json.dumps(index))
    monkeypatch.setenv('IFC_CONVERT_PY', '1')
    monkeypatch.setattr(ifc_index, 'open_properties', lambda *a: pytest.fail('The completed index must be reused'))
    monkeypatch.setattr(ifc_scene.GLTF2, 'load', lambda *a: pytest.fail('Do not load the GLB triangle blob'))
    result = ifc_scene.process(source, doc, tmp_path)
    assert result['nodes'] == 1
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    assert set(manifest['items']) == {element.GlobalId}
    assert manifest['items'][element.GlobalId]['node'] == element.GlobalId
    index = json.loads((tmp_path / 'elements.json').read_text())
    assert index['elements'][0]['quantities']['width_m'] == 17.25
    assert index['geometry'] == 'ready'
    raw, final = tmp_path / 'tmp/raw.glb', tmp_path / 'scene.glb'
    _, raw_offset, raw_length = read_header(raw)
    header, final_offset, final_length = read_header(final)
    assert raw_length == final_length
    assert raw.read_bytes()[raw_offset:] == final.read_bytes()[final_offset:]
    assert header['nodes'][0]['extras']['kind'] == 'proxy'
