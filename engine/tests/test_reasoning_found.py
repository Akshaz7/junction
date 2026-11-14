from types import SimpleNamespace as NS

from engine.reasoning_parts import found
from engine.solvers.data import Doc, Item


def _ctx(items, cites, doc, **kw):
    first = {}
    for c in cites:
        for i in c.get("item_ids") or []:
            first.setdefault(i, c["n"])
    cited = [i for i in items]
    sc = doc.scale if doc else None
    base = dict(res={"doc_ids": [doc.doc_id] if doc else []}, question="", ans={}, cites=cites, route=None, trace=[], unit="", value=None,
                doc=doc, items={i.item_id: i for i in items}, cited=cited, first_cite=first, models_used=False,
                is_ifc=bool(doc and doc.mode == "ifc"), sc=sc, scale_w="", scale_c=1, from_cad=False, steps=[], checked=None, area_q=None, rooms=[])
    base.update(kw)
    return base


def _doc(mode="ifc", items=(), scale=None, title="T", pages=1):
    return Doc("d1", mode, list(items), title, scale=scale, pages=pages)


def test_single_room_named_with_storey():
    it = Item("r1", "room", label="Küche", props={"number": "2.02"}, storey="Erdgeschoss")
    ctx = _ctx([it], [{"n": 1, "item_ids": ["r1"]}], _doc("ifc", [it]))
    found.run(ctx)
    s = ctx["steps"][0]
    assert s["text"] == "Room “Küche 2.02” on Erdgeschoss in the building model (IFC)" and s["cite"] == 1


def test_many_doors_with_examples_and_no_ids():
    its = [Item(f"door-{i:03d}", "door", name=n, storey="EG") for i, n in enumerate(["Seminarraum", "Labor K5", "Flur", "Büro"])]
    ctx = _ctx(its, [{"n": 1, "item_ids": [i.item_id for i in its]}], _doc("ifc", its))
    found.run(ctx)
    t = ctx["steps"][0]["text"]
    assert t.startswith("4 doors on EG in the building model (IFC), each one numbered, including Seminarraum")
    assert "door-0" not in t and len(t) <= 110


def test_cad_and_scan_wording():
    it = Item("r", "room", label="Zimmer", source="dxf")
    ctx = _ctx([it], [{"n": 1, "item_ids": ["r"]}], _doc("planmap", [it], {"method": "dxf_units_fit"}), from_cad=True)
    found.run(ctx)
    assert "CAD drawing (DXF)" in ctx["steps"][0]["text"]
    it2 = Item("w", "window")
    ctx = _ctx([it2, Item("w2", "window")], [{"n": 1, "item_ids": ["w", "w2"]}], _doc("planmap", [it2], {"method": "door-prior"}))
    found.run(ctx)
    assert ctx["steps"][0]["text"] == "2 windows on the scanned drawing, each one numbered"


def test_text_quote_names_page():
    doc = _doc("planmap", [], {"method": "pdf_vector"}, title="Site plan", pages=3)
    ctx = _ctx([], [{"n": 1, "page": 2, "quote": "Fire rating EI 60 for all stair doors", "item_ids": []}], doc, cited=[])
    found.run(ctx)
    s = ctx["steps"][0]
    assert s["kind"] == "read" and s["text"].startswith("Printed on page 2 of Site plan: “Fire rating") and len(s["text"]) <= 110


def test_multiple_sources():
    it = Item("r", "room", label="A")
    ctx = _ctx([it], [{"n": 1, "doc_id": "a", "item_ids": ["r"]}, {"n": 2, "doc_id": "b", "item_ids": []}], _doc("ifc", [it]),
               res={"doc_ids": ["a", "b"]})
    found.run(ctx)
    assert "across 2 sources" in ctx["steps"][0]["text"]
