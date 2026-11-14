"""F-PERF: request isolation, evidence snapshots, and paid streaming explanations."""
import copy
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from engine.reader.cache import document_scope
from engine.solvers import data


@pytest.fixture
def model(tmp_path):
    folder = tmp_path / "uploaded-model"
    folder.mkdir()
    (folder / "doc.json").write_text(json.dumps({"kind": "ifc", "pages": 1}))
    elements = [{"item_id": str(i), "kind": "door", "name": "Door", "ifc_class": "IfcDoor"} for i in range(3)]
    (folder / "elements.json").write_text(json.dumps({"elements": elements}))
    return folder.name, tmp_path


def test_answer_cache_parses_once_across_threads_and_releases(model, monkeypatch):
    did, root = model
    reads = []
    read = data._json
    monkeypatch.setattr(data, "_json", lambda path: (reads.append(path.name), read(path))[1])

    @document_scope
    def question():
        first = data.load_doc(did, root)
        with ThreadPoolExecutor(1) as worker:
            other = worker.submit(copy_context().run, data.load_doc, did, root).result()
        assert first is other
        assert data.load_doc(did, root) is first
        first.items.clear()  # must never escape into another chat
    question()
    assert reads.count("elements.json") == 1
    assert len(data.load_doc(did, root).items) == 3
    assert reads.count("elements.json") == 2


def test_fresh_question_sees_ingestion_and_new_pages(model):
    did, root = model
    @document_scope
    def query(prefer=None):
        return data.load_doc(did, root, prefer)
    assert len(query().items) == 3
    (root / did / "elements.json").write_text(json.dumps({"elements": []}))
    assert query().items == []
    (root / did / "planmap-1.json").write_text(json.dumps({"page": 1, "items": [
        {"item_id": "x", "kind": "wall", "props": {}}]}))
    assert query("planmap").items[0].kind == "wall"
    assert query().mode == "ifc"


def test_cache_bound_and_roots_are_independent(model, monkeypatch, tmp_path):
    did, root = model
    from engine.reader.cache import DocumentCache
    monkeypatch.setenv("DOCUMENT_CACHE_BYTES", "1")
    cache = DocumentCache()
    cache.load(data.load_doc.__wrapped__, did, root, None)
    assert not cache.entries
    monkeypatch.setenv("DOCUMENT_CACHE_BYTES", "invalid")
    assert DocumentCache().limit > 0
    @document_scope
    def query():
        assert data.load_doc(did, root) is not None
        assert data.load_doc(did, root / "other") is None
    query()


def test_whole_answer_reuses_model_for_solver_guard_and_reasoning(model, monkeypatch):
    from engine.answer import answer
    from engine import sheetqa
    did, root = model
    monkeypatch.setenv("ARTIFACTS_DIR", str(root))
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setattr(sheetqa, "is_sheet", lambda *a: pytest.fail("IFC previews must not run sheet OCR"))
    reads = []
    read = data._json
    monkeypatch.setattr(data, "_json", lambda path: (reads.append(path.name), read(path))[1])
    res = answer("How many doors are in this model?", [did])
    assert res["answer"]["value"] == 3 and res["reasoning"]
    assert reads.count("elements.json") == 1


def test_png_dimensions_read_only_the_header(tmp_path, monkeypatch):
    import struct
    from pathlib import Path
    from engine.reader.text import png_size
    image = tmp_path / "drawing.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 12000, 8000) + b"\0" * 100000)
    monkeypatch.setattr(Path, "read_bytes", lambda p: pytest.fail("must not read the full drawing"))
    assert png_size(image) == (12000, 8000)


def test_explanation_number_guard_compares_values_not_substrings_or_citations():
    from engine.explain import _ok
    assert _ok("There are 3 doors. [1]", "**3 doors** are in the model. [1]")
    assert not _ok("**3 doors** [1]", "**13 doors** are in the model. [1][3]")


