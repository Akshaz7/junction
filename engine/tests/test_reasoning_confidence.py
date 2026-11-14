from types import SimpleNamespace as NS

from engine.reasoning_parts import confidence


def _ctx(**kw):
    base = dict(res={}, question="", ans={}, cites=[], route="planmap", trace=[], unit="", value=None, doc=None, items={}, cited=[],
                first_cite={}, models_used=False, is_ifc=False, sc=None, scale_w="an estimated scale", scale_c=0.5, from_cad=False,
                steps=[{"kind": "found"}], checked=None, area_q=None, rooms=[])
    base.update(kw)
    return base


def test_ifc_verified():
    r = confidence.run(_ctx(route="solver", is_ifc=True))
    assert (r["label"], r["pct"], r["improve"]) == ("Verified", 97, None)
    assert r["_steps"] == [{"kind": "found"}]


def test_cad_verified():
    assert confidence.run(_ctx(from_cad=True, sc={"method": "dxf"}))["pct"] == 95


def test_scan_count_with_agreement_is_cross_checked():
    it = NS(kind="door", conf=0.9)
    r = confidence.run(_ctx(cited=[it], checked=True))
    assert r["label"] == "Cross-checked" and 80 <= r["pct"] <= 91


def test_scan_door_prior_area_is_estimate_with_improve():
    r = confidence.run(_ctx(unit="m2", sc={"method": "door-prior"}, scale_c=0.4))
    assert r["label"] == "Estimate" and r["pct"] < 80 and "scale" in r["improve"].lower()


def test_disagreement_drops():
    assert confidence.run(_ctx(checked=False))["label"] == "Estimate"


def test_vision_reader_low():
    r = confidence.run(_ctx(route="vision", ans={"confidence": 0.6}))
    assert r["label"] == "Estimate" and r["pct"] <= 70
