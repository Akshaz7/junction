import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vision.sheet_text import read_sheet


def _sheet(tmp_path, text):
    words, x = [], 100
    for t in text.split(" "):
        words.append({"text": t, "bbox_px": [x, 100, x + len(t) * 12, 124]}); x += len(t) * 12 + 10
    words += [{"text": "A-2", "bbox_px": [6000, 4300, 6200, 4400]}, {"text": "SECOND", "bbox_px": [4700, 4310, 5100, 4390]},
              {"text": "FLOOR", "bbox_px": [5120, 4310, 5500, 4390]}, {"text": "PLAN", "bbox_px": [5520, 4310, 5800, 4390]}]
    p = tmp_path / "text-1.json"; p.write_text(json.dumps({"doc_id": "t", "page": 1, "image": {"w": 6300, "h": 4500}, "words": words})); return p


def test_stoa_style_tags(tmp_path):
    r = read_sheet(_sheet(tmp_path, "FP-1 FP-2 FP-5 CV-3 FSR-1 FSI-5 PS-24 16\"Ø 12\"Ø D16 @ 300 D13@300 12'-6\" 133'-10\" 26,562 SF SEE SHEET M-303 SCALE: 1/4\" = 1'-0\" 1:50"))
    t = r["tags"]
    assert set(t["equipment"]) >= {"FP-1", "FP-2", "FP-5", "CV-3", "FSR-1", "FSI-5", "PS-24"}
    assert r["groups"]["FP"] == ["FP-1", "FP-2", "FP-5"]
    assert set(t["pipe_size"]) == {'16"Ø', '12"Ø'}
    assert set(t["rebar"]) == {"D16 @ 300", "D13 @ 300"}
    assert {"12'-6\"", "133'-10\""} <= set(t["feet_inch"])
    assert "26,562 SF" in t["area"] and "M-303" in t["sheet_ref"]
    assert r["sheet"]["id"] == "A-2" and r["sheet"]["title"] == "SECOND FLOOR PLAN"
    assert all(len(i["bbox_px"]) == 4 for i in r["items"])
