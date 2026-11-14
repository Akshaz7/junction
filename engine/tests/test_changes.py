import json
from pathlib import Path

import pytest

from engine.changes import compare

REV = Path(__file__).resolve().parents[2] / "artifacts" / "revisions"
DOCS = sorted(p.name for p in REV.iterdir() if (p / "truth_changes.json").exists()) if REV.exists() else []


@pytest.mark.skipif(not DOCS, reason="no synthetic revisions")
@pytest.mark.parametrize("doc", DOCS)
def test_every_true_change_is_found(doc):
    truth = json.loads((REV / doc / "truth_changes.json").read_text())["changes"]
    got = compare(doc, REV / doc)["changes"]
    for t in truth:
        hit = [g for g in got if g["type"] == t["type"] and g["kind"] == t["kind"] and g.get("field") == t.get("field")
               and (g.get("v1_item") == t.get("v1_item") or g.get("v2_item") == t.get("v2_item"))]
        assert hit, f"missed {t['type']} {t['kind']} {t.get('field')}"
        if t.get("field") == "label":
            assert hit[0]["old"] == t["old"] and hit[0]["new"] == t["new"]
    assert len(got) <= len(truth) + 1   # no flood of false alarms
