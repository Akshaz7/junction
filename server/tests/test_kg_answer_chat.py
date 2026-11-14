"""The project hook chooses graph answers before any model or broad library route."""
from pathlib import Path

from server import chats_routes


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
