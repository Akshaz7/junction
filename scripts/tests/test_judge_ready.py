"""S-30: all deployment I/O is mocked; no live chats, pairs or quota consumed."""
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


SPEC = importlib.util.spec_from_file_location("judge_ready", Path(__file__).parents[1] / "judge_ready.py")
ready = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ready)
BASE = "https://frontend.example"
ORIGIN = "https://backend.example"
CHAT = "11111111-2222-3333-4444-555555555555"


def answer(count, doc_id):
    return {
        "answer": {"value": count, "text_md": f"There are **{count} items**. [1]", "abstained": False},
        "doc_ids": [doc_id], "latency_ms": 42,
        "evidence": {"boxes": [{"item_id": f"item-{i}", "bbox_px": [i, i, i+10, i+20]} for i in range(count)]},
    }


class Deployment:
    def __init__(self):
        self.requests = []
        self.queries = []
        self.ws_calls = []
        self.overrides = {}
        self.delete_pair = False
        self.burst_status = 200
        self.answers = [answer(18, ready.AC20), answer(5, ready.AC20), answer(13, ready.CUBI)]

    def handler(self, request):
        self.requests.append(request)
        method, path = request.method, request.url.path
        override = self.overrides.get((method, path))
        if override:
            return override(request)
        if path == "/api/health":
            return httpx.Response(200, json={"ok": True, "db": True, "caps_loaded": True,
                                            "servable_docs": 370, "bench_files": 1, "build_rev": "abc1234"})
        if path == "/api/bench/latest":
            return httpx.Response(200, json={"tag": "e-s200-z1", "abstentions": 0})
        if path == "/api/docs":
            return httpx.Response(200, json={"sources": [{"source": "ifc_bench", "docs": [{"doc_id": ready.AC20}]}]})
        if path.endswith("/files/scene.json"):
            return httpx.Response(200, json={"doc_id": ready.AC20, "items": {}})
        if path.endswith("/files/scene.glb"):
            return httpx.Response(200, content=b"glTF" + b"x" * 24)
        if path.endswith("/files/scene.usdz"):
            return httpx.Response(200, content=b"PK\x03\x04" + b"x" * 24)
        if path.endswith("/pages/2/image"):
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n" + b"x" * 24)
        if (method, path) == ("POST", "/api/chats"):
            return httpx.Response(201, json={"id": CHAT})
        if path.endswith("/messages"):
            self.queries.append(json.loads(request.content))
            value = self.answers[len(self.queries)-1]
            return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"},
                                  text="event: status\ndata: {}\n\nevent: answer\ndata: " + json.dumps(value) + "\n\n")
        if path.endswith("/scene-state"):
            return httpx.Response(self.burst_status, json={"chat_id": CHAT, "states": []})
        if (method, path) == ("POST", "/api/pair"):
            return httpx.Response(201, json={"code": "ABC123"})
        if path == "/openapi.json":
            assert request.url.host == "backend.example"
            paths = {"/api/pair/{code}": {"delete": {}}} if self.delete_pair else {}
            return httpx.Response(200, json={"paths": paths})
        if (method, path) == ("DELETE", "/api/pair/ABC123") and self.delete_pair:
            return httpx.Response(204)
        pytest.fail(f"unexpected HTTP request: {method} {path}")

    def ws_join(self, url, chat_id, timeout):
        self.ws_calls.append((url, chat_id, timeout))
        return "wss connected; scene.join -> scene.state in 2 ms"

    @contextmanager
    def runner(self):
        with httpx.Client(transport=httpx.MockTransport(self.handler), timeout=1) as client:
            yield ready.Readiness(client, BASE, ORIGIN, timeout=1, revision=lambda: "abc1234", ws_join=self.ws_join)


def test_all_checks_pass_one_chat_three_scoped_questions_and_exact_burst(capsys):
    deployment = Deployment()
    with deployment.runner() as checker:
        assert checker.run() == 0
        assert len(checker.results) == len(ready.PLAN)
        assert all(row.status == "PASS" for row in checker.results)
    calls = deployment.requests
    assert sum(r.method == "POST" and r.url.path == "/api/chats" for r in calls) == 1
    chat = next(json.loads(r.content) for r in calls if r.url.path == "/api/chats")
    assert chat["title"].startswith("judge-ready ") and chat["doc_ids"] == [ready.AC20]
    assert deployment.queries == [{"content": q, "doc_ids": [d]} for _, d, q, _ in ready.QUESTIONS]
    burst = [r for r in calls if r.url.path.endswith("/scene-state")]
    assert len(burst) == 30 and all(r.method == "GET" for r in burst)
    assert deployment.ws_calls == [("wss://backend.example/ws", CHAT, 1)]
    assert not any(r.method == "DELETE" for r in calls)
    output = capsys.readouterr().out
    assert CHAT in output and "PAIR CODE: ABC123" in output
    assert "bytes downloaded" in output and "server=42 ms" in output and "wall=" in output
    assert output.rstrip().endswith("JUDGE READY")


