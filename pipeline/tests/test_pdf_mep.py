"""pdf_mep on a synthetic pair: an ARK sheet and a ventilation sheet that redraws it (grey, shifted) plus one duct
(two parallel black lines, "400x200") and one air terminal (small square, "+75 l/s")."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import pdf_mep as M  # noqa: E402
from pipeline.tests.test_pdf_openings import _pdf  # noqa: E402

LABELS = [(80, 330, "B101"), (420, 330, "B102"), (80, 120, "B103"), (420, 120, "B104"), (250, 220, "CORRIDOR"),
          (500, 60, "1:100")]


def _underlay(grey: bool):
    g = "0.5 G" if grey else "0 G"
    ops = [g, "1 w"]
    for x0, y0, x1, y1 in ((50, 50, 550, 350), (60, 60, 540, 340)):     # double exterior wall
        ops.append(f"{x0} {y0} {x1 - x0} {y1 - y0} re S")
    ops += [f"300 60 m 300 340 l S", f"60 200 m 540 200 l S"]
    return ops


def _make_pair(tmp_path, dx=30.0, dy=-20.0):
    ark = _pdf(tmp_path / "ark.pdf", ["0 g"] + _underlay(False), [(x, y, 9, t) for x, y, t in LABELS])
    # vent sheet: underlay redrawn grey and shifted (other sheet frame), MEP in black on top
    ops = [f"q 1 0 0 1 {dx} {dy} cm"] + _underlay(True) + [
        "BT /F1 9 Tf " + " ".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in LABELS[:5]) + " ET", "Q",
        "0 G 1.4 w",
        f"{100 + dx} {260 + dy} m {300 + dx} {260 + dy} l S",          # duct: 200 pt = 7.06 m long
        f"{100 + dx} {270 + dy} m {300 + dx} {270 + dy} l S",          # 10 pt apart = 0.353 m
        f"{100 + dx} {260 + dy} m {100 + dx} {270 + dy} l S",          # end cap
        f"{60 + dx} {300 + dy} m {90 + dx} {330 + dy} l S", f"{70 + dx} {300 + dy} m {100 + dx} {330 + dy} l S",  # leaders
        f"{400 + dx} {250 + dy} 12 12 re S",                          # air terminal symbol 0.42 m
    ]
    vent = _pdf(tmp_path / "vent.pdf", ops, [(150 + dx, 278 + dy, 6, "400x200"), (418 + dx, 250 + dy, 6, "+75 l/s")])
    return ark, vent


def test_align_split_ducts_terminals(tmp_path):
    ark_pdf, vent_pdf = _make_pair(tmp_path)
    ark, vent = M.load(ark_pdf), M.load(vent_pdf)
    T = M.align(vent, ark)
    assert T and T["matches"] >= 4 and T["residual"] < 1.0
    assert abs(T["s"] - 1) < 0.01 and np.allclose(M.apply_T(T, [[130, 100]])[0], [100, 80], atol=1.0)
    sp = M.split_mep(vent, ark)
    assert sp["method"] == "geometric"
    mep_paths = [vent["paths"][i] for i in sp["mep_paths"]]
    assert mep_paths and all(p["stroke"] == (0, 0, 0) for p in mep_paths if p["stroke"] is not None)
    assert not any(vent["paths"][i]["stroke"] == (0, 0, 0) for i in sp["underlay_paths"])
    assert abs(sp["m_per_pt"] - 0.0352778) < 1e-4
    D = M.ducts(vent, sp["mep"], sp["m_per_pt"])
    assert len(D) == 1
    d = D[0]
    assert abs(d["width_drawn_m"] - 0.353) < 0.02 and abs(d["length_m"] - 7.06) < 0.1
    assert d["width_m"] == pytest.approx(0.4)          # printed size wins over the drawn gap
    assert d["label"] == "400x200" and d["height_m"] == pytest.approx(0.2)
    TT = M.terminals(vent, sp["mep"], sp["m_per_pt"])
    assert len(TT) == 1 and TT[0]["airflow_ls"] == 75 and abs(TT[0]["size_m"] - 0.42) < 0.02
    M.overlay(vent, sp["mep"], tmp_path / "o.png", ducts=D, terms=TT)
    assert (tmp_path / "o.png").stat().st_size > 1000


def test_style_fallback_without_ark(tmp_path):
    _, vent_pdf = _make_pair(tmp_path)
    vent = M.load(vent_pdf)
    sp = M.split_mep(vent, None)
    assert sp["method"] == "style" and sp["T"] is None
    assert all(vent["paths"][i]["stroke"] != (128, 128, 128) for i in sp["mep_paths"])


def test_build_ifc_adds_mep_to_ark(tmp_path):
    import ifcopenshell
    import ifcopenshell.util.placement as up
    from pipeline import pdf_to_ifc
    from pipeline.tests.test_pdf_to_ifc import _planmap
    ark_ifc = pdf_to_ifc.build(_planmap(), tmp_path / "ark.ifc")
    n_before = len([p for p in ifcopenshell.open(str(ark_ifc)).by_type("IfcProduct") if not p.is_a("IfcDistributionPort") and not p.is_a("IfcAnnotation")])
    ducts = [{"start_pt": [100, 100], "end_pt": [300, 100], "width_m": 0.4, "height_m": 0.2, "shape": "rect",
              "label": "400x200", "length_m": 7.0},
             {"start_pt": [100, 150], "end_pt": [100, 250], "width_m": 0.25, "diameter_m": 0.25, "shape": "round",
              "label": "ø250", "length_m": 3.5}]
    terms = [{"center_pt": [200, 200], "size_m": 0.4, "shape": "square", "airflow_ls": 75.0, "label": "+75 l/s"}]
    out = M.build_ifc(ark_ifc, ducts, terms, ceiling_height=2.7, out_path=tmp_path / "combined.ifc")
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcDuctSegment")) == 2 and len(f.by_type("IfcAirTerminal")) == 1
    assert len([p for p in f.by_type("IfcProduct") if not p.is_a("IfcDistributionPort") and not p.is_a("IfcAnnotation")]) == n_before + 3
    st = f.by_type("IfcBuildingStorey")[0]
    for e in f.by_type("IfcDuctSegment") + f.by_type("IfcAirTerminal"):
        assert e.ContainedInStructure[0].RelatingStructure == st
    # rectangular duct centre at 2.7 - 0.1 - 0.1 = 2.5 m, x = 100 pt * m_per_pt
    d = f.by_type("IfcDuctSegment")[0]
    loc = d.Representation.Representations[0].Items[0].Position.Location.Coordinates
    assert loc[2] == pytest.approx(2.5) and loc[0] == pytest.approx(100 * 0.0352778, rel=1e-3)
    assert len(ifcopenshell.open(str(ark_ifc)).by_type("IfcDuctSegment")) == 0      # input untouched
    with pytest.raises(ValueError):
        M.build_ifc(ark_ifc, ducts, terms, out_path=ark_ifc)


def _vent_single(tmp_path, extra_labels=True):
    """MEP sheet uploaded on its own: grey underlay + black ducts (an L: 7 m run + 3 m branch) + a terminal."""
    _, vent = _make_pair(tmp_path, dx=0.0, dy=0.0)
    ops = _underlay(True) + [
        "0 G 1.4 w",
        "100 260 m 300 260 l S", "100 270 m 300 270 l S", "100 260 m 100 270 l S",       # 7 m horizontal run
        "300 270 m 300 360 l S", "310 260 m 310 360 l S", "300 360 m 310 360 l S",       # 3 m branch up (y-up pdf)
        "400 250 12 12 re S",
    ]
    texts = [(x, y, 9, t) for x, y, t in LABELS[:5]] + [(150, 278, 6, "400x200"), (418, 250, 6, "+75 l/s")]
    if extra_labels:
        texts += [(320, 300, 6, "2xK3-160"), (430, 300, 6, "-60 l/s"), (200, 300, 6, "Q4-200")]
    return _pdf(tmp_path / "vent_single.pdf", ops, texts)


def test_single_sheet_detect_and_enrich(tmp_path):
    import ifcopenshell
    from pipeline import pdf_to_ifc
    from pipeline.tests.test_pdf_to_ifc import _planmap
    pdf = _vent_single(tmp_path)
    assert M.is_mep_sheet(pdf, 0)
    pm = _planmap()
    pm["scale"].update(m_per_px=0.02, m_per_pt=0.02)      # 1 pt = 1 px = 2 cm: walls 10.4 x 8.8 m around the ducts
    ifc = pdf_to_ifc.build(pm, tmp_path / "model.ifc")
    n0 = len(ifcopenshell.open(str(ifc)).by_type("IfcProduct"))
    rep = M.enrich_ifc(ifc, pdf, 0, pm)
    assert rep["ok"] and rep["ducts"] == 2 and rep["terminals"] == 1 and rep["fittings"] == 1
    f = ifcopenshell.open(str(ifc))
    segs, fits, terms = f.by_type("IfcDuctSegment"), f.by_type("IfcDuctFitting"), f.by_type("IfcAirTerminal")
    assert len(segs) == 2 and len(fits) == 1 and len(terms) == 1
    import ifcopenshell.util.element as ue0
    assert ue0.get_predefined_type(fits[0]) == "BEND"          # on the occurrence or its type (ifc_enrich.mep_native)
    assert len([p for p in f.by_type("IfcProduct") if not p.is_a("IfcDistributionPort")]) == n0 + 4
    sysm = f.by_type("IfcDistributionSystem")
    assert len(sysm) == 1 and sysm[0].PredefinedType == "VENTILATION"
    grp = [r for r in f.by_type("IfcRelAssignsToGroup") if r.RelatingGroup == sysm[0]]
    assert grp and set(grp[0].RelatedObjects) == set(segs + fits + terms)
    import ifcopenshell.util.element as ue
    ps = ue.get_psets(next(s for s in segs if s.Name == "400x200"))
    assert ps["Pset_DuctSegmentTypeCommon"]["Shape"] == "RECTANGULAR"
    pd_ = ps["Pset_DuctSegmentTypeCommon"]     # label 400x200 on a run drawn 0.2 m wide: 200 across, 400 high
    assert pd_["NominalDiameterOrWidth"] == pytest.approx(0.2) and pd_["NominalHeight"] == pytest.approx(0.4)
    # duct tops in the ceiling void: 0.1 m under the storey's wall height
    import ifcopenshell.util.shape  # noqa: F401
    st_h = (ue.get_psets(f.by_type("IfcBuildingStorey")[0]).get("Hologram_StoreySource") or {}).get("WallHeight", 2.7)
    for s in segs:
        it = s.Representation.Representations[0].Items[0]
        z = it.Position.Location.Coordinates[2]
        assert z + it.SweptArea.YDim / 2 == pytest.approx(st_h - 0.1)


def test_plain_sheets_are_not_mep(tmp_path):
    ark_pdf, _ = _make_pair(tmp_path)
    assert not M.is_mep_sheet(ark_pdf, 0)
    # MEP drawing without MEP text (labels missing) is not called an MEP sheet either: precision first
    assert not M.is_mep_sheet(_vent_single(tmp_path, extra_labels=False), 0)
    # and nothing is added to an IFC when the page has no MEP layer
    from pipeline import pdf_to_ifc
    from pipeline.tests.test_pdf_to_ifc import _planmap
    pm = _planmap()
    ifc = pdf_to_ifc.build(pm, tmp_path / "plain.ifc")
    before = (tmp_path / "plain.ifc").read_bytes()
    rep = M.enrich_ifc(ifc, ark_pdf, 0, pm)
    assert rep["ducts"] == 0 and (tmp_path / "plain.ifc").read_bytes() == before


def test_mep_lengths_file_only_with_solid_scale(tmp_path):
    import json
    from pipeline import pdf_to_ifc
    from pipeline.tests.test_pdf_to_ifc import _planmap
    pdf = _vent_single(tmp_path)
    pm = _planmap()
    pm["scale"].update(m_per_px=0.02, m_per_pt=0.02)          # confident plan-map scale (printed, 0.98)
    ifc = pdf_to_ifc.build(pm, tmp_path / "model.ifc")
    rep = M.enrich_ifc(ifc, pdf, 0, pm)
    f = tmp_path / "mep-lengths.json"
    assert rep["lengths_file"] == str(f)
    runs = json.loads(f.read_text())["runs"]
    assert {r["kind"] for r in runs} == {"duct"} and all(r["source"] == "pdf_mep" and r["page"] == 1 for r in runs)
    import ifcopenshell
    ids = {e.GlobalId for e in ifcopenshell.open(str(ifc)).by_type("IfcDuctSegment")}
    assert {pdf_to_ifc.guid_for("synthetic", r["item_id"], 1) for r in runs} == ids     # same ids as the IFC
    by_len = sorted(r["length_m"] for r in runs)
    assert by_len == pytest.approx([1.8, 4.0], abs=0.05)     # 90 pt and 200 pt at 2 cm/pt
    h = next(r for r in runs if r["length_m"] > 3)
    assert h["bbox_px"] == pytest.approx([100, 130, 300, 140], abs=1.0)   # image 600 px for a 600 pt page
    # a guessed scale (door guess) and no agreeing printed duct sizes: no file, the engine abstains
    pm2 = _planmap()
    pm2["scale"].update(m_per_px=0.02, m_per_pt=0.02, method="door guess", confidence=0.3)
    ifc2 = pdf_to_ifc.build(pm2, tmp_path / "g" / "model.ifc")
    rep2 = M.enrich_ifc(ifc2, pdf, 0, pm2)
    assert rep2["lengths_file"] is None and not (tmp_path / "g" / "mep-lengths.json").exists()
    # label calibration: 3 runs whose printed size agrees with the drawn width give a solid scale
    D = [{"label_across_m": 0.4, "width_pt": 20.0}, {"label_across_m": 0.2, "width_pt": 10.2},
         {"label_across_m": 0.25, "width_pt": 12.4}]
    assert M.label_scale(D) == pytest.approx(0.02, rel=0.03) and M.label_scale(D[:2]) is None
