"""S-31: mocked HTTP only; no API, database, models or network required."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


SPEC = importlib.util.spec_from_file_location("hard_cases", Path(__file__).parents[1] / "hard_cases.py")
hard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hard)


def case(case_id="first", **extra):
    return {"id": case_id, "doc_id": "ifc_bench__ac20-arc", "question": "How many doors?",
            "expect": "Count with evidence.", **extra}


def answer(**extra):
    return {"answer": {"text_md": "A" * 310, "abstained": False}, "route": "index",
            "cost": {"usd_total": 0.0012}, "latency_ms": 125,
            "evidence": {"boxes": [{"item_id": "d1"}, {"item_id": "d2"}],
                         "scene": {"highlight_item_ids": ["d1", "d2"]}}, **extra}


def stream(value):
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          text=': heartbeat\r\nevent: status\r\ndata: {}\r\n\r\n'
                          'event: trace\r\ndata: {}\r\n\r\nevent: answer\r\ndata: '
                          + json.dumps(value) + '\r\n\r\n')


def test_one_chat_per_case_followups_metrics_and_printed_report(tmp_path, capsys):
    requests = []
    chats = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/chats":
            chats.append(json.loads(request.content))
            return httpx.Response(200, json={"id": f"chat-{len(chats)}"})
        assert request.headers["accept"] == "text/event-stream"
        value = answer()
        if json.loads(request.content)["content"] == "Where are toilets?":
            value["answer"] = {"text_md": "No readable data.", "abstained": True}
            value["evidence"] = {"boxes": [], "scene": {"highlight_item_ids": []}}
        return stream(value)

    output = tmp_path / "reports/run.jsonl"
    cases = [case(followups=["and on the first floor?", "reset the model"]),
             case("second", question="Where are toilets?", doc_id="cubicasa5k__colorful-11397")]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert hard.run_cases(cases, client, "https://example.test/", output)
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    saved = [json.loads(line) for line in output.read_text().splitlines()]
    assert printed == saved
    assert len(saved) == 4
    assert [r["turn"] for r in saved] == [1, 2, 3, 1]
    assert [r["chat_id"] for r in saved] == ["chat-1"] * 3 + ["chat-2"]
    assert [r.url.path for r in requests] == ["/api/chats"] + ["/api/chats/chat-1/messages"] * 3 + [
        "/api/chats", "/api/chats/chat-2/messages"]
    assert chats == [{"doc_ids": [c["doc_id"]], "title": f"Hard case: {c['id']}"} for c in cases]
    assert [json.loads(r.content) for r in requests if r.url.path.endswith("messages")] == [
        {"content": q, "doc_ids": [c["doc_id"]]} for c in cases
        for q in [c["question"], *c.get("followups", [])]]
    assert saved[0].items() >= {
        "id": "first", "question": "How many doors?", "answer_text": "A" * 300,
        "route": "index", "cost_usd": 0.0012, "latency_s": 0.125,
        "evidence_boxes": 2, "scene_ids_count": 2, "abstained": "no",
    }.items()
    assert saved[-1]["abstained"] == "yes"
    assert saved[-1]["evidence_boxes"] == saved[-1]["scene_ids_count"] == 0


@pytest.mark.parametrize("failure", ["http", "timeout", "sse", "missing", "malformed", "metrics"])
def test_failed_turn_is_saved_and_next_case_runs(tmp_path, failure):
    messages = []

    def handler(request):
        if request.url.path == "/api/chats":
            return httpx.Response(200, json={"id": "chat"})
        messages.append(request)
        if len(messages) > 1:
            return stream(answer())
        if failure == "http":
            return httpx.Response(503)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure == "sse":
            return httpx.Response(200, text='event: error\ndata: {"detail":"engine failed"}\n\n')
        if failure == "missing":
            return httpx.Response(200, text='event: status\ndata: {}\n\n')
        if failure == "malformed":
            return httpx.Response(200, text='event: answer\ndata: {broken}\n\n')
        return stream(answer(cost={}))

    output = tmp_path / "run.jsonl"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not hard.run_cases([case(), case("second")], client, "https://example.test", output)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(messages) == 2  # No retries of potentially persisted messages/edits.
    assert rows[0]["error"]
    assert all(rows[0][key] is None for key in ("answer_text", "cost_usd", "latency_s", "abstained"))
    assert "error" not in rows[1]


def test_create_failure_records_unattempted_turns_and_continues(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(404)
        if request.url.path == "/api/chats":
            return httpx.Response(200, json={"id": "ok"})
        return stream(answer())

    output = tmp_path / "run.jsonl"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert not hard.run_cases([case(followups=["Reset"]), case("next")], client,
                                  "https://example.test", output)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 3
    assert all(row["error"].startswith("create chat:") for row in rows[:2])
    assert [r.url.path for r in requests] == ["/api/chats", "/api/chats", "/api/chats/ok/messages"]


def test_sse_multiline_data_and_final_frame_without_blank_line():
    payload = json.dumps(answer(), indent=2)
    lines = [": keepalive", "event: delta", 'data: {"text":"partial"}', "", "event: answer"]
    lines.extend(f"data: {line}" for line in payload.splitlines())
    assert hard.read_answer(iter(lines)) == answer()


@pytest.mark.parametrize("content", ["", "{broken}", "[]", json.dumps(case(followups="oops")),
                                     json.dumps(case(expect=None)), json.dumps(case(question=" ")),
                                     json.dumps(case()) + "\n" + json.dumps(case())])
def test_invalid_input_rejected_with_line_context(tmp_path, content):
    path = tmp_path / "cases.jsonl"
    path.write_text(content)
    with pytest.raises(ValueError, match=str(path)):
        hard.load_cases(path)


def test_seed_has_eight_cases_both_docs_and_requested_chains():
    cases = hard.load_cases(hard.DEFAULT_INPUT)
    assert len(cases) == 8
    assert {c["doc_id"] for c in cases} == {"ifc_bench__ac20-arc", "cubicasa5k__colorful-11397"}
    assert any(c.get("followups") == ["reset the model"] for c in cases)
    assert any(c.get("followups") == ["and on the first floor?"] for c in cases)
    assert any(c["question"].startswith("Prepare a construction coordination meeting agenda") for c in cases)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_defaults_unique_reports_and_failure_exit(tmp_path, monkeypatch, capsys, fail):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(case()))
    factory = httpx.Client
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if request.url.path == "/api/chats":
            return httpx.Response(200, json={"id": "chat"})
        return httpx.Response(503) if fail else stream(answer())

    monkeypatch.setattr(hard.httpx, "Client", lambda **kwargs: factory(
        transport=httpx.MockTransport(handler), **kwargs))
    args = ["--input", str(path), "--output-dir", str(tmp_path / "runs")]
    assert hard.main(args) == int(fail)
    assert hard.main(args) == int(fail)
    assert len(list((tmp_path / "runs").glob("*.jsonl"))) == 2
    assert all(url.startswith("http://localhost:8000/api/") for url in urls)
    assert "Saved" in capsys.readouterr().err
