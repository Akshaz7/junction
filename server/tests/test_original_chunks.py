"""Large originals persist in bounded chunks and restore only after integrity checks."""
import asyncio
import json

import pytest

from server import artifact_store


class MemoryPool:
    def __init__(self):
        self.rows = {}
        self.max_parameter = 0

    async def execute(self, query, doc, name, ct, data, size):
        self.max_parameter = max(self.max_parameter, len(data))
        self.rows[name] = {"data": bytes(data), "name": name}

    async def fetch(self, query, doc):
        return [{"name": n} for n in self.rows]

    async def fetchrow(self, query, doc, name):
        return self.rows.get(name)


@pytest.mark.parametrize("damage", [None, "missing", "corrupt"])
def test_chunked_original_round_trip_and_integrity(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(artifact_store, "SOURCE_CHUNK_BYTES", 16)
    doc = tmp_path / "uploads__test"
    doc.mkdir()
    original = tmp_path / "uploads" / "large.ifc"
    original.parent.mkdir()
    data = b"ISO-10303-21;" * 10
    original.write_bytes(data)
    (doc / "doc.json").write_text(json.dumps({"files": {"ifc": str(original)}}))
    pool = MemoryPool()
    asyncio.run(artifact_store.save_doc(pool, doc.name))
    part_names = sorted(n for n in pool.rows if n.startswith(artifact_store.SOURCE_CHUNKS) and not n.endswith("manifest.json"))
    assert len(part_names) == 9
    assert all(len(pool.rows[n]["data"]) <= 16 for n in part_names)
    assert not any(n.startswith(artifact_store.ORIGINAL) for n in pool.rows)
    original.unlink()
    if damage == "missing":
        del pool.rows[part_names[1]]
    elif damage == "corrupt":
        pool.rows[part_names[1]]["data"] = b"corrupt"
    if damage:
        with pytest.raises(ValueError, match="incomplete|integrity"):
            asyncio.run(artifact_store.restore_doc(pool, doc.name))
        assert not original.exists()
        assert not list(original.parent.glob("*.tmp"))
    else:
        asyncio.run(artifact_store.restore_doc(pool, doc.name))
        assert original.read_bytes() == data

