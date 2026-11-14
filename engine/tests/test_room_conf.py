"""Unlabelled rooms typed only by the segmentation head must be confident to count as a bedroom/kitchen/bathroom."""
import json

from engine.solvers import solve


def _room(n, rtype, conf, label=None, label_type=None):
    props = {"room_type": rtype, "area_px": 10000}
    if label_type:
        props["label_room_type"] = label_type
    return {"item_id": f"room-{n:03d}", "kind": "room", "label": label, "bbox_px": [n * 100, 0, n * 100 + 90, 90],
            "polygon_px": None, "props": props, "conf": conf, "source": "det"}


def test_weak_unlabelled_bedroom_not_counted(tmp_path):
    d = tmp_path / "doc1"
    d.mkdir()
    items = [_room(1, "bedroom", 0.95), _room(2, "bedroom", 0.6), _room(3, "bedroom", 0.6, "MH", "bedroom"), _room(4, "kitchen", 0.7)]
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": "doc1", "page": 1, "image": {"w": 1000, "h": 1000}, "items": items}))
    r = solve("How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?", "doc1", root=tmp_path)
    assert r["answer"]["value"] == 2   # confident one + the labelled one; the weak unlabelled one is left out
