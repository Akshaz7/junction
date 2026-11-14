import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from pipeline.revisions import DOCS  # noqa: E402


@pytest.mark.parametrize("doc_id", DOCS)
def test_revision_truth_matches_planmaps(doc_id):
    rev = ROOT / "artifacts" / "revisions" / doc_id
    t = json.loads((rev / "truth_changes.json").read_text())
    p1 = json.loads((rev / "v1" / "planmap-1.json").read_text())
    p2 = json.loads((rev / "v2" / "planmap-1.json").read_text())
    assert t["generated_for_demo"] and len(t["changes"]) == 3
    assert p1["image"] == p2["image"] and (rev / "v1" / "page-1.png").exists() and (rev / "v2" / "page-1.png").exists()
    n = lambda pm, k: sum(1 for i in pm["items"] if i["kind"] == k)
    assert n(p2, "door") == n(p1, "door") + 1
    assert n(p2, "wall") == n(p1, "wall")  # -1 removed, +1 from the split
    assert n(p2, "room") == n(p1, "room")
    by1 = {i["item_id"]: i for i in p1["items"]}
    by2 = {i["item_id"]: i for i in p2["items"]}
    c = {x["change_id"]: x for x in t["changes"]}
    assert c["c1"]["v1_item"] in by1 and by1[c["c1"]["v1_item"]]["kind"] == "wall"
    assert by2[c["c2"]["v2_item"]]["kind"] == "door"
    assert by1[c["c3"]["v1_item"]]["label"] == c["c3"]["old"] != c["c3"]["new"] == by2[c["c3"]["v2_item"]]["label"]
    # the removed wall's box is empty of walls in v2
    x0, y0, x1, y1 = c["c1"]["bbox_px_v1"]
    assert not any(i["kind"] == "wall" and abs(i["bbox_px"][0] - x0) < 2 and abs(i["bbox_px"][1] - y0) < 2
                   and abs(i["bbox_px"][2] - x1) < 2 and abs(i["bbox_px"][3] - y1) < 2 for i in p2["items"])
