import time
from pathlib import Path

import pytest

from engine import linked

ROOT = Path("/home/ar/junction/artifacts")
DOC = "uploads__swiss-site289-floor2149-bff698"
pytestmark = pytest.mark.skipif(not (ROOT / DOC / "planmap-1.json").exists(), reason="artifact missing")


def test_linked_door_relates_to_rooms_and_wall():
    r = linked.lookup(DOC, "door-001", ROOT)
    assert 1 <= len(r["relations"]["rooms"]) <= 2 and r["relations"]["wall"]
    assert r["scale"]["m_per_px"]


def test_linked_room_contains_door_fast():
    rooms = [x for x in linked._load_planmaps(DOC, ROOT)[0]["items"] if x["kind"] == "room"]
    t = time.perf_counter()
    hits = [linked.lookup(DOC, x["item_id"], ROOT) for x in rooms]
    print("per-room lookup s", (time.perf_counter() - t) / len(rooms))
    assert any(h["relations"]["counts"].get("door") for h in hits)


def test_linked_wall_bounds_room():
    walls = [x for x in linked._load_planmaps(DOC, ROOT)[0]["items"] if x["kind"] == "wall"][:10]
    assert any(linked.lookup(DOC, w["item_id"], ROOT)["relations"]["rooms"] for w in walls)


def test_linked_plan_unknown_id_is_none():
    assert linked.lookup(DOC, "no-such-item", ROOT) is None
