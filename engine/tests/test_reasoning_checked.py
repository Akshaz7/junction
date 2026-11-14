from engine.reasoning_parts import checked
from engine.solvers.data import Doc, Item


def _ctx(doc, rooms, unit="m2", trace=None, is_ifc=False, steps=None):
    return dict(res={}, question="", ans={}, cites=[], route="planmap", trace=trace or [], unit=unit, value=None, doc=doc,
                items={}, cited=rooms, first_cite={}, models_used=False, is_ifc=is_ifc, sc=doc.scale, scale_w="", scale_c=1,
                from_cad=False, steps=steps if steps is not None else [], checked=None, area_q=True, rooms=rooms)


def _raster(label_text, mpp=0.1):
    poly = [[0, 0], [100, 0], [100, 100], [0, 100]]   # 10000 px² -> 100 m² at 0.1
    room = Item("r1", "room", label="Kitchen", polygon_px=poly)
    txt = Item("t1", "text", label=label_text, bbox_px=[40, 40, 60, 50])
    far = Item("t2", "text", label="9.99 m²", bbox_px=[300, 300, 320, 310])
    return Doc("d", "planmap", [room, txt, far], scale={"m_per_px": mpp}), room


def test_raster_printed_label_agrees():
    doc, room = _raster("100,0 m²")
    c = _ctx(doc, [room]); checked.run(c)
    assert c["checked"] is True and "matches within" in c["steps"][-1]["text"]


def test_raster_printed_label_differs():
    doc, room = _raster("60 m²")
    c = _ctx(doc, [room]); checked.run(c)
    assert c["checked"] is False and "apart" in c["steps"][-1]["text"]


def test_no_label_no_step():
    doc, room = _raster("hello")
    c = _ctx(doc, [room]); checked.run(c)
    assert c["checked"] is None and c["steps"] == []


def test_recount_and_dedupe():
    doc, room = _raster("hello")
    old = [{"kind": "checked", "text": "old"}]
    c = _ctx(doc, [room], unit="", trace=[{"detail": "plan map 11, drawing re-read 12"}], steps=old); checked.run(c)
    assert len(c["steps"]) == 1 and "counted 12" in c["steps"][0]["text"] and c["checked"] is False


def test_ifc_footprint():
    r = Item("r", "room", q={"area_m2": 23.9}, bbox_m=[[0, 0, 0], [5.6, 2.7, 4.4]])
    doc = Doc("d", "ifc", [r])
    c = _ctx(doc, [r], is_ifc=True); checked.run(c)
    assert c["checked"] is True
