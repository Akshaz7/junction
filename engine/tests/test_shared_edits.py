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
    # no last_hidden (older server): only the last hidden item comes back (main's undo rule)
    assert _cmd(scene_answer("undo", doc, parse_scene("undo"), {"hidden": [other, DOOR]}))["item_ids"] == [DOOR]


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


def _ids(doc, kind, n=2):
    return [i.item_id for i in doc.items if i.kind == kind][:n]


@pytest.mark.parametrize("q", ["move the window back", "put it back where it was", "undo my edit", "undo", "put the window back"])
def test_chat_reverts_a_manual_move(doc, q):
    """Edit-panel move recorded in the shared layer; the chat puts it back (offset [0, 0])."""
    win = _ids(doc, "window", 1)[0]
    st = {"hidden": [], "last_hidden": [], "moved": {win: [0.5, 0.0]}, "last_edit": {"op": "move", "item_ids": [win]}}
    a = answer(q, [DOC], scene_state=st)
    assert a["evidence"]["scene"]["commands"] == [
        {"op": "move", "item_ids": [win], "offset_m": [0.0, 0.0], "labels": {win: tags(doc)[win]}}]
    assert "back where it was" in a["answer"]["text_md"] and tags(doc)[win] in a["answer"]["text_md"]


def test_chat_reverts_a_material_and_hides_still_win(doc):
    wall = _ids(doc, "wall", 1)[0]
    st = {"hidden": [DOOR], "last_hidden": [DOOR], "materials": {wall: "Glass"}, "last_edit": {"op": "material", "item_ids": [wall]}}
    a = answer("undo my edit", [DOC], scene_state=st)
    assert _cmd(a) == {"op": "material", "item_ids": [wall], "material": None, "labels": {wall: tags(doc)[wall]}}
    assert "original material" in a["answer"]["text_md"]
    # the newest edit was the removal: undo brings the door back, the material stays
    st["last_edit"] = {"op": "hide", "item_ids": [DOOR]}
    assert _cmd(answer("undo my edit", [DOC], scene_state=st)) == {**_cmd(answer("undo my edit", [DOC], scene_state=st)),
                                                                   "op": "restore", "item_ids": [DOOR]}
    # "put the door back" names a hidden door: restore, not a material revert
    assert _cmd(answer("put the door back", [DOC], scene_state=st))["op"] == "restore"


def test_named_kind_reverts_only_moved_items(doc):
    w1, w2 = _ids(doc, "window")
    st = {"hidden": [], "moved": {w1: [1.0, 0.0], w2: [0.0, 1.0]}, "last_edit": {"op": "move", "item_ids": [w2]}}
    assert _cmd(answer("move the window back", [DOC], scene_state=st))["item_ids"] == [w2]          # singular: the latest
    assert set(_cmd(answer("move the windows back", [DOC], scene_state=st))["item_ids"]) == {w1, w2}
    # nothing moved: the old restore path (all windows visible again)
    assert _cmd(answer("move the window back", [DOC], scene_state={"hidden": []}))["op"] == "restore"


def test_edit_log_undo_steps_moves_and_materials_back(doc):
    """Main's ordered edit-log undo (state["edits"]) inverts the last edit, now including moves and materials."""
    from engine.scene_cmds import undo_commands
    win, wall = _ids(doc, "window", 1)[0], _ids(doc, "wall", 1)[0]

    def ed(op, ids, **detail):
        return {"doc_id": DOC, "op": op, "item_ids": ids, "labels": {}, "detail": detail}
    log = [ed("hide", [DOOR]), ed("move", [win], offset_m=[0.5, 0]), ed("move", [win], offset_m=[1.0, 0])]
    assert undo_commands(doc, {"edits": log}) == [{"op": "move", "item_ids": [win], "offset_m": [0.5, 0.0]}]   # one step back
    assert undo_commands(doc, {"edits": log[:2]}) == [{"op": "move", "item_ids": [win], "offset_m": [0.0, 0.0]}]
    assert undo_commands(doc, {"edits": [*log, ed("material", [wall], material="Glass")]}) == [
        {"op": "material", "item_ids": [wall], "material": None}]
    assert undo_commands(doc, {"edits": [*log, ed("highlight", [win])]})[0]["op"] == "move"            # highlights never consume Undo
    assert undo_commands(doc, {"edits": log[:1]}) == [{"op": "restore", "item_ids": [DOOR]}]          # visibility unchanged
    # undo of a reset brings the hidden door and the move back
    out = undo_commands(doc, {"edits": [*log, ed("reset", [])]})
    assert {"op": "hide", "item_ids": [DOOR]} in out and {"op": "move", "item_ids": [win], "offset_m": [1.0, 0.0]} in out
    # through answer(): undo with the log is main's path
    a = answer("undo", [DOC], scene_state={"hidden": [DOOR], "edits": log, "last_hidden": [DOOR], "moved": {win: [1.0, 0.0]},
                                           "last_edit": {"op": "move", "item_ids": [win]}})
    assert a["evidence"]["scene"]["commands"] == [{"op": "move", "item_ids": [win], "offset_m": [0.5, 0.0]}]
