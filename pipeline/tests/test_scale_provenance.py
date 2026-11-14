import math

import ezdxf
import ifcopenshell
import pytest

from pipeline.scale_provenance import dxf_scale, dxf_units, ifc_units


@pytest.mark.parametrize(('code', 'factor'), [(1, .0254), (2, .3048), (4, .001), (5, .01), (6, 1), (7, 1000), (14, .1), (21, 1200 / 3937)])
def test_dxf_declared_units_including_imperial_and_extended_table(code, factor):
    doc = ezdxf.new(); doc.header['$INSUNITS'] = code
    out = dxf_scale(doc, {'a': 2, 'rms_px': .5}, 'test')
    assert out['m_per_px'] == pytest.approx(factor / 2, rel=1e-6)
    assert out['native_units']['m_per_unit'] == pytest.approx(factor, rel=1e-6)
    assert out['derivation']['inputs'][0]['source']['header'] == '$INSUNITS'


def test_dxf_unitless_is_unknown():
    doc = ezdxf.new(); doc.header['$INSUNITS'] = 0
    assert dxf_units(doc, 'test')['m_per_unit'] is None
    assert dxf_scale(doc, {'a': 2}, 'test')['m_per_px'] is None


@pytest.mark.parametrize('schema', ['IFC2X3', 'IFC4', 'IFC4X3'])
@pytest.mark.parametrize(('prefix', 'factor'), [(None, 1), ('MILLI', .001), ('CENTI', .01)])
def test_ifc_schema_and_si_units(schema, prefix, factor):
    f = ifcopenshell.file(schema=schema)
    u = f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE', Prefix=prefix)
    ass = f.create_entity('IfcUnitAssignment', Units=[u])
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), UnitsInContext=ass)
    r = ifc_units(f, 'test')
    assert r['m_per_unit'] == pytest.approx(factor)
    assert r['inputs'][0]['source']['assignment'] == f'#{ass.id()}'


def test_ifc_conversion_based_foot_uses_declaration_not_english_name():
    f = ifcopenshell.file(schema='IFC4')
    base = f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE')
    cf = f.create_entity('IfcMeasureWithUnit', ValueComponent=f.create_entity('IfcLengthMeasure', .3048), UnitComponent=base)
    dim = f.create_entity('IfcDimensionalExponents', LengthExponent=1, MassExponent=0, TimeExponent=0,
                          ElectricCurrentExponent=0, ThermodynamicTemperatureExponent=0, AmountOfSubstanceExponent=0, LuminousIntensityExponent=0)
    foot = f.create_entity('IfcConversionBasedUnit', Dimensions=dim, UnitType='LENGTHUNIT', Name='jalka/Fuß/fot', ConversionFactor=cf)
    ass = f.create_entity('IfcUnitAssignment', Units=[foot])
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), UnitsInContext=ass)
    r = ifc_units(f, 'test')
    assert r['m_per_unit'] == pytest.approx(.3048)
    assert math.prod(i['value'] for i in r['inputs']) == pytest.approx(r['m_per_unit'])
    assert r['inputs'][0]['source']['entity'] == f'#{cf.id()}'


def test_ifc_absent_or_ambiguous_units_never_defaults_to_metres():
    f = ifcopenshell.file(schema='IFC4')
    assert ifc_units(f, 'test')['m_per_unit'] is None
    units = [f.create_entity('IfcSIUnit', UnitType='LENGTHUNIT', Name='METRE', Prefix=p) for p in (None, 'MILLI')]
    ass = f.create_entity('IfcUnitAssignment', Units=units)
    f.create_entity('IfcProject', GlobalId=ifcopenshell.guid.new(), UnitsInContext=ass)
    assert ifc_units(f, 'test')['m_per_unit'] is None
