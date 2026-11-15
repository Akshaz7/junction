"""Generic (non-Swiss) DXF path: rooms from closed wall loops, openings from layers, scale from $INSUNITS."""
import ezdxf

from pipeline import dxf_generic


def _doc():
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # millimetres
    for name in ("A-WALL", "A-DOOR", "A-GLAZ"):
        doc.layers.add(name)
    ms = doc.modelspace()
    # 3 m x 2 m room bounded by four 100 mm wall rectangles
    for pts in ([(0, 0), (3200, 0), (3200, 100), (0, 100)], [(0, 2100), (3200, 2100), (3200, 2200), (0, 2200)],
                [(0, 0), (100, 0), (100, 2200), (0, 2200)], [(3100, 0), (3200, 0), (3200, 2200), (3100, 2200)]):
        ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-WALL"})
    ms.add_arc((500, 100), 800, 0, 90, dxfattribs={"layer": "A-DOOR"})
    ms.add_text("BATHROOM", dxfattribs={"layer": "A-AREA-IDEN", "insert": (1000, 1000), "height": 100})
    return doc, ms


def test_room_from_closed_walls_has_exact_area():
    _, ms = _doc()
    from shapely.geometry import Polygon
    rooms = dxf_generic.derive_rooms(ms, 0.001)
    assert len(rooms) == 1
    assert abs(Polygon(rooms[0]).area * 1e-6 - 6.0) < 0.05  # 3.0 m x 2.0 m


def test_door_from_swing_arc_and_label_without_fixtures():
    _, ms = _doc()
    doors, windows = dxf_generic.openings(ms, 0.001)
    assert len(doors) == 1 and windows == []
    assert [t[0] for t in dxf_generic.room_labels(ms)] == ["BATHROOM"]


def test_inch_dxf_areas_and_door_leaf_use_insunits():
    """F-IMPERIAL: a DXF in inches ($INSUNITS=1) measures in metres via 0.0254, never as 1 unit = 1 m."""
    from shapely.geometry import Polygon

    from pipeline.scale_provenance import dxf_units
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 1
    for name in ("A-WALL", "A-DOOR"):
        doc.layers.add(name)
    ms = doc.modelspace()
    # 10 ft x 8 ft room (120 x 96 in) inside 4 in walls
    for pts in ([(0, 0), (128, 0), (128, 4), (0, 4)], [(0, 100), (128, 100), (128, 104), (0, 104)],
                [(0, 0), (4, 0), (4, 104), (0, 104)], [(124, 0), (128, 0), (128, 104), (124, 104)]):
        ms.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-WALL"})
    ms.add_arc((20, 4), 32, 0, 90, dxfattribs={"layer": "A-DOOR"})
    unit_m = dxf_units(doc, "t")["m_per_unit"]
    assert unit_m == 0.0254
    rooms = dxf_generic.derive_rooms(ms, unit_m)
    assert len(rooms) == 1
    assert abs(Polygon(rooms[0]).area * unit_m ** 2 - 120 * 96 * 0.0254 ** 2) < 0.05   # 7.43 m2, not 11520
    doors, _ = dxf_generic.openings(ms, unit_m)
    assert abs(doors[0]["leaf_len"] * unit_m - 32 * 0.0254) < 1e-6   # 0.81 m measured, not an assumed 0.9 m
