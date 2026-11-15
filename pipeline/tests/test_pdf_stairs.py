import ifcopenshell.util.element as ue_
import pytest

from pipeline import pdf_stairs as S


def _fl(origin, run, side, length, width, treads):
    return {"origin": origin, "run": run, "side": side, "length": length, "width": width, "treads": treads}


@pytest.mark.parametrize("h", [2.7, 3.0, 3.45])
def test_risers_in_range_and_sum_to_height(h):
    for drawn in (None, 3, 5, 17, 40):
        n, rh = S.risers(h, drawn)
        assert S.RISER_MIN <= rh <= S.RISER_MAX
        assert abs(n * rh - h) < 1e-9


def test_risers_keeps_buildable_drawn_count():
    assert S.risers(3.0, 17)[0] == 17


def test_straight_flight():
    p = S.plan([_fl((0, 0), (1, 0), (0, 1), 4.5, 1.2, 15)], 3.0)
    assert len(p) == 1 and p[0]["turn"] == "straight" and p[0]["predefined"] == "STRAIGHT_RUN_STAIR"
    assert abs(p[0]["risers"] * p[0]["riser_h"] - 3.0) < 1e-9


def test_u_stair_with_landing():
    a = _fl((0, 0), (1, 0), (0, 1), 2.7, 1.3, 9)
    b = _fl((0.9, 1.45), (1, 0), (0, 1), 1.8, 1.3, 6)
    p = S.plan([a, b], 3.45)
    assert len(p) == 1 and p[0]["turn"] == "U" and p[0]["predefined"] == "HALF_TURN_STAIR"
    assert sum(p[0]["per_flight"]) == p[0]["risers"]
    assert 0 < p[0]["landings_z"][0] < 3.45
    assert S.RISER_MIN <= p[0]["riser_h"] <= S.RISER_MAX


def test_far_flights_stay_separate():
    a = _fl((0, 0), (1, 0), (0, 1), 2.7, 1.3, 9)
    b = _fl((20, 20), (1, 0), (0, 1), 2.7, 1.3, 9)
    assert [x["turn"] for x in S.plan([a, b], 3.0)] == ["straight", "straight"]


def test_hook_never_raises():
    assert S.enrich_ifc_file(None, None) == 0


# ---------------------------------------------------------------- IFC rebuild (synthetic model)

