"""Shared edit layer (chat + 3D Edit panel): the chat can undo or restore manual removals, because the server passes
the chat's whole hidden set (manual edits included) as scene_state. Demo IFC doc ac20."""
from pathlib import Path

import pytest

from engine.answer import answer
from engine.scene_cmds import parse_scene, scene_answer, tags
from engine.solvers import ARTIFACTS
from engine.solvers.data import load_doc

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
DOOR = "3qloCPnZDEQBom1ZjBlwJP"          # Keller, 1.0 m interior door
pytestmark = pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")


@pytest.fixture(scope="module")
def doc():
    return load_doc(DOC, ARTIFACTS)


def _cmd(a):
    return a["evidence"]["scene"]["commands"][0]


@pytest.mark.parametrize("q", ["undo my edit", "undo my last edit", "Undo that change", "revert my last change",
                               "undo what I removed", "please undo"])
def test_undo_phrasings(q):
    assert parse_scene(q).op == "undo"


def test_put_the_door_back_restores_the_manually_hidden_door(doc):
    """Manual Remove in the Edit panel, then chat 'put the door back': only that door comes back, named."""
    a = answer("put the door back", [DOC], scene_state={"hidden": [DOOR], "last_hidden": [DOOR]})
    c = _cmd(a)
    assert c["op"] == "restore" and c["item_ids"] == [DOOR]
    assert f"({tags(doc)[DOOR]})" in a["answer"]["text_md"] and "visible again" in a["answer"]["text_md"]
    assert not a["answer"]["abstained"]


def test_undo_restores_the_latest_removal_only(doc):
    other = next(i.item_id for i in doc.items if i.kind == "window")
    st = {"hidden": [other, DOOR], "last_hidden": [DOOR]}
    a = scene_answer("undo my edit", doc, parse_scene("undo my edit"), st)
    assert _cmd(a) == {**_cmd(a), "op": "restore", "item_ids": [DOOR]}
    assert tags(doc)[DOOR] in a["answer"]["text_md"] and "1 other hidden item(s) stay hidden" in a["answer"]["text_md"]
    # no last_hidden (older server): everything hidden comes back, as before
    assert _cmd(scene_answer("undo", doc, parse_scene("undo"), {"hidden": [other, DOOR]}))["item_ids"] == [other, DOOR]


def test_restore_everything_resets_manual_edits_too():
    a = answer("restore everything", [DOC], scene_state={"hidden": [DOOR]})
    assert _cmd(a)["op"] == "reset"


def test_restore_without_state_keeps_old_behaviour(doc):
    """No shared state (no chat): 'bring the doors back' still restores every door."""
    n = sum(1 for i in doc.items if i.kind == "door")
    assert len(_cmd(answer("bring the doors back", [DOC]))["item_ids"]) == n


def test_singular_restores_the_latest_removal_plural_restores_all(doc):
    other = next(i.item_id for i in doc.items if i.kind == "door" and i.item_id != DOOR)
    st = {"hidden": [DOOR, other], "last_hidden": [other]}
    assert _cmd(scene_answer("put the door back", doc, parse_scene("put the door back"), st))["item_ids"] == [other]
    assert set(_cmd(scene_answer("put the doors back", doc, parse_scene("put the doors back"), st))["item_ids"]) == {DOOR, other}
    assert _cmd(scene_answer("put the door back", doc, parse_scene("put the door back"), {"hidden": [DOOR, other]}))["item_ids"] == [other]
