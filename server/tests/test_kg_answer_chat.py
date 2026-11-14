"""The project hook chooses graph answers before any model or broad library route."""
from pathlib import Path

from server import chats_routes
from server.tests.test_projects import client  # isolated local schema + real source indexes
from server.tests.test_contract import _sse


def test_project_graph_response_keeps_confidence_and_skips_model_routes(monkeypatch):
    from engine import kg_answer
    seen = []
    result = {"trace": [{"step": "knowledge_graph"}], "answer": {"confidence": .41},
              "reasoning": {"graph_path": [{"confidence": .41}]}}
    project = {"id": "site", "docs": [{"doc_id": "one"}, {"doc_id": "two"}]}

    def forbidden(*a, **kw):
        raise AssertionError("Graph result must not go through the model/explanation path")

    def graph(q, p, root):
        assert p == project and q == "What is connected to D12?"
        assert Path(root)
        return result

    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    monkeypatch.setattr(kg_answer, "answer", graph)
    monkeypatch.setattr(chats_routes, "_selected_engine", forbidden)
    got = chats_routes._run_engine("What is connected to D12?", ["one", "two"], lambda *ev: seen.append(ev), project=project)
    assert got is result and got["answer"]["confidence"] == .41
    assert seen == [("trace", {"step": "knowledge_graph"})]


def test_explicit_file_selection_and_stub_engine_do_not_use_project_graph(monkeypatch):
    from engine import kg_answer

    def forbidden(*a, **kw):
        raise AssertionError("No project context means normal selection semantics")

    monkeypatch.setattr(kg_answer, "answer", forbidden)
    stub = lambda q, docs, events: {"selected": docs}
    monkeypatch.setattr(chats_routes, "ENGINE", stub)
    assert chats_routes._run_engine("What is connected to D12?", ["one"], lambda *ev: None) == {"selected": ["one"]}


def test_non_graph_project_question_falls_through(monkeypatch):
    from engine import kg_answer, library
    project = {"id": "site", "docs": [{"doc_id": "one"}]}
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    monkeypatch.setattr(kg_answer, "answer", lambda *a: None)
    monkeypatch.setattr(library, "library_answer", lambda *a: None)
    monkeypatch.setattr(library, "sheet_count_answer", lambda *a: None)
    monkeypatch.setattr(chats_routes, "_selected_engine", lambda *a: {"normal": True})
    assert chats_routes._run_engine("How many doors?", ["one"], lambda *ev: None, project=project) == {"normal": True}


def test_project_chat_streams_real_source_paths_and_explicit_selection_wins(client, monkeypatch):
    from engine import kg, kg_answer
    from engine.kg.build import build_uncached
    from server import stub_engine

    # Never populate the shared artifacts cache from a worker's tests.
    monkeypatch.setattr(kg, "build", build_uncached)
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    docs = ["ifc_bench__fzk-house-arc", "ifc_models__kit-fzk-haus-ac20-fzk-haus"]
    project = client.post("/api/projects", json={"name": "Graph source proof", "doc_ids": docs}).json()
    chat = client.post("/api/chats", json={"project_id": project["id"]}).json()
    for selection in ({}, {"doc_ids": []}):
        r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Where else does door Innentuer-1 appear?", **selection})
        assert r.status_code == 200
        result = next(data for event, data in _sse(r.text) if event == "answer")
        assert result["graph_answer"]["shape"] == "appearances"
        assert {c["doc_id"] for c in result["citations"]} == set(docs)
        assert result["answer"]["confidence"] == min(e["confidence"] for e in result["reasoning"]["graph_path"])
        assert result["cost"] == {"usd_total": 0, "calls": []}

    def forbidden(*a, **kw):
        raise AssertionError("Explicit file selection must bypass project graph routing")

    def selected(q, ids, on_event, **kw):
        return stub_engine.answer(q, ids, on_event)

    monkeypatch.setattr(kg_answer, "answer", forbidden)
    monkeypatch.setattr(chats_routes, "ENGINE", selected)
    monkeypatch.setattr(chats_routes, "_real_engine", selected)
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Where else does door Innentuer-1 appear?", "doc_ids": docs[:1]})
    result = next(data for event, data in _sse(r.text) if event == "answer")
    assert result["doc_ids"] == docs[:1]
