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