def test_reader_publishes_each_observation_before_final_with_citations(model, monkeypatch):
    from engine.reader.agent import read_answer
    import engine.models as M
    did, root = model
    replies = iter([
        {"action": "tool", "tool": "ifc", "args": {"doc": "d1", "kind": "door"}},
        {"action": "tool", "tool": "compute", "args": {"expr": "3+2"}},
        {"action": "final", "answer": "**3 doors**. [1]", "value": 3, "unit": "count", "confidence": .9, "evidence": ["e1"]},
    ])
    monkeypatch.setattr(M, "call", lambda *a, **kw: SimpleNamespace(json=next(replies), text="", provider="fake", model="test", cost_usd=.001))
    events = []
    res = read_answer("Count the doors", [did], root, on_event=lambda k, p: events.append((k, p)))
    partials = [p for k, p in events if k == "answer.partial"]
    from server.schema import validate_answer
    for p in partials:
        validate_answer(p)
    assert len(partials) == 2
    assert all("so far" in p["answer"]["text_md"] and p["answer"]["value"] is None for p in partials)
    assert partials[0]["citations"][0]["item_ids"] == ["0", "1", "2"]
    assert partials[0]["cost"]["usd_total"] == .001
    assert partials[1]["cost"]["usd_total"] == .002
    assert res["cost"]["usd_total"] == .003
    assert any(k == "status" and "doors" in p["text"] for k, p in events)


@pytest.mark.parametrize("text,accepted", [("**3 doors** are in the model. [1]", True),
                                         ("**4 doors** are in the model. [1]", False),
                                         ("**13 doors** are in the model. [1]", False),
                                         ("**4 doors** are in the model. [1][3]", False)])
def test_paid_explanation_stream_cost_reaches_answer_even_if_rejected(tmp_path, monkeypatch, text, accepted):
    from engine.explain import explain
    from engine.models import core, providers as P
    import engine.models as M
    from engine.tests.test_stream import FakeStream
    monkeypatch.setenv("MODELS_FAKE", "0")
    monkeypatch.setenv("EXPLAIN", "1")
    monkeypatch.setenv("MODELS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MODELS_COSTS_LOG", str(tmp_path / "costs.jsonl"))
    monkeypatch.setattr(core, "_forced_fake", lambda: False)
    monkeypatch.setattr(core, "api_key", lambda p: "test-key")
    monkeypatch.setattr(core, "chain_for", lambda t: [{"provider": "runware_claude", "model": "claude-sonnet-5-5"}])
    monkeypatch.setattr(core, "_check_budget", lambda p: None)
    M.set_db_logger(None)
    events = [
        {"type": "message_start", "message": {"usage": {"output_tokens": 1}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        {"type": "message_delta", "usage": {"input_tokens": 1000, "output_tokens": 20}},
    ]
    monkeypatch.setattr(P.httpx, "stream", lambda *a, **kw: FakeStream(events))
    original = {"answer": {"text_md": "**3 doors** are in the model. [1]", "abstained": False},
                "citations": [{"n": 1, "doc_id": "missing", "item_ids": []}], "route": "index", "trace": [],
                "cost": {"usd_total": .001, "calls": [{"cost_usd": .001}]}}
    seen = []
    res = explain(copy.deepcopy(original), "Count doors", tmp_path, on_event=lambda k, p: seen.append((k, p)))
    assert res["cost"]["usd_total"] == pytest.approx(.0032)
    assert res["cost"]["calls"][-1]["cost_usd"] == pytest.approx(.0022)
    assert res["answer"]["text_md"] == (text if accepted else original["answer"]["text_md"])
    assert bool(seen) is accepted
    assert P.DELTA_SINK.get() is None
    log = json.loads((tmp_path / "costs.jsonl").read_text())
    assert log["input_tokens"] == 1000 and log["output_tokens"] == 20
    assert log["cost_usd"] == pytest.approx(.0022)
    cached = explain(copy.deepcopy(original), "Count doors", tmp_path)
    assert cached["cost"]["usd_total"] == .001
