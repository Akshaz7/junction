"""Production-graph scoring must not convert unknown source truth into success."""
from importlib import import_module

import pytest

from scripts.kg_eval import calibration_scores, graph_audit, heldout


def test_known_graph_pairs_unknown_pairs_and_zero_denominators(tmp_path, monkeypatch):
    nodes = []
    for did, identity in (("a", "G"), ("b", "G"), ("c", None)):
        nodes.append({"id": did, "kind": "door", "source": {"doc_id": did, "item_id": "door-1"},
                      "props": {"guid": identity} if identity else {}})
    edges = [{"id": "known", "kind": "same_as", "from": "a", "to": "b", "method": "guid",
              "confidence": 1, "evidence": {"guid": "G"}},
             {"id": "unknown", "kind": "same_as", "from": "b", "to": "c", "method": "position",
              "confidence": .5, "evidence": {"residual_m": 0}}]
    module = import_module("engine.kg.build")
    monkeypatch.setattr(module, "build_uncached", lambda *_: {"nodes": nodes, "edges": edges, "stats": {}})
    report = graph_audit(tmp_path, {"id": "audit"})
    assert report["same_as"]["guid"]["precision"] == 1
    assert report["same_as"]["guid"]["recall"] == 1
    assert report["same_as"]["position"]["unknown"] == 1
    assert report["same_as"]["position"]["precision"] is None
    assert report["same_as_all_methods"]["unknown"] == 1
    assert report["relation_samples"]["serves"]["sample_size"] == 0


def test_heldout_metadata_missing_fails_closed(tmp_path):
    assert heldout(tmp_path, "unregistered", set())


def test_brier_and_ece_match_a_known_example():
    observations = [{"method": "guid", "residual_m": 0, "correct": value, "heldout": True}
                    for value in (True, False)]
    scores = calibration_scores(observations, lambda *_: .75)["heldout"]["guid"]
    assert scores["brier"] == pytest.approx(.3125)
    assert scores["ece"] == pytest.approx(.25)
    assert scores["n"] == 2
