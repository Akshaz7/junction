"""Stair assemblies vs their aggregated flights (synthetic, generated for test)."""
from engine.analytics import storey_compare
from engine.solvers.data import Doc, Item
from engine.tests.test_acc_ifc import model, entity, aggregate
from pipeline.ifc_accuracy import count_metadata


def stair_doc():
    mk = lambda i, st, comp=None, cls='IfcStair': Item(i, 'stairs', storey=st, bbox_m=((0, 0, 0), (1, 1, 1)),
                                                      props={'ifc_class': cls, **({'count_component_of': comp} if comp else {})})
    items = [mk('S1', 'Ground'), mk('F1', 'Ground', 'S1', 'IfcStairFlight'), mk('F2', 'Ground', 'S1', 'IfcStairFlight')]
    return Doc('d', 'ifc', items, storeys=[{'name': 'Ground', 'elevation_m': 0}, {'name': 'Upper', 'elevation_m': 3}])


def test_flights_of_an_assembly_are_not_stairs():
    q = 'Count IfcStair assemblies separately from IfcStairFlight elements. Give counts per storey. Which can be confirmed as protected escape stairs?'
    r = storey_compare(q, stair_doc(), 0)
    assert r['answer']['value'] == 1
    assert 'Ground 1' in r['answer']['text_md'] and '2 stair flights belong' in r['answer']['text_md'] and 'Ground 2' in r['answer']['text_md']
    assert 'not determined' in r['answer']['text_md']


def test_aggregated_flights_are_marked_as_components():
    f = model()
    stair = entity(f, 'IfcStair', 'Stair')
    fl = [entity(f, 'IfcStairFlight', f'Flight {i}') for i in (1, 2)]
    aggregate(f, stair, *fl)
    assert count_metadata(stair)['count_component_of'] is None
    assert all(count_metadata(x)['count_component_of'] == stair.GlobalId for x in fl)
