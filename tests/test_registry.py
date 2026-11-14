import json
from pathlib import Path

from pipeline.registry import doc_id_for_question_path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "data" / "junction-dataset-preview"
ART = REPO / "artifacts"


def _docs():
    return {json.loads(l)["doc_id"]: json.loads(l) for l in open(ART / "registry.jsonl")}


def test_every_file_maps_to_doc():
    docs = _docs()
    mapped = {v for d in docs.values() for v in d["files"].values()}
    files = {p.relative_to(ROOT).as_posix() for p in (ROOT / "data").rglob("*")
             if p.is_file() and p.name != "LICENSE.md"}
    assert files <= mapped, sorted(files - mapped)[:5]
    for d in docs.values():
        assert (ART / d["doc_id"] / "doc.json").exists()
        for k in ("doc_id", "source", "formats", "kind", "title", "pages", "licence", "credit", "heldout"):
            assert k in d


def test_questions_map_to_docs():
    docs = _docs()
    for l in open(ROOT / "questions.jsonl"):
        assert doc_id_for_question_path(json.loads(l)["path"]) in docs


def test_ac20_licence_and_missing_credits():
    d = _docs()["ifc_bench__ac20-arc"]
    assert "KIT" in d["licence"]
    listed = set((REPO / "results" / "missing_credits.txt").read_text().split())
    assert listed == {k for k, v in _docs().items() if not v["credit"]}
