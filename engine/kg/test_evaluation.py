"""Evaluation errors could manufacture accuracy; exercise the truth boundary."""
import math

import pytest

from engine.kg.evaluation import Case, Item, align, evaluate, fit_table, metrics, plan_items, svg_items
from engine.kg import confidence as confidence_module


def test_metrics_deduplicate_and_empty_denominators():
    assert metrics(set(), set())["precision"] is None
    assert metrics({("a", "b")}, set())["fp"] == 1


def test_plan_ids_are_not_truth_and_unknown_is_not_correct():
    plan = {"items": [{"item_id": "door-1", "source": "dxf", "kind": "door"}]}
    item = plan_items(plan)[0]
    assert item.identity is None
    _, obs = evaluate(Case("unknown", [item], [item]))
    assert obs == []


def test_position_repeated_labels_and_level_separation():
    a = [Item("a", "truth-a", "door", "EG", "Door", xy=(0., 0.)),
         Item("b", "truth-b", "door", "OG", "Door", xy=(0., 0.))]
    b = [Item("x", "truth-a", "door", "EG", "Door", xy=(0., .01)),
         Item("y", "truth-b", "door", "OG", "Door", xy=(0., .01))]
    report, _ = evaluate(Case("floors", a, b))
    assert report["methods"]["position"]["tp"] == 2
    assert report["methods"]["position"]["fp"] == 0


def test_tied_positions_abstain_instead_of_using_order():
    a = [Item("a", "A", "door", "EG", xy=(0., 0.))]
    b = [Item("b", "A", "door", "EG", xy=(1., 0.)), Item("c", "C", "door", "EG", xy=(-1., 0.))]
    report, _ = evaluate(Case("tie", a, b))
    assert report["methods"]["position"]["predicted"] == 0


def test_calibration_cannot_use_heldout():
    obs = [{"method": "guid", "residual_m": 0, "correct": True, "heldout": True}]
    assert fit_table(obs)["guid"][0]["probability"] is None
    obs.append({**obs[0], "heldout": False, "correct": False})
    assert fit_table(obs)["guid"][0]["probability"] == pytest.approx(1 / 3)


def test_position_calibration_monotonic_pooling():
    obs = [{"method": "position", "residual_m": residual, "correct": value, "heldout": False}
           for residual, value in [(0.001, False), (.03, True), (.1, False)]]
    entries = fit_table(obs)["position"]
    assert entries[0]["probability"] == entries[1]["probability"]
    assert entries[1]["probability"] >= entries[2]["probability"]
    assert entries[-1]["probability"] is None


def test_svg_straight_geometry_only_and_transforms_are_not_ignored(tmp_path):
    p = tmp_path / "test.svg"
    p.write_text('<svg><g data-guid="A" class="IfcDoor"><path d="M1,2 L3,4 Z"/></g>'
                 '<g transform="translate(2,3)"><g data-guid="B"><path d="M0,0 L4,4"/></g></g>'
                 '<g data-guid="C"><path d="M0,0 C1,2 3,4 5,6"/></g></svg>')
    assert [i.id for i in svg_items(p)] == ["A"]
    assert svg_items(p)[0].xy == (2, 3)


def test_alignment_never_scores_its_anchors():
    a = [Item(str(i), str(i), "room", "G", xy=(float(i % 5), float(i // 5))) for i in range(20)]
    b = [Item(i.id, i.identity, i.kind, i.level, xy=(2 * i.xy[0] + 3, -2 * i.xy[1] - 4)) for i in a]
    aa, bb, evidence = align(a, b)
    assert evidence["residual_m"] < 1e-10
    assert not set(evidence["anchor_ids"]) & {i.id for i in aa}
    assert len(aa) == len(bb) == evidence["withheld"]
    assert all(math.dist(x.xy, y.xy) < 1e-10 for x, y in zip(aa, bb))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "0.1"])
def test_invalid_position_confidence(value):
    assert confidence_module.confidence("position", value) == 0


def test_uncalibrated_estimate_and_bad_alignment(monkeypatch):
    monkeypatch.setattr(confidence_module, "CALIBRATION", {"position": [
        {"max_residual_m": .1, "n": 100, "probability": .99}]})
    assert confidence_module.confidence("position", .01) == .99
    assert confidence_module.confidence("position", 1) == .5
    assert confidence_module.confidence("position", .01, alignment={"matches": 2, "residual_m": 0}) == 0
    assert confidence_module.confidence("made_up") == .5