def test_build_mismatch_warns_without_failing(capsys):
    with Deployment().runner() as checker:
        checker.revision = lambda: "def5678"
        assert checker.run() == 0
        assert next(r for r in checker.results if r.name == "build").status == "WARN"
    assert capsys.readouterr().out.rstrip().endswith("JUDGE READY")


@pytest.mark.parametrize("field,bad", [("ok", False), ("db", False), ("caps_loaded", False),
    ("servable_docs", 369), ("servable_docs", None), ("bench_files", 0), ("bench_files", True)])
def test_health_gates(field, bad):
    deployment = Deployment()
    body = {"ok": True, "db": True, "caps_loaded": True, "servable_docs": 370, "bench_files": 1, "build_rev": "abc1234"}
    body[field] = bad
    deployment.overrides[("GET", "/api/health")] = lambda _: httpx.Response(200, json=body)
    with deployment.runner() as checker:
        checker.check("health", checker.check_health)
        assert checker.results[0].status == "FAIL" and field in checker.results[0].detail


@pytest.mark.parametrize("body", [{"tag": "fake200", "abstentions": 0},
    {"tag": "e-s200-z1", "abstentions": 1}, {"tag": "e-s200-z1", "abstentions": None},
    {"tag": "e-s200-z1", "abstentions": False}, {"status": "no_bench"}])
def test_rejects_unready_benchmark(body):
    deployment = Deployment()
    deployment.overrides[("GET", "/api/bench/latest")] = lambda _: httpx.Response(200, json=body)
    with deployment.runner() as checker:
        checker.check("benchmark", checker.check_bench)
        assert checker.results[0].status == "FAIL"


def test_multiple_failures_do_not_stop_remaining_checks_or_print_response_secrets(capsys):
    deployment = Deployment()
    deployment.overrides[("GET", "/api/health")] = lambda _: httpx.Response(503, text="secret-health-body")
    deployment.overrides[("POST", "/api/pair")] = lambda _: httpx.Response(405, text="secret-pair-body")
    deployment.burst_status = 429
    with deployment.runner() as checker:
        assert checker.run() == 1
        assert len(checker.results) == len(ready.PLAN)
        assert sum(row.status == "FAIL" for row in checker.results) == 4
    output = capsys.readouterr().out
    assert "0/30" in output and "HTTP 405" in output
    assert "secret-health-body" not in output and "secret-pair-body" not in output
    assert output.rstrip().endswith("NOT READY: 4 failures")


def test_chat_creation_failure_never_posts_messages_or_joins_ws():
    deployment = Deployment()
    deployment.overrides[("POST", "/api/chats")] = lambda _: httpx.Response(503)
    with deployment.runner() as checker:
        assert checker.run() == 1
    assert not deployment.queries and not deployment.ws_calls
    assert not any(r.url.path.endswith("/scene-state") for r in deployment.requests)
    assert any(r.url.path == "/api/pair" for r in deployment.requests)


def test_pair_deletes_only_created_code_when_advertised(capsys):
    deployment = Deployment()
    deployment.delete_pair = True
    with deployment.runner() as checker:
        assert checker.run() == 0
    deletes = [r.url.path for r in deployment.requests if r.method == "DELETE"]
    assert deletes == ["/api/pair/ABC123"]
    assert "deleted only the created pair" in capsys.readouterr().out


def test_failed_pair_cleanup_is_failure_and_keeps_code_visible(capsys):
    deployment = Deployment()
    deployment.delete_pair = True
    deployment.overrides[("DELETE", "/api/pair/ABC123")] = lambda _: httpx.Response(503)
    with deployment.runner() as checker:
        checker.check("pairing", checker.check_pair)
        assert checker.results[0].status == "FAIL"
    assert "PAIR CODE: ABC123" in capsys.readouterr().out


@pytest.mark.parametrize("change,error", [
    (lambda v: v["answer"].update(value=17), "expected=18"),
    (lambda v: v["answer"].update(value=True), "positive integer"),
    (lambda v: v["answer"].update(abstained=True), "abstained"),
    (lambda v: v["answer"].update(text_md="18 doors"), "inline"),
    (lambda v: v.update(doc_ids=[ready.CUBI]), "wrong document"),
    (lambda v: v["evidence"].update(boxes=[]), "boxes=0"),
    (lambda v: v["evidence"]["boxes"][0].update(bbox_px=[0, 0, 0, 0]), "invalid evidence box"),
    (lambda v: v.update(latency_ms=float("nan")), "latency_ms"),
])
def test_answer_proof_and_value_validation(change, error):
    value = answer(18, ready.AC20)
    change(value)
    with pytest.raises(ready.CheckError, match=error):
        ready.validate_answer(value, 18, ready.AC20)


