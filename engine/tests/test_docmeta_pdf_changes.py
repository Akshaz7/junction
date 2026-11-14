"""D-13/D-14: folder metadata, series lookup, and the PDF revision diff on a synthetic shifted image pair."""
import json

import numpy as np
import pytest

from engine import docmeta


def test_derive_opening_design_and_ifc():
    rec = {"doc_id": "opening_design__x", "source": "opening_design", "title": "t", "kind": "pdf",
           "files": {"pdf": "data/opening_design/Sports Complex/20190612 Issue/P105 Plumbing Plan.pdf"}}
    m = docmeta.derive(rec)
    assert m["project"] == "Sports Complex" and m["date"] == "2019-06-12" and m["sheet"] == "P105"
    assert m["folder_path"] == ["Sports Complex", "MEP", "Plumbing"] and m["folder"] == "Sports Complex/MEP/Plumbing"
    ifc = docmeta.derive({"doc_id": "ifc_bench__ac20-str", "source": "ifc_bench", "files": {}})
    assert ifc["discipline"] == "Structural"
    t = docmeta.folder_tree([m, ifc])
    assert t["total"] == 2 and {f["name"] for f in t["folders"]} == {"Sports Complex", "Ac20"}


def test_series_lookup(tmp_path):
    (tmp_path / "series").mkdir()
    (tmp_path / "series" / "s.json").write_text(json.dumps({"series_id": "s", "title": "T", "versions": [
        {"doc_id": "a", "date": "2019-01-01", "label": "V1"}, {"doc_id": "b", "date": "2019-02-01", "label": "V2"}]}))
    assert docmeta.latest_version("a", tmp_path) == "b" and docmeta.latest_version("zzz", tmp_path) == "zzz"
    assert docmeta.series_of("a", tmp_path)["count"] == 2 and docmeta.older_versions("b", tmp_path)[0]["doc_id"] == "a"


def test_diff_page_finds_added_box_and_shift():
    from engine import pdf_changes
    rng = np.random.default_rng(0)
    a = np.full((600, 800), 255, np.uint8)
    for y in (100, 200, 300):
        a[y:y + 3, 50:700] = 0
    a[400:420, 100:300] = rng.integers(0, 60, (20, 200))
    b = a.copy()
    b[500:540, 500:640] = 0  # added block
    ch, info = pdf_changes.diff_page(a, b, [], [])
    assert len(ch) >= 1
    box = ch[0]["bbox_px_v2"]
    assert box[0] <= 520 and box[2] >= 620 and box[1] <= 510 and box[3] >= 530
    assert ch[0]["type"] == "added" and ch[0]["bbox_px_v1"] is None
    same, _ = pdf_changes.diff_page(a, a.copy(), [], [])
    assert same == []
    shifted = np.roll(a, (3, 4), axis=(0, 1))
    none, _ = pdf_changes.diff_page(a, shifted, [], [])
    assert none == []
