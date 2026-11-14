"""Large IFC lifecycle and bounded original persistence, no external services."""
import json
from types import SimpleNamespace

import pytest

from server import chats_routes, files_routes, ifc_ingest, ingest_job


def test_index_usable_before_scene_and_survives_scene_failure(tmp_path, monkeypatch):
    src = tmp_path / "model.ifc"
    # Sparse file verifies the default admits the full 100 MiB upload boundary.
    with src.open("wb") as f:
        f.truncate(files_routes.MAX_UPLOAD)
    doc = {"doc_id": "uploads__large", "files": {"ifc": str(src)}}
    st = ingest_job.Status(tmp_path / "ingest.json")

    def phase(name, source, out, timeout, **kwargs):
        if name == "ifc_index":
            (out / "elements.json").write_text(json.dumps({"elements": []}))
            return {"peak_worker_rss_mib": 99}
        state = json.loads((out / "ingest.json").read_text())
        assert state["readable"] and state["status"] == "running"
        assert "Counts and quantities" in state["detail"]
        raise RuntimeError("This phase exceeded its 320 MiB memory budget.")

    monkeypatch.setattr(ifc_ingest, "phase", phase)
    monkeypatch.delenv("INGEST_IFC_MAX_MB", raising=False)
    assert ifc_ingest.run(src, doc, tmp_path, st) == "partial"
    state = json.loads(st.path.read_text())
    assert state["readable"] and "3D view could not" in state["detail"]
    assert "320 MiB" in state["detail"] and (tmp_path / "elements.json").is_file()


def test_watchdog_preserves_existing_index(tmp_path):
    f = tmp_path / "ingest.json"
    f.write_text(json.dumps({"status": "running", "readable": True, "stages": []}))
    (tmp_path / "elements.json").write_text('{"elements":[]}')
    state = files_routes._fail_ingest(f, "Ingestion timed out after 5 minutes.")
    assert state["status"] == "partial" and state["readable"]
    assert "already indexed remain available" in state["detail"]


def test_chat_reports_specific_ingestion_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(chats_routes, "ENGINE", chats_routes._real_engine)
    doc = tmp_path / "uploads__failed"
    doc.mkdir()
    detail = "This IFC is 125 MB; this server indexes IFC files up to 104.858 MB. Split the model into smaller IFC files."
    (doc / "ingest.json").write_text(json.dumps({"status": "failed", "reason": detail}))
    answer = chats_routes._no_data_answer("How many doors?", [doc.name])
    assert detail == answer["answer"]["text_md"]
    assert "no readable drawing data" not in answer["answer"]["text_md"]
    assert answer["cost"]["usd_total"] == 0


def test_unavailable_scene_uses_progress_detail(tmp_path):
    detail = ifc_ingest.INDEX_DETAIL
    (tmp_path / "ingest.json").write_text(json.dumps({"status": "running", "readable": True, "detail": detail}))
    result = files_routes._missing_scene(tmp_path)
    assert result.status_code == 404 and json.loads(result.body)["detail"] == detail


def test_budget_reserves_container_headroom(tmp_path, monkeypatch):
    # RSS and native allocation safeguards are independently tested without
    # allocating hundreds of megabytes or relying on host-specific ps output.
    monkeypatch.setenv("IFC_WORKER_MEMORY_MB", "128")
    assert ifc_ingest._budget() <= 128 * 1024**2


def test_scene_timeout_kills_worker_and_keeps_index(tmp_path, monkeypatch):
    (tmp_path / "elements.json").write_text('{"elements":[]}')
    proc = SimpleNamespace(poll=lambda: None, pid=123, returncode=-9, kill=lambda: None, wait=lambda: None)
    monkeypatch.setattr(ifc_ingest.subprocess, "Popen", lambda *a, **kw: proc)
    monkeypatch.setattr(ifc_ingest, "_rss", lambda pid: 1)
    with pytest.raises(RuntimeError, match="time limit"):
        ifc_ingest.phase("ifc_scene", tmp_path / "input.ifc", tmp_path, timeout=-1)
    assert (tmp_path / "elements.json").is_file()


def test_missing_index_quantity_is_not_sent_to_a_model(tmp_path, monkeypatch):
    import time

    from engine import ifc_pending
    from engine.solvers.solve import _abstain
    doc = tmp_path / "uploads__props"
    doc.mkdir()
    (doc / "elements.json").write_text(json.dumps({"geometry": "pending", "elements": []}))
    answer = _abstain("What is the area?", doc.name, "The model has no area data for rooms.", [], "index", time.perf_counter())
    assert ifc_pending.missing_quantity(answer, [doc.name], tmp_path)
    import importlib
    module = importlib.import_module("engine.answer")
    monkeypatch.setattr(module, "_reader", lambda *a: pytest.fail("Missing IFC quantities must never be guessed"))
    assert module._use_reader(answer, "What is the area?", [doc.name], tmp_path, [], [], time.perf_counter(), lambda *a: None) is answer


@pytest.mark.parametrize("fault", [None, "duplicate", "interrupted"])
def test_batches_publish_only_a_complete_unique_index(tmp_path, monkeypatch, fault):
    published = tmp_path / "elements.json"
    published.write_text('{"old":"complete"}')
    calls = []

    def phase(name, source, out, timeout, index_offset=0):
        assert json.loads(published.read_text()) == {"old": "complete"}
        calls.append(index_offset)
        if index_offset and fault == "interrupted":
            raise RuntimeError("Worker memory limit")
        gid = "first" if not index_offset or fault == "duplicate" else "second"
        (out / "elements.json").write_text(json.dumps({"geometry": "pending", "total_elements": 2,
                                                        "elements": [{"item_id": gid}]}))
        return {"peak_worker_rss_mib": 50 + index_offset, "memory_budget_mib": 320}

    monkeypatch.setattr(ifc_ingest, "phase", phase)
    if fault:
        with pytest.raises(RuntimeError, match="duplicate|memory limit"):
            ifc_ingest.index(tmp_path / "input.ifc", {}, tmp_path, 90)
        assert json.loads(published.read_text()) == {"old": "complete"}
    else:
        metrics = ifc_ingest.index(tmp_path / "input.ifc", {}, tmp_path, 90)
        assert calls == [0, 1] and metrics["batches"] == 2
        assert [e["item_id"] for e in json.loads(published.read_text())["elements"]] == ["first", "second"]


def test_property_queries_use_the_ready_index_without_reopening_large_source(tmp_path, monkeypatch):
    from engine import props
    folder = tmp_path / "uploads__large"
    folder.mkdir()
    source = folder / "source.ifc"
    source.write_text("The property route must not parse this source")
    (folder / "doc.json").write_text(json.dumps({"files": {"ifc": str(source)}}))
    (folder / "ingest.json").write_text(json.dumps({"status": "running", "readable": True}))
    (folder / "elements.json").write_text(json.dumps({"elements": [
        {"item_id": "door", "kind": "door", "props": {"fire_rating": "60 minutes"}, "quantities": {"width_m": .9}}]}))
    monkeypatch.setattr(props, "_read_ifc", lambda *a: pytest.fail("The upload's bounded property index is already available"))
    records, _, status = props.index(folder.name, tmp_path)
    assert records[0].values["fire_rating"] == "60 minutes"
    assert records[0].values["width_m"] == .9
    assert status == "the stored model index"
