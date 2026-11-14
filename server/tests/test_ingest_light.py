"""Upload ingestion in the deploy image: VLM plan map, text.json, durable storage in PostgreSQL."""
import asyncio
import json

from server import artifact_store, config, ingest_job, vlm_planmap

RAW = {
    "is_plan": True,
    "items": [
        {"kind": "room", "box_2d": [100, 100, 500, 500], "label": "KITCHEN", "room_type": "kitchen", "printed_area_m2": 12.5},
        {"kind": "room", "box_2d": [100, 500, 500, 900], "label": "Bedroom 1", "room_type": "bedroom"},
        {"kind": "door", "box_2d": [300, 495, 360, 505]},
        {"kind": "door", "box_2d": [300, 495, 360, 505]},      # exact duplicate: dropped by the dup rule
        {"kind": "door", "box_2d": [100, 300, 110, 360]},
        {"kind": "window", "box_2d": [95, 600, 105, 700]},
        {"kind": "window", "box_2d": [0, 0, 0, 0]},             # degenerate: dropped
        {"kind": "toilet", "box_2d": [400, 800, 440, 840]},
    ],
    "dimensions": [],
}


def test_build_planmap_from_vlm_output():
    pm = vlm_planmap.build("uploads__x-1", 1, 1000, 800, RAW, "m", 5)
    assert vlm_planmap.validate(pm) == []
    kinds = [i["kind"] for i in pm["items"]]
    assert kinds.count("door") == 2 and kinds.count("window") == 1 and kinds.count("room") == 2
    assert all(i["source"] in ("vlm", "rule") for i in pm["items"])
    assert pm["scale"]["method"] == "door-prior" and pm["scale"]["m_per_px"]
    kitchen = next(i for i in pm["items"] if i["label"] == "KITCHEN")
    assert kitchen["props"]["room_type"] == "kitchen" and kitchen["props"]["area_m2_label"] == 12.5
    derived = [i for i in pm["items"] if i["kind"] == "wall"]
    assert derived and all(i["props"]["derived"] == "room-outline" and i["source"] == "rule" and i["conf"] < 0.5 for i in derived)
    assert len({i["item_id"] for i in pm["items"]}) == len(pm["items"])


def test_dimension_scale_wins_when_two_agree():
    raw = dict(RAW, dimensions=[{"text": "4.00 m", "meters": 4.0, "box_2d": [50, 100, 60, 500]},
                                {"text": "2.00 m", "meters": 2.0, "box_2d": [50, 500, 60, 700]}])
    pm = vlm_planmap.build("d", 1, 1000, 1000, raw, "m", 1)
    assert pm["scale"]["method"] == "dimension" and abs(pm["scale"]["m_per_px"] - 0.01) < 1e-6


def test_text_json_has_words_lines_and_text(tmp_path):
    words = [{"text": "ROOM", "bbox_px": [10, 10, 50, 22]}, {"text": "101", "bbox_px": [55, 11, 80, 22]},
             {"text": "NOTES", "bbox_px": [10, 100, 60, 112]}]
    (tmp_path / "text-1.json").write_text(json.dumps(
        {"doc_id": "d", "page": 1, "image": {"w": 200, "h": 200}, "source": "pdf-text-layer", "words": words}))
    ingest_job.build_text_json("d", tmp_path)
    p = json.loads((tmp_path / "text.json").read_text())["pages"][0]
    assert p["text"] == "ROOM 101\nNOTES" and p["lines"][0]["bbox_px"] == [10, 10, 80, 22] and len(p["words"]) == 3


def test_artifact_store_round_trip(schema_url, tmp_path, monkeypatch):
    import asyncpg
    from server import db
    from server.migrate import apply_migrations
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(artifact_store, "_restored", set())
    art = tmp_path / "artifacts"
    doc_id = "uploads__rt-123456"
    (art / doc_id).mkdir(parents=True)
    (art / "uploads").mkdir()
    (art / "uploads" / "orig.png").write_bytes(b"ORIG")
    (art / doc_id / "doc.json").write_text(json.dumps({"doc_id": doc_id, "files": {"png": "artifacts/uploads/orig.png"}}))
    (art / doc_id / "planmap-1.json").write_text("{}")
    (art / doc_id / "page-1.png").write_bytes(b"\x89PNG")

    async def go():
        c = await asyncpg.connect(config.database_url())
        await apply_migrations(c)
        await c.close()
        pool = await db.get_pool()
        n = await artifact_store.save_doc(pool, doc_id)
        await artifact_store.save_doc(pool, doc_id)  # idempotent
        import shutil
        shutil.rmtree(art)  # the container restarted with a fresh disk
        await artifact_store.ensure_doc(doc_id)
        await db.close_pool()
        return n
    assert asyncio.run(go()) > 0
    assert json.loads((art / doc_id / "doc.json").read_text())["doc_id"] == doc_id
    assert (art / doc_id / "page-1.png").read_bytes() == b"\x89PNG"
    assert (art / "uploads" / "orig.png").read_bytes() == b"ORIG"


def test_size_cap_keeps_plan_map_and_drops_page_images(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(artifact_store, "MAX_DOC_BYTES", 100)
    d = tmp_path / "uploads__big-000000"
    d.mkdir()
    (d / "planmap-1.json").write_text("{}")
    (d / "page-1.png").write_bytes(b"x" * 1000)
    names = [n for n, _ in artifact_store.doc_files("uploads__big-000000")]
    assert "planmap-1.json" in names and "page-1.png" not in names
