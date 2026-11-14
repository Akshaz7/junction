"""Read-only source and direction checks for the real pairs recorded by F-CHANGES.

These checks validate source identities and comparison invariants, not manually
labelled ground truth. No source artifact is modified and no model is called.
"""
import json
from pathlib import Path

import pytest

from engine.revision_compare import compare_documents

REPO = Path(__file__).resolve().parents[2]
REPORT = REPO / "results/final/CHANGES/pairs.json"
PAIRS = json.loads(REPORT.read_text()).get("pairs", []) if REPORT.is_file() else []


@pytest.mark.parametrize("pair", PAIRS, ids=[p["name"] for p in PAIRS])
def test_real_revision_sources_and_reverse_direction(pair):
    root = REPO / "artifacts"
    a, b = pair["doc_a"], pair["doc_b"]
    if not all((root / doc / "elements.json").is_file() for doc in (a, b)):
        pytest.skip("real IFC indexes unavailable")
    result = compare_documents(a, b, root)
    reverse = compare_documents(b, a, root)
    assert result["status"] != "unavailable"
    assert result["summary"] == pair["summary"]
    assert result["summary"]["added"] == reverse["summary"]["removed"]
    assert result["summary"]["removed"] == reverse["summary"]["added"]
    for kind in ("moved", "resized", "property_changed"):
        assert result["summary"][kind] == reverse["summary"][kind]
    inventories = {}
    for doc in (a, b):
        data = json.loads((root / doc / "elements.json").read_text())
        inventories[doc] = {item["item_id"] for item in data["elements"]}
        unchanged = compare_documents(doc, doc, root)
        assert unchanged["summary"]["total"] == 0
    for change in result["changes"]:
        assert [c["doc_id"] for c in change["citations"]] == [a, b]
        for side, doc, citation in zip(("v1", "v2"), (a, b), change["citations"]):
            source = change[side]
            if source is not None:
                assert source["doc_id"] == doc
                assert source["item_id"] in inventories[doc]
                assert citation["item_ids"] == [source["item_id"]]
            else:
                assert citation["item_ids"] == []
