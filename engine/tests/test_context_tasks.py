"""Thread memory (engine/context.py) and document tasks (engine/tasks): all model transport mocked, nothing live."""
import json
import struct
import zlib

import pytest

from engine import context as C
from engine import project_index as PI
from engine.answer import answer
from engine.models import Result
from engine.tasks import detect

CLAIM = ("Draft a construction claim using the available project documents. Identify documented changes, affected work, dates, and supporting "
         "citations. State where cost, delay, or entitlement evidence is missing.")
DOC = "cubicasa5k__colorful-11960"
V1, V2 = "acme__sheet-a101-v1", "acme__sheet-a101-v2"


def _png(path):
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 8 for _ in range(8))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _words(lines):
    ws = []
    for y, text in lines:
        x = 100.0
        for w in text.split():
            ws.append({"text": w, "bbox_px": [x, y, x + 10 * len(w), y + 20]})
            x += 10 * len(w) + 8
    return {"image": {"w": 2000, "h": 1500}, "page": 1, "words": ws}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("MODELS_FAKE", "1")
    PI._CACHE.clear()
    for did, title in ((V1, "A101 Floor Plan v1"), (V2, "A101 Floor Plan v2")):
        d = tmp_path / did
        d.mkdir()
        (d / "doc.json").write_text(json.dumps({"doc_id": did, "source": "acme", "title": title, "kind": "pdf", "pages": 1}))
        (d / "text-1.json").write_text(json.dumps(_words([(100, "Level 1 floor plan rev issued for construction"), (140, "Door D3 relocated per RFI 12")])))
    d = tmp_path / DOC
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"doc_id": DOC, "source": "cubicasa5k", "title": "colorful-11960", "kind": "raster", "pages": 1}))
    _png(d / "page-1.png")
    items = [{"item_id": f"{k}-{i}", "kind": k, "label": None, "bbox_px": [i * 10, 5 if k == "door" else 50, i * 10 + 8, 9 if k == "door" else 54], "polygon_px": None, "props": {}, "conf": 0.9, "source": "rule"}
             for k, n in (("window", 3), ("door", 5)) for i in range(1, n + 1)]
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": DOC, "page": 1, "image": {"w": 800, "h": 600},
                                                  "scale": {"m_per_px": 0.02, "method": "x", "confidence": 1.0}, "items": items}))
    (tmp_path / "series" / "diffs").mkdir(parents=True)
    (tmp_path / "series" / "acme-a101.json").write_text(json.dumps({"series_id": "acme-a101", "title": "A101 Floor Plan", "versions": [
        {"doc_id": V1, "date": "2019-03-11", "label": "Version 1 · 2019-03-11", "pages": 1},
        {"doc_id": V2, "date": "2019-03-12", "label": "Version 2 · 2019-03-12", "pages": 1}]}))
    (tmp_path / "series" / "diffs" / "acme-a101--1-2.json").write_text(json.dumps({"changes": [
        {"type": "changed", "kind": "region", "description": 'Text changed from "Door D3 west" to "Door D3 east".', "bbox_px_v1": [100, 140, 300, 160],
         "bbox_px_v2": [100, 140, 300, 160], "ink_px": 900, "page": 1, "page_v1": 1, "page_v2": 1, "change_id": "c1"}]}))
    PI.upsert_doc(V1, tmp_path)
    PI.upsert_doc(V2, tmp_path)
    PI.upsert_doc(DOC, tmp_path)
    return tmp_path


class Mock:
    def __init__(self):
        self.calls = []

    def __call__(self, task, messages, images=None, schema=None, **kw):
        self.calls.append({"task": task, "messages": messages, "images": images, "schema": schema})
        last = messages[-1]["content"] if isinstance(messages, list) else str(messages)
        if task == "context_rewrite":
            if "this one" in last.split("Latest message:")[-1]:
                return Result(text="", json={"question": CLAIM.rstrip(".") + f" Focus on the document colorful-11960.", "doc": "current"}, provider="mock", model="haiku", cost_usd=0.0002)
            return Result(text="", json={"question": "How many doors are there?", "doc": "last"}, provider="mock", model="haiku", cost_usd=0.0002)
        if task == "task_write":
            return Result(text="Draft generated for review: not legal advice.\n\n## Documented changes\n- Door D3 text changed between issues on 2019-03-11 and 2019-03-12 [1].\n"
                               "- The sheet notes door D3 relocated per RFI 12 [2].\n\n## Evidence gaps\n- No cost evidence was found.", provider="mock", model="opus", cost_usd=0.05)
        if task == "forced_answer":
            return Result(text="", json={"answer": "The walls look like masonry."}, provider="mock", model="flash", cost_usd=0.0001)
        raise RuntimeError(f"unexpected task {task}")


@pytest.fixture()
def mock(monkeypatch):
    m = Mock()
    monkeypatch.setattr("engine.models.call", m)
    return m


