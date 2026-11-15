import json

from engine.answer import answer
from engine.item_ref import resolve
from engine.reader.agent import _plain_step
from engine.solvers.data import Item


def _doc(tmp_path):
    d = tmp_path / "docA"
    d.mkdir()
    items = [{"item_id": f"door-00{n}", "kind": "door", "bbox_px": [100 * n, 100, 100 * n + 5, 140], "props": {"width_m": 0.8 + n / 100, "area_px": 50}, "conf": 0.9, "source": "det"} for n in range(1, 7)]
    items.append({"item_id": "room-001", "kind": "room", "label": "Kitchen", "bbox_px": [480, 50, 620, 300], "props": {}, "conf": 0.9, "source": "det"})
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": "docA", "page": 1, "image": {"w": 800, "h": 400}, "items": items, "scale": {"m_per_px": 0.02, "method": "ratio"}}))
    (d / "doc.json").write_text(json.dumps({"doc_id": "docA", "kind": "raster", "pages": 1}))
    return tmp_path


def test_door_label_resolves_to_the_one_door_not_to_a_count(tmp_path, monkeypatch):
    root = _doc(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(root))
    for ref in ("D5", "5", "door-005"):
        res = answer(f"Tell me about door {ref}: its size and where it is.", ["docA"])
        assert res is not None and not res["answer"]["abstained"], ref
        assert res["evidence"]["scene"]["highlight_item_ids"] == ["door-005"]
        assert abs(res["answer"]["value"] - 0.85) < 1e-9 and "0.85 m" in res["answer"]["text_md"]
        assert "inside Kitchen" in res["answer"]["text_md"]
        assert [c["item_ids"] for c in res["citations"]] == [["door-005"]] and len(res["evidence"]["boxes"]) == 1


def test_unknown_or_ambiguous_reference_falls_through():
    items = [Item(item_id="a-door-5", kind="door"), Item(item_id="b-door-5", kind="door")]
    assert resolve(items, "door", "D5") == [] or len(resolve(items, "door", "D5")) == 2
    assert resolve(items, "door", "D9") == []


def test_thinking_row_label_is_plain_not_json():
    s = _plain_step("planmap", {"doc": "d1", "kind": "door", "name": "door-005"}, "e10 (inventory; cites all 1 matching items)")
    assert s.startswith("Looked up door door-005 on the plan") and "{" not in s