def test_element_only_ifc_answers_fail_box_requirement_and_keep_latency(capsys):
    deployment = Deployment()
    deployment.answers[0]["evidence"]["boxes"] = []
    deployment.answers[1]["evidence"]["boxes"] = []
    with deployment.runner() as checker:
        assert checker.run() == 1
        assert [r.name for r in checker.results if r.status == "FAIL"] == ["ground-floor doors", "floors"]
    output = capsys.readouterr().out
    assert "value=18; boxes=0" in output and "server=42 ms" in output


@pytest.mark.parametrize("payload,error", [
    ("event: status\ndata: {}\n\n", "terminal"),
    ("event: error\ndata: secret-engine-error\n\n", "engine error"),
    ("event: answer\ndata: {}\n\nevent: answer\ndata: {}\n\n", "exactly one"),
])
def test_sse_failures(payload, error):
    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, text=payload)
    with pytest.raises(ready.CheckError, match=error):
        ready.streamed_answer(response)


def test_sse_comments_crlf_multiline_and_final_frame_without_blank_line():
    response = httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text=': ping\r\n\r\nevent: answer\r\ndata: {"answer":\r\ndata: {"value": 5}}')
    assert ready.streamed_answer(response) == {"answer": {"value": 5}}


def test_html_asset_not_mistaken_for_success():
    deployment = Deployment()
    path = f"/api/docs/{ready.AC20}/files/scene.glb"
    deployment.overrides[("GET", path)] = lambda _: httpx.Response(200, text="<html>fallback</html>")
    with deployment.runner() as checker:
        checker.check("model.glb", lambda: checker.download("model.glb", path, b"glTF"))
        assert checker.results[0].status == "FAIL"


def test_websocket_uses_scene_join_and_ignores_unrelated_events(monkeypatch):
    from websockets.sync import client

    class Socket:
        sent = []
        incoming = iter([
            {"type": "chat.message"},
            {"type": "scene.state", "chat_id": "other", "doc_id": ready.AC20},
            {"type": "scene.state", "chat_id": CHAT, "doc_id": ready.AC20,
             "hidden": [], "highlighted": [], "labels": {}},
        ])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, raw):
            self.sent.append(json.loads(raw))

        def recv(self, timeout):
            assert timeout > 0
            return json.dumps(next(self.incoming))

    sock = Socket()
    def connect(url, **kwargs):
        assert url == "wss://backend.example/ws"
        return sock
    monkeypatch.setattr(client, "connect", connect)
    assert "scene.join -> scene.state" in ready.websocket_join("wss://backend.example/ws", CHAT, 1)
    assert sock.sent == [{"type": "scene.join", "chat_id": CHAT, "doc_id": ready.AC20}]


def test_websocket_timeout_is_failure_without_error_details(capsys):
    with Deployment().runner() as checker:
        checker.chat_id = CHAT
        def fail(*args):
            raise TimeoutError("secret transport details")
        checker.ws_join = fail
        checker.check("WebSocket", checker.check_ws)
        assert checker.results[0].status == "FAIL"
    assert "secret transport details" not in capsys.readouterr().out


def test_dry_run_never_opens_network_or_git(monkeypatch, capsys):
    import socket
    def fail(*args, **kwargs):
        pytest.fail("dry run must not perform I/O")
    monkeypatch.setattr(httpx.Client, "request", fail)
    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(ready.subprocess, "check_output", fail)
    assert ready.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert all(name in output for name, _ in ready.PLAN)
    assert "readiness not assessed" in output and "\nJUDGE READY" not in output


@pytest.mark.parametrize("origin", ["http://localhost", "https://user:secret@example.com", "https://example.com/api"])
def test_rejects_non_deployed_or_credential_urls(origin):
    with pytest.raises(SystemExit):
        ready.main(["--dry-run", "--base-url", origin])


def test_cli_returns_nonzero_for_live_failure(monkeypatch):
    deployment = Deployment()
    deployment.overrides[("POST", "/api/pair")] = lambda _: httpx.Response(404)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(deployment.handler), **kwargs))
    real_runner = ready.Readiness
    monkeypatch.setattr(ready, "Readiness", lambda *args: real_runner(*args, revision=lambda: "abc1234", ws_join=deployment.ws_join))
    assert ready.main(["--base-url", BASE, "--aiven-origin", ORIGIN]) == 1