def _model(h=3.45, stairs=((0, 0, 81, 39, 9), (0, 42, 81, 39, 9))):
    """A one-storey IFC with pdf_fixtures stairs: (x, y, run_pt, width_pt, treads) rectangles in page pt."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.unit
    from pipeline import pdf_fixtures
    f = ifcopenshell.api.project.create_file(version="IFC4") if hasattr(ifcopenshell.api, "project") else None
    if f is None:
        import ifcopenshell.api.project
        f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="t")
    ifcopenshell.api.unit.assign_unit(f)
    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=ctx)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite")
    bld = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding")
    sto = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="L3")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bld], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[sto], relating_object=bld)
    sto.ObjectPlacement = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 13.0)), None, None))
    ps = ifcopenshell.api.pset.add_pset(f, product=sto, name="Hologram_StoreySource")
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"WallHeight": h})
    mpt = 0.0352777
    fx = []
    for x, y, run, w, n in stairs:
        poly = [[x, y], [x + run, y], [x + run, y + w], [x, y + w]]
        fx.append({"kind": "stair", "polygon": poly, "conf": 0.9,
                   "props": {"treads": n, "tread_depth_m": round(run * mpt / n, 3), "direction": None}})
    pdf_fixtures.to_ifc(f, sto, body, fx, 0.0, storey_height_m=h, m_per_pt=mpt, doc_id="t")
    return f, fx


def _rise(fl):
    """Top of the flight solids above the flight base (from the authored profile, not from attributes)."""
    import ifcopenshell.util.placement as up
    import numpy as np
    tops, bots = [], []
    M = up.get_local_placement(fl.ObjectPlacement)
    for it in fl.Representation.Representations[0].Items:
        P = M @ up.get_axis2placement(it.Position)
        ys = [p[1] for p in it.SweptArea.OuterCurve.Points.CoordList]
        # profile y is world up (the profile plane is vertical)
        up_axis = P[:3, 1]
        assert np.allclose(up_axis, (0, 0, 1), atol=1e-6)
        tops.append(P[2, 3] + max(ys)); bots.append(P[2, 3] + min(ys))
    return min(bots), max(tops)


def test_ifc_u_stair_flights_landing_and_drawn_rise():
    import ifcopenshell.util.element as ue
    f, _ = _model()
    before = {e.GlobalId for e in f.by_type("IfcStair")} | {e.GlobalId for e in f.by_type("IfcStairFlight")}
    rep = []
    assert S.enrich_ifc_file(f, [], rep) == 1, rep
    stairs = f.by_type("IfcStair")
    assert len(stairs) == 1 and ue_.get_predefined_type(stairs[0]) == "HALF_TURN_STAIR"
    parts = ue.get_decomposition(stairs[0])
    flights = [p for p in parts if p.is_a("IfcStairFlight")]
    landings = [p for p in parts if p.is_a("IfcSlab") and p.PredefinedType == "LANDING"]
    assert len(flights) == 2 and len(landings) == 1
    # every GlobalId survives: stair 2's goes to flight 2, flight 2's to the landing
    after = {e.GlobalId for e in list(stairs) + flights + landings}
    assert before == after
    h = 3.45  # a U stair in its shaft rises the full storey (derived); 20 risers of the 175 mm class -> 172.5 mm
    rh = h / round(h / S.DEFAULT_RISER)
    lo = min(_rise(fl)[0] for fl in flights)
    hi = max(_rise(fl)[1] for fl in flights)
    assert abs((hi - lo) - (h - rh)) < 1e-6  # the top riser is the floor-slab edge above
    assert sum(fl.NumberOfRisers * fl.RiserHeight for fl in flights) == pytest.approx(h, abs=1e-3)
    assert all(S.RISER_MIN <= fl.RiserHeight <= S.RISER_MAX for fl in flights)
    # the landing top is where flight 1 ends and flight 2 starts
    zs = sorted(_rise(fl) for fl in flights)
    lz = ue.get_psets(flights[0])["Hologram_StairFlight"]
    import ifcopenshell.util.placement as up
    it = landings[0].Representation.Representations[0].Items[0]
    ltop = (up.get_local_placement(landings[0].ObjectPlacement) @ up.get_axis2placement(it.Position))[2, 3] + it.Depth
    assert ltop == pytest.approx(zs[1][0] + 0, abs=0.25) and zs[0][1] + rh == pytest.approx(ltop, abs=1e-6)
    ps = ue.get_psets(stairs[0])
    assert ps["Pset_StairCommon"]["NumberOfRiser"] * ps["Pset_StairCommon"]["RiserHeight"] == pytest.approx(h, abs=1e-3)
    assert all("Pset_StairFlightCommon" in ue.get_psets(fl) for fl in flights)
    assert all(ue.get_material(p) is not None for p in flights + landings)
    assert lz["BaseElevation"] == pytest.approx(0.0) or lz["BaseElevation"] == pytest.approx(zs[1][0] - lo, abs=1e-3)


def test_ifc_straight_stair_drawn_rise_printed_riser_and_valid():
    import ifcopenshell.validate
    f, _ = _model(h=3.0, stairs=((0, 0, 60, 34, 6),))
    gid = f.by_type("IfcStair")[0].GlobalId
    pm = {"page": 1, "fixtures": [{"kind": "stair", "props": {"treads": 6, "riser_printed_m": 0.16,
                                                              "riser_text": "N 160"}}]}
    assert S.enrich_ifc_file(f, [pm]) == 1
    st = f.by_type("IfcStair")[0]
    assert st.GlobalId == gid and ue_.get_predefined_type(st) == "STRAIGHT_RUN_STAIR"
    (fl,) = [p for p in __import__("ifcopenshell.util.element").util.element.get_decomposition(st)]
    lo, hi = _rise(fl)
    assert hi - lo == pytest.approx(6 * 0.16, abs=1e-6)  # 7 risers x printed 160 mm; the 7th is the slab edge
    assert fl.NumberOfRisers == 7 and fl.RiserHeight == pytest.approx(0.16)
    ev = ue_.get_psets(st)["Hologram_Evidence"]
    assert ev["Source"].startswith("partial") and "N 160" in ev["Detail"]  # no stair room: kept as drawn
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg)
    assert not lg.statements


def test_ifc_rebuild_never_raises_and_leaves_bad_stairs():
    f, _ = _model()
    fl = f.by_type("IfcStairFlight")[0]
    fl.Representation = None  # nothing to read: that stair group is left as it was
    n0 = len(f.by_type("IfcStair"))
    assert S.enrich_ifc_file(f, None) in (0, 1)
    assert S.enrich_ifc_file(object()) == 0
    assert len(f.by_type("IfcStair")) >= n0 - 1


def test_ifc_u_stair_well_balustrades_follow_the_pitch():
    import ifcopenshell.util.element as ue
    f, _ = _model()
    S.enrich_ifc_file(f, [])
    rails = [r for r in f.by_type("IfcRailing") if "Hologram_StairRail" in ue.get_psets(r)]
    wells = [r for r in rails if ue.get_psets(r)["Hologram_StairRail"]["Side"] == "well"]
    assert len(wells) == 2  # one per flight on the well side
    for r in wells:
        lo, hi = _rise(r)
        assert hi - lo > S.RAIL_H + 1.0  # sloped with the flight, not a flat 1 m block at floor level
