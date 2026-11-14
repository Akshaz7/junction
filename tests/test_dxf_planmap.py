import json
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

def _fixture_ids():
    raw = json.loads((ROOT / "tests/fixtures.json").read_text())
    ids = raw if isinstance(raw, list) else raw.get("fixtures", raw.get("doc_ids", []))
    ids = [i["doc_id"] if isinstance(i, dict) else i for i in ids]
    return [i for i in ids if i.startswith("swiss_dwellings__")]


def _answers(doc_id):
    out = {}
    for line in (ROOT / "data/sets/questions_en.jsonl").read_text().splitlines():
        q = json.loads(line)
        if q.get("doc_id") != doc_id or q.get("unit") != "count":
            continue
        t = q["question"]
        m = re.match(r"How many rooms labelled '(.+)' are there", t)
        if m:
            out[("room", m.group(1))] = int(float(q["answer"]))
        elif t.startswith("How many apartments"):
            out[("unit", None)] = int(float(q["answer"]))
        elif t.startswith("How many doors"):
            out[("door", None)] = int(float(q["answer"]))
        elif t.startswith("How many windows"):
            out[("window", None)] = int(float(q["answer"]))
    return out


@pytest.mark.parametrize("doc_id", _fixture_ids())
def test_counts_match_questions(doc_id):
    pm = json.loads((ROOT / "artifacts" / doc_id / "planmap-1.json").read_text())
    items = pm["items"]
    rooms = Counter(i["label"] for i in items if i["kind"] == "room" and i["label"])
    got = {("unit", None): sum(1 for i in items if i["props"].get("role") == "unit"),
           ("door", None): sum(1 for i in items if i["kind"] == "door"),
           ("window", None): sum(1 for i in items if i["kind"] == "window")}
    ans = _answers(doc_id)
    assert ans, "no count questions for fixture"
    checked = 0
    for k, v in ans.items():
        have = rooms.get(k[1], 0) if k[0] == "room" else got[k]
        assert have == v, (doc_id, k, have, v)
        checked += 1
    assert checked >= 4
    assert pm["registration"]["rms_px"] < 3
    assert 0 < pm["scale"]["m_per_px"] < 0.1
