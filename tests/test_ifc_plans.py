import json
from pathlib import Path

ART = Path(__file__).resolve().parent.parent / "artifacts" / "ifc_bench__ac20-arc"


def test_erdgeschoss_plan():
    pages = json.loads((ART / "pages.json").read_text())["pages"]
    n = next(p["page"] for p in pages if p["storey"] == "Erdgeschoss")
    pm = json.loads((ART / f"planmap-{n}.json").read_text())
    rooms = [i for i in pm["items"] if i["kind"] == "room"]
    assert len(rooms) == 18
    W, H = pm["image"]["w"], pm["image"]["h"]
    assert (ART / f"page-{n}.png").exists()
    for it in pm["items"]:
        x0, y0, x1, y1 = it["bbox_px"]
        assert 0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H, it["item_id"]
    els = {e["item_id"] for e in json.loads((ART / "elements.json").read_text())["elements"]}
    assert all(i["item_id"] in els for i in pm["items"])
