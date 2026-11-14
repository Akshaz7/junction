import copy
import time

from server import chats_routes, stub_engine
from server.answer_progress import AnswerProgress, NOTE, partial_deadline
from server.schema import validate_answer
from server.tests.test_contract import DOC, _sse
from server.tests.test_sse_first import stream_setup, URL, QUESTION, CHAT_ID


def test_partial_preserves_findings_citations_and_stops_scene_edits():
    source = stub_engine.answer(QUESTION, [DOC], None)
    source["evidence"]["scene"]["commands"] = [{"op": "hide", "item_ids": ["window-001"]}]
    original = copy.deepcopy(source)
    progress = AnswerProgress(QUESTION, [DOC])
    progress.update("answer.partial", source)
    ans = progress.partial()
    validate_answer(ans)
    assert source == original
    assert ans["citations"] == source["citations"] and ans["evidence"]["boxes"] == source["evidence"]["boxes"]
    assert source["answer"]["text_md"] in ans["answer"]["text_md"]
    assert NOTE in ans["answer"]["text_md"] and "Partial answer" in ans["answer"]["text_md"]
    assert ans["answer"]["value"] is None and ans["answer"]["confidence"] <= 0.5
    assert "commands" not in ans["evidence"]["scene"]


def test_partial_without_evidence_never_invents_it():
    progress = AnswerProgress(QUESTION, [DOC])
    progress.update("answer.partial", {"answer": "not a schema-valid snapshot"})
    progress.update("answer.delta", {"text": "_Reading the drawing closely…_"})
    ans = progress.partial()
    validate_answer(ans)
    assert ans["answer"]["abstained"] and ans["citations"] == []
    assert "No verified findings" in ans["answer"]["text_md"]


def test_partial_uses_streamed_text_if_snapshot_not_available():
    progress = AnswerProgress(QUESTION, [DOC])
    progress.update("answer.delta", {"text": "The sheet mentions a reinforced slab."})
    ans = progress.partial()
    assert "reinforced slab" in ans["answer"]["text_md"]
    assert ans["answer"]["abstained"] and ans["answer"]["value"] is None


def test_deadline_precedes_engine_guard(monkeypatch):
    monkeypatch.delenv("ANSWER_PARTIAL_AFTER_S", raising=False)
    monkeypatch.delenv("ANSWER_TIMEOUT_S", raising=False)
    assert partial_deadline() == 299   # Ash: no early cut-off; just before the 300 s hung-call guard
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "20")
    assert partial_deadline() == 19
    monkeypatch.setenv("ANSWER_TIMEOUT_S", "0")
    monkeypatch.setenv("ANSWER_PARTIAL_AFTER_S", "nan")
    assert partial_deadline() == 299   # Ash: no early cut-off; just before the 300 s hung-call guard


def test_slow_engine_persists_partial_and_sends_it_to_watchers(stream_setup, monkeypatch):
    client, state = stream_setup
    monkeypatch.setenv("ANSWER_PARTIAL_AFTER_S", "0.05")
    def slow_engine(q, ids, emit):
        ans = stub_engine.answer(q, ids, None)
        emit("answer.partial", ans)
        time.sleep(0.2)
        emit("answer.delta", {"text": "Late result must not leak"})
        return ans
    monkeypatch.setattr(chats_routes, "ENGINE", slow_engine)
    response = client.post(URL, json={"content": QUESTION})
    events = _sse(response.text)
    assert events[-1][0] == "answer"
    ans = events[-1][1]
    validate_answer(ans)
    assert NOTE in ans["answer"]["text_md"] and ans["citations"]
    assert state["answers"] == [ans]
    assert any(e["type"] == "chat.delta" for e in state["notifications"])
    assert state["notifications"][-1]["role"] == "assistant"
    assert CHAT_ID not in chats_routes.ACTIVE
    time.sleep(0.2)
    assert "Late result" not in str(state["notifications"])


def test_explicit_empty_selection_clears_chat_default(stream_setup, monkeypatch):
    client, state = stream_setup
    selected = []
    def engine(q, ids, emit):
        selected.extend(ids)
        return stub_engine.answer(q, ids, emit)
    monkeypatch.setattr(chats_routes, "ENGINE", engine)
    response = client.post(URL, json={"content": QUESTION, "doc_ids": []})
    assert _sse(response.text)[-1][0] == "answer" and selected == []
