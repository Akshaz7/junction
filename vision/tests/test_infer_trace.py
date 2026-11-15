"""Generated for demo proposals; no detector weights or inference required."""
from PIL import Image

from vision.infer_det import DetOnnx, recount


def detector():
    d = object.__new__(DetOnnx)
    d.kinds = ['door']; d.cuts = {'door': .6}; d.floor = .2
    d.raw = lambda images: [[{'kind': 'door', 'conf': .9, 'box': [.1, .1, .3, .3]},
                             {'kind': 'door', 'conf': .8, 'box': [.11, .11, .31, .31]},
                             {'kind': 'door', 'conf': .3, 'box': [.6, .6, .8, .8]}] for _ in images]
    return d


def test_actual_filter_and_dedupe_observations_are_retained():
    d = detector()
    items = d.detect(Image.new('RGB', (100, 100)))
    assert len(items) == 1
    t = d.last_traces[0]
    assert (t['raw_count'], t['after_threshold'], t['dedupe_merged'], t['tiles']) == (3, 2, 1, 1)
    assert t['classes']['door']['score_threshold'] == .6
    assert t['classes']['door']['proposal_score_median'] == .8
    assert t['classes']['door']['retained_score_min'] == .9
    assert t['dedupe']['enabled'] and t['dedupe']['iou'] == .3


def test_recount_provenance_identifies_replaced_classes():
    pm = {'items': [], 'provenance': {'models': {}}}
    updated = recount(pm, Image.new('RGB', (100, 100)), detector(), only=['door'])
    assert updated['provenance']['extraction']['applies_to'] == ['door']
    assert pm == {'items': [], 'provenance': {'models': {}}}


def test_baseline_free_pass_records_actual_merge_then_score_cut():
    from vision.verify import free_pass
    trace = {}
    items = [{'kind': 'door', 'conf': score, 'bbox_px': box} for score, box in [
        (.9, [0, 0, 10, 10]), (.8, [1, 1, 11, 11]), (.5, [50, 50, 60, 60])]]
    assert len(free_pass(items, 100, 100, diagnostics=trace)) == 1
    assert (trace['raw_count'], trace['dedupe_merged'], trace['after_threshold']) == (3, 1, 1)
    assert trace['classes']['door']['after_dedupe'] == 2
    assert trace['classes']['door']['score_threshold'] == .7
