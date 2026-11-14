import pytest
from engine.app_help import app_help_answer, is_app_question, _guide

@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")   # unit tests never call a real model; the live path is checked by hand (E-58)


CASES = [
    ("how do I upload files?", ["Data", "Upload", "Choose file", "PDF", "DXF", "IFC"]),
    ("Which file formats can I upload?", ["PNG", "100 MiB"]),
    ("how do I ask about a specific document with @?", ["@", "Add to question"]),
    ("how do I open the 2D viewer from a citation?", ["Open citation", "drawing viewer"]),
    ("how do I see this in 3D?", ["Visualise it", "Build"]),
    ("how do I walk through the model?", ["Walk"]),
    ("can I remove a door in the 3D view and undo it?", ["Edit", "Undo"]),
    ("how do I run the rule checks?", ["Tools", "Run checks"]),
    ("how do I pair my phone?", ["QR", "Stoa Pro iPhone app", "History"]),
    ("how do I export a report?", ["Export report", "Copy as Markdown"]),
    ("how do I compare two versions of a drawing?", ["Compare", "Upload a new version"]),
    ("where are skills and automations?", ["Library"]),
]


@pytest.mark.parametrize("q,must", CASES)
def test_howto_answers_come_from_the_guide(q, must):
    r = app_help_answer(q, [])
    assert r is not None, q
    t = r["answer"]["text_md"]
    assert not r["answer"]["abstained"] and r["cost"]["usd_total"] == 0.0
    for w in must:
        assert w in t, (q, w, t)


def test_what_can_you_do_lists_features():
    t = app_help_answer("what can you do?", [])["answer"]["text_md"]
    assert "upload" in t and "Visualise it" in t and "Show on table" in t


def test_unknown_feature_points_to_help_and_invents_nothing(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    t = app_help_answer("how do I change the app theme colour in the settings page?", [])["answer"]["text_md"]
    assert "Help" in t and "does not cover" in t


@pytest.mark.parametrize("q", ["How many windows are there?", "Where is the stair core on level 2?",
                               "What is the net floor area of room 12?", "How does the roof drain?", "Can I fit a sofa in the living room?"])
def test_document_questions_are_not_hijacked(q):
    assert not is_app_question(q)


def test_every_button_named_in_guide_exists_in_ui_labels():
    # guard against invented buttons: the guide's bold-free labels must appear in the web source
    import pathlib, re
    src = "".join(p.read_text(errors="ignore") for p in pathlib.Path("web/src").rglob("*.tsx"))
    for label in ["Visualise it", "Walk", "Edit", "Undo", "Run checks", "Export report", "Copy as Markdown", "Pair a phone", "Choose file",
                  "Ask about it", "Open in Compare", "Upload a new version", "Create skill", "Create automation", "Show on table", "New chat", "Share", "History"]:
        assert label in src, label
    assert _guide()
