from engine import context

DOC = "ifc_bench__ac20-arc"
SEQS = [("What does this drawing say about the doors?", "The drawing says doors are ..."), ("How many windows are there?", "There are 120 windows.")]


def _hist(q, a):
    return [{"role": "user", "content": q, "doc_ids": [DOC]}, {"role": "assistant", "content": a, "doc_ids": [DOC]}]


def test_self_contained_questions_are_never_rewritten(monkeypatch):
    monkeypatch.setattr("engine.models.call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model must not be called")))
    for q, a in SEQS:
        for ask in ("How many doors are there?", "How many doors?", "Where are the toilets?", "How many windows and doors are there?"):
            r = context.resolve(ask, [DOC], _hist(q, a))
            assert not r.rewritten and r.question == ask


def test_followups_still_rewrite():
    assert not context.stands_alone("and doors?")
    assert not context.stands_alone("what about the same on level 2?")


def test_bad_rewrite_is_discarded(monkeypatch):
    class R:
        json = {"question": "How many offices are in the AC20 Institute document?", "doc": "current"}
        model, cost_usd, latency_ms, provider = "m", 0.0, 1, "p"
    monkeypatch.setattr("engine.models.call", lambda *a, **k: R())
    r = context.resolve("and the doors?", [DOC], _hist(*SEQS[1]))
    assert "offices" not in r.question.lower()
    assert context.rewrite_ok("and the doors?", "How many doors are there?", _hist("How many doors?", "77"))
    assert not context.rewrite_ok("and the doors?", "How many offices are there?", _hist(*SEQS[1]))


def test_rewrite_may_repeat_the_document_title():
    from engine.context import rewrite_ok
    h = [{"role": "user", "content": "How many doors and windows are on the ground floor?"}]
    cand = "How many doors and windows are on the first floor of the AC20 Institute / Phantasy Office Building - arc model?"
    assert not rewrite_ok("And on the first floor?", cand, h)
    assert rewrite_ok("And on the first floor?", cand, h, ["AC20 Institute / Phantasy Office Building - arc"])


def test_strip_titles_removes_the_repeated_title_clause():
    from engine.context import strip_titles
    t = ["AC20 Institute / Phantasy Office Building - arc"]
    assert strip_titles("How many doors and windows are on the first floor of the AC20 Institute / Phantasy Office Building - arc model?", t) == "How many doors and windows are on the first floor?"
    assert strip_titles("Where is the kitchen?", t) == "Where is the kitchen?"


def test_scene_command_with_its_own_object_is_not_rewritten():
    from engine.context import stands_alone
    assert stands_alone("Remove the front door. Is it still compliant?")
    assert stands_alone("Hide all the windows")
    assert not stands_alone("Remove it")


def test_two_kind_count_names_the_storey():
    from pathlib import Path
    from engine.answer import answer
    if not Path("artifacts/ifc_bench__ac20-arc").is_dir():
        return
    a = answer("How many doors and windows are on the ground floor?", ["ifc_bench__ac20-arc"])
    assert "on Erdgeschoss (ground floor)" in a["answer"]["text_md"].replace("**", "") and "in this model" not in a["answer"]["text_md"]
