import json
from pathlib import Path

from pipeline.langcheck import is_english

REPO = Path(__file__).resolve().parent.parent
S = REPO / "data" / "sets"


def rows(n):
    return [json.loads(l) for l in open(S / n)]


def test_sample200():
    s = rows("sample200.jsonl")
    assert len(s) == 200
    assert all(is_english(q["question"]) for q in s)
    # independent crude Finnish/Danish/German/French check
    bad = ("kuinka", "monta", "pohjapiir", "hvad", "wie viele", "combien", "quelle")
    assert not [q for q in s if any(b in q["question"].lower() for b in bad)]


def test_router_split_by_drawing():
    tr = {q["doc_id"] for q in rows("router_train.jsonl")}
    te = {q["doc_id"] for q in rows("router_test.jsonl")}
    assert tr and te and not (tr & te)


def test_heldout_flags():
    held = set((S / "heldout_docs.txt").read_text().split())
    reg = [json.loads(l) for l in open(REPO / "artifacts" / "registry.jsonl")]
    assert held
    for d in reg:
        assert d["heldout"] == (d["doc_id"] in held)
        assert json.load(open(REPO / "artifacts" / d["doc_id"] / "doc.json"))["heldout"] == d["heldout"]
    ids = (S / "cubicasa_heldout_ids.txt").read_text().split()
    assert "colorful/11397" in ids and all("/" in i for i in ids)
