from engine.solvers.data import Doc, Item
from engine.wall_runs import answer, item_runs, wants_wall_runs
import json


def test_intent():
    assert wants_wall_runs("what is the length of the longest wall?") == "longest"
    assert wants_wall_runs("total wall length") == "total"
    assert wants_wall_runs("wall surface area") is None
    assert wants_wall_runs("how many walls are there") is None
    assert wants_wall_runs("what is the shortest wall") is None


def _wall(iid, pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return Item(iid, "wall", bbox_px=[min(xs), min(ys), max(xs), max(ys)], polygon_px=pts)


def test_l_network_splits_into_runs():
    # L-shaped outline, 0.1 m thick at 0.01 m/px: legs 5.0 m and 3.0 m
    pts = [[0, 0], [500, 0], [500, 10], [10, 10], [10, 300], [0, 300]]
    r = item_runs(_wall("w", pts), 0.01)
    assert r["method"] == "wall network outline"
    assert abs(max(x[0] for x in r["runs"]) - 5.0) < 0.1 and abs(max(x[0] for x in r["runs"]) - 5.0) >= 0
    assert abs(r["total_m"] - (2 * 500 + 2 * 300) * 0.01 / 2) < 0.2


def test_rectangle(tmp_path):
    r = item_runs(_wall("w", [[0, 0], [400, 0], [400, 10], [0, 10]]), 0.01)
    assert r["method"] == "rectangular outline" and abs(r["runs"][0][0] - 4.0) < 1e-6


def _write(tmp_path, scale):
    d = tmp_path / "doc1"
    d.mkdir()
    walls = [{"item_id": "wall-1", "kind": "wall", "bbox_px": [0, 0, 500, 300],
              "polygon_px": [[0, 0], [500, 0], [500, 10], [10, 10], [10, 300], [0, 300]], "props": {}, "conf": 0.9, "source": "seg"},
             {"item_id": "wall-2", "kind": "wall", "bbox_px": [100, 100, 300, 110],
              "polygon_px": [[100, 100], [300, 100], [300, 110], [100, 110]], "props": {}, "conf": 0.9, "source": "seg"}]
    doors = [{"item_id": f"door-{i}", "kind": "door", "bbox_px": [0, 0, 90, 5], "props": {}, "conf": 0.9, "source": "det"} for i in range(3)]
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": "doc1", "page": 1, "image": {"w": 600, "h": 400}, "scale": scale,
                                                  "items": walls + doors, "provenance": {}}))
    (d / "doc.json").write_text(json.dumps({"doc_id": "doc1", "kind": "raster"}))
    return tmp_path


def test_longest_estimate_with_door_scale(tmp_path):
    root = _write(tmp_path, {"m_per_px": 0.01, "method": "door-prior", "confidence": 0.3, "evidence": "x"})
    r = answer("what is the length of the longest wall?", ["doc1"], root)
    assert "(estimate)" in r["answer"]["text_md"] and "door widths" in r["answer"]["text_md"]
    assert abs(r["answer"]["value"] - 5.0) < 0.1 and not r["answer"]["abstained"]
    assert r["evidence"]["scene"]["highlight_item_ids"] == ["wall-1"]
    assert r["citations"][0]["bbox_px"] is not None
    t = answer("what is the total wall length", ["doc1"], root)
    assert abs(t["answer"]["value"] - 10.0) < 0.1   # L network (2*500+2*300)/2*0.01 = 8.0 plus the 2.0 m rectangle


def test_no_scale_abstains(tmp_path):
    root = _write(tmp_path, {"method": "none", "confidence": 0.0})
    r = answer("longest wall length", ["doc1"], root)
    assert r is None or r["answer"]["abstained"] or "scale" in r["answer"]["text_md"]


def test_phrasings():
    for q in ["longest wall", "What is the longest wall?", "which wall is longest?", "what is the biggest wall", "largest wall",
              "how long is the longest wall?"]:
        assert wants_wall_runs(q) == "longest", q
    for q in ["wall lengths", "how long are the walls?", "total length of walls", "total wall length"]:
        assert wants_wall_runs(q) == "total", q
    for q in ["how many walls are there", "largest wall area", "what is the wall thickness"]:
        assert wants_wall_runs(q) is None, q


def test_ifc_longest_with_ties(monkeypatch):
    import engine.solvers.data as data
    items = [Item("a", "wall", name="W1", storey="L1", q={"length_m": 41.7}),
             Item("b", "wall", name="W2", storey="L2", q={"length_m": 41.7}),
             Item("c", "wall", name="W3", storey="L1", q={"length_m": 5.0}),
             Item("d", "wall", name="W4", storey="L1", q={})]
    doc = Doc("x", "ifc", items, storeys=[{"name": "L1"}, {"name": "L2"}])
    monkeypatch.setattr(data, "load_doc", lambda *a, **k: doc)
    r = answer("What is the longest wall?", ["x"], ".")
    assert r["answer"]["value"] == 41.7 and r["answer"]["unit"] == "m" and r["answer"]["abstained"] is False
    assert set(r["evidence"]["scene"]["highlight_item_ids"]) == {"a", "b"} and "2 walls share" in r["answer"]["text_md"]
    assert answer("total length of walls", ["x"], ".") is None      # existing quantity handlers own IFC totals
    assert answer("longest exterior wall", ["x"], ".") is None
