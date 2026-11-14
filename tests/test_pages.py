import json
from pathlib import Path

from PIL import Image

from pipeline.fixtures import load_fixtures

ART = Path(__file__).resolve().parent.parent / "artifacts"


def test_fixtures_have_page1():
    for d in load_fixtures():
        if d["kind"] == "ifc":
            continue  # IFC pages come from D-07 storey plans
        p = ART / d["doc_id"] / "page-1.png"
        assert p.exists(), d["doc_id"]
        assert (ART / d["doc_id"] / "page-1.thumb.png").exists()
        assert min(Image.open(p).size) > 100


def test_vector_pdf_words_have_boxes():
    n = 0
    for d in load_fixtures():
        if "pdf" in d["formats"]:
            t = json.loads((ART / d["doc_id"] / "text-1.json").read_text())
            W, H = t["image"]["w"], t["image"]["h"]
            assert t["words"]
            for w in t["words"]:
                x0, y0, x1, y1 = w["bbox_px"]
                assert 0 <= x0 <= x1 <= W and 0 <= y0 <= y1 <= H and w["text"]
            n += 1
    assert n >= 4
