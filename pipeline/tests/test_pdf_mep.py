"""pdf_mep on a synthetic pair: an ARK sheet and a ventilation sheet that redraws it (grey, shifted) plus one duct
(two parallel black lines, "400x200") and one air terminal (small square, "+115 l/s")."""
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
    vent = _pdf(tmp_path / "vent.pdf", ops, [(150 + dx, 278 + dy, 6, "400x200"), (418 + dx, 250 + dy, 6, "+115 l/s")])
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
    assert abs(d["width_m"] - 0.353) < 0.02 and abs(d["length_m"] - 7.06) < 0.1
    assert d["label"] == "400x200" and d["height_m"] == pytest.approx(0.2)
    TT = M.terminals(vent, sp["mep"], sp["m_per_pt"])
    assert len(TT) == 1 and TT[0]["airflow_ls"] == 115 and abs(TT[0]["size_m"] - 0.42) < 0.02
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
    n_before = len(ifcopenshell.open(str(ark_ifc)).by_type("IfcProduct"))
    ducts = [{"start_pt": [100, 100], "end_pt": [300, 100], "width_m": 0.4, "height_m": 0.2, "shape": "rect",
              "label": "400x200", "length_m": 7.0},
             {"start_pt": [100, 150], "end_pt": [100, 250], "width_m": 0.25, "diameter_m": 0.25, "shape": "round",
              "label": "ø250", "length_m": 3.5}]
    terms = [{"center_pt": [200, 200], "size_m": 0.4, "shape": "square", "airflow_ls": 115.0, "label": "+115 l/s"}]
    out = M.build_ifc(ark_ifc, ducts, terms, ceiling_height=2.7, out_path=tmp_path / "combined.ifc")
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcDuctSegment")) == 2 and len(f.by_type("IfcAirTerminal")) == 1
    assert len(f.by_type("IfcProduct")) == n_before + 3
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
