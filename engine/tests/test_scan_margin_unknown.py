"""A scan/detector count whose only check is box coverage must not show a margin of 0."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_evint_round3 as t  # noqa: E402
from engine import scan_calc  # noqa: E402
from engine.reasoning_parts import confidence  # noqa: E402


def test_coverage_only_margin_is_unknown_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr('engine.scan_uncertainty.historical', lambda *a, **k: None)
    r = t.counted(tmp_path)
    r['reasoning'].pop('margin', None)
    r['trace'] = [x for x in r['trace'] if x.get('step') != 'recount']
    scan_calc.attach(r, 'How many doors?', tmp_path)
    confidence.attach(r, 'How many doors?', tmp_path)
    m = r['reasoning']['margin']
    assert m['rule'] == 'coverage_only_margin_unknown'
    assert m['value'] is None and m['pct'] is None
    assert 'unknown' in m['why']


def test_recount_difference_still_drives_the_margin(tmp_path):
    r = t.counted(tmp_path, recount=3)
    scan_calc.attach(r, 'How many doors?', tmp_path)
    assert r['reasoning']['margin']['value'] == 1
