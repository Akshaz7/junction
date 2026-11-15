"""Budget order of the vector page stages (server.ingest_job PAGE_LIMITS / VECTOR_RESERVE_S): when a dense sheet's
rooms or openings eat the page's time, the plan-region crop still runs (neighbouring roofs stay out) and only the
optional add-ons are cut; the IFC route keeps enough time after the page for a dense sheet."""
import sys
import time
import types

from server import ingest_job


def _fake_modules(monkeypatch, calls):
    def mod(name, **fns):
        m = types.ModuleType(f"pipeline.{name}")
        for k, f in fns.items():
            setattr(m, k, f)
        monkeypatch.setitem(sys.modules, f"pipeline.{name}", m)
        return m

    def forever(*a, **k):
        calls.append("rooms")
        time.sleep(60)
        return ["never"]

    def quick(name, out=None):
        def f(*a, **k):
            calls.append(name)
            return out
        return f
    mod("pdf_rooms", rooms=forever)
    mod("pdf_openings", openings=quick("openings", ["door"]))
    mod("pdf_semantics", plan_region=quick("plan_region", ("region", {})), analyse=quick("analyse", {}))
    mod("pdf_fixtures", detect=quick("detect", []))
    mod("pdf_levels", planmap_provenance=quick("planmap_provenance", {}))
    mod("pdf_quality", assess=quick("assess", {}))


def test_plan_region_runs_after_rooms_ate_the_page(monkeypatch):
    calls, cut = [], []
    _fake_modules(monkeypatch, calls)
    page_s = ingest_job.PLAN_REGION_RESERVE_S + 2.0  # rooms gets 2 s, then must leave the reserve behind it
    restore = ingest_job._soft_limits(time.time() + page_s, cut)
    try:
        t = time.time()
        assert sys.modules["pipeline.pdf_rooms"].rooms(None, []) == []  # cut at its limit: empty result
        assert time.time() - t < 4.0
        assert sys.modules["pipeline.pdf_openings"].openings(None, []) == ["door"]
        assert sys.modules["pipeline.pdf_semantics"].plan_region(None, [], [], [], 1.0) == ("region", {})
    finally:
        for m, name, f in restore:
            setattr(m, name, f)
    assert cut == ["rooms"], cut
    assert calls == ["rooms", "openings", "plan_region"]


def test_ifc_route_keeps_time_after_a_full_page():
    """ARK at the production budget: after the page images (~7 s) a vector page may run up to its hard timeout
    (left - VECTOR_RESERVE_S); the IFC route then still gets >= 90 s (dense sheet: 72-86 s) before IFC_RESERVE_S."""
    left = ingest_job.INGEST_BUDGET_S - 7.0
    page_timeout = left - ingest_job.VECTOR_RESERVE_S
    ifc_timeout = (left - page_timeout) - ingest_job.IFC_RESERVE_S
    assert ifc_timeout >= 90.0
    page_s = left - ingest_job.VECTOR_RESERVE_S - 3.0  # the page child's own soft deadline
    assert page_s >= 120.0  # ARK plan-map compute ~80 s + crop + semantics, optional add-ons in what is left
