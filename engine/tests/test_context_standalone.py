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
