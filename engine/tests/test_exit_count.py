import re
from pathlib import Path

import pytest

from engine import advisor, findings
from engine.solvers.data import load_doc

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_models__bsc-duplex-duplex-a-20110907"
pytestmark = pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")


def test_exits_map_lists_each_element_once():
    doc = load_doc(DOC, ROOT)
    for items in findings.exits_map(doc).values():
        ids = [i.item_id for i in items]
        assert len(ids) == len(set(ids))


def test_remaining_exits_never_exceed_doors_on_the_storey():
    doc = load_doc(DOC, ROOT)
    for st, items in findings.exits_map(doc).items():
        doors = {i.item_id for i in doc.items if i.kind == "door" and i.storey == st}
        for d in [i for i in items if i.kind == "door"][:1]:
            cards = advisor.advise(DOC, {"op": "hide", "item_ids": [d.item_id]})
            for c in cards:
                m = re.search(r"leaves (\d+) other exit", c["body"])
                if m:
                    assert int(m.group(1)) <= len(doors) - 1