def test_detect_starters():
    assert detect(CLAIM) == "claim"
    assert detect("Prepare a construction coordination meeting agenda from the project documents.") == "meeting"
    assert detect("Plan the next construction work phase from the project documents.") == "phase"
    assert detect("Review the available construction contract documents for scope.") == "contract"
    assert detect("How many doors are there?") is None


def test_standalone_questions_skip_the_rewrite():
    h = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert not C.needs_rewrite("How many windows are on level 2 of the north block?", [], h)
    assert not C.needs_rewrite("anything", [], [])
    assert C.needs_rewrite("this one", [DOC], h) and C.needs_rewrite("and doors?", [], h) and C.needs_rewrite("and on level 2?", [], h)


def test_claim_without_document_is_a_cited_draft_not_a_refusal(root, mock):
    a = answer(CLAIM, [])
    assert not a["answer"]["abstained"] and a["route"] == "hybrid" and "cannot answer" not in a["answer"]["text_md"]
    assert a["citations"] and "[1]" in a["answer"]["text_md"]
    assert any("Door D3" in c["quote"] for c in a["citations"]) and any(c.get("change_id", "").startswith("ser:acme-a101:1#") for c in a["citations"])
    assert [c["task"] for c in mock.calls] == ["task_write"]
    from server.schema import validate_answer
    validate_answer(a)


def test_this_one_with_attached_doc_continues_the_claim(root, mock):
    hist = [{"role": "user", "content": CLAIM}, {"role": "assistant", "content": "I searched 25 project documents ... cannot answer."}]
    a = answer("this one", [DOC], history=hist)
    assert [c["task"] for c in mock.calls][:2] == ["context_rewrite", "task_write"]
    assert a["trace"][0]["step"] == "context" and "Focus on the document colorful-11960" in a["trace"][0]["detail"]
    assert a["doc_ids"] == [DOC] and a["route"] == "hybrid" and a["citations"]
    tw = mock.calls[1]
    assert tw["images"] and str(tw["images"][0]).endswith("page-1.png")           # the drawing itself goes to the writer
    assert "colorful-11960" in tw["messages"][-1]["content"] and "window" in tw["messages"][-1]["content"]   # plan-map facts


def test_claim_on_doc_with_revisions_lists_changes(root, mock):
    a = answer(CLAIM, [V2])
    ev_block = mock.calls[0]["messages"][-1]["content"]
    assert "2019-03-11" in ev_block and "2019-03-12" in ev_block and "Door D3" in ev_block
    assert a["citations"][0]["doc_id"] in (V1, V2) and a["evidence"]["boxes"]


def test_followup_doors_uses_last_document(root, mock):
    hist = [{"role": "user", "content": "how many windows"}, {"role": "assistant", "content": "There are **3 windows**.", "doc_ids": [DOC]}]
    a = answer("and doors?", [], history=hist)
    assert a["answer"]["value"] == 5 and a["doc_ids"] == [DOC]
    assert a["trace"][0]["step"] == "context" and "doors" in a["trace"][0]["detail"].lower()


def test_rewrite_falls_back_to_a_rule_when_models_fail(root, monkeypatch):
    monkeypatch.setattr("engine.models.call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    r = C.resolve("this one", [DOC], [{"role": "user", "content": CLAIM}, {"role": "assistant", "content": "no"}], root)
    assert r.rewritten and CLAIM[:30] in r.question and "colorful-11960" in r.question and r.doc_ids == [DOC]


def test_task_template_when_the_writer_is_down(root, monkeypatch):
    def call(task, *a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr("engine.models.call", call)
    a = answer(CLAIM, [])
    assert a["citations"] and "[1]" in a["answer"]["text_md"] and "Evidence gaps" in a["answer"]["text_md"]


def test_attached_drawing_is_read_before_missing_materials_abstain(root, mock):
    a = answer("What materials are used in the walls?", [DOC])
    reads = [c for c in mock.calls if c["task"] == "read_drawing"]
    assert reads and reads[0]["images"] and str(reads[0]["images"][0]).endswith("page-1.png")
    assert not any(c["task"] == "forced_answer" for c in mock.calls)
    assert a["answer"]["abstained"] and a["answer"]["value"] is None


def test_progress_block_only_states_what_ran():
    from engine.tasks import _progress
    from engine.tasks.evidence import Evidence
    ev = Evidence(); ev.docs_searched = 25; ev.scope = "AC20: not part of a version series"; ev.gaps = ["a", "b"]
    ev.add(doc_id="d", page=1, kind="text", title="t", text="x")
    t = _progress("meeting", ev, 3.2)
    assert "1 evidence item(s) from 25 document(s)" in t and "Evidence gaps noted: 2." in t and "Drafting the agenda… 3 s" in t
    assert "exit" not in t.lower()
