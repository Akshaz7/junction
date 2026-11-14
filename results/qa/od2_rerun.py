"""E-48 single frozen evaluation; development uses generated for demo PDFs only.

PYTHONPATH=. scripts/heavy.sh .venv/bin/python results/qa/od2_rerun.py
No tuning or reruns after this evaluation. Gold goes only to the numeric scorer.
This measures deterministic coverage, not the unmeasured production model ladder.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types
from unittest.mock import patch

from engine.bench import load_set, run, summarize
from engine.reader.tables import _cache
from engine.schedules import answer_schedule
from engine.titleblock import answer_text

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/qa'
BASE = 'b155e6b878c4d9d2c0a190e33c9f007112c1d19c'
CODE = ['engine/schedules.py', 'engine/titleblock.py', 'engine/reader/text.py',
        'engine/reader/tables.py', 'engine/tests/test_od_pdf.py']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_module(name):
    module_name = f'engine._od2_before_{name}'
    source = subprocess.check_output(['git', 'show', f'{BASE}:engine/{name}.py'], cwd=ROOT)
    module = types.ModuleType(module_name)
    module.__file__ = str(ROOT / f'engine/{name}.py')
    sys.modules[module_name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module, hashlib.sha256(source).hexdigest()


def defer(question, ids):
    from engine.answer import _abstained
    return _abstained(question, ids, 'PDF code lookup defers to the production reader/forced ladder.',
                      [], time.perf_counter())


def main():
    output = OUT / 'od2-before-after.json'
    freeze_file = OUT / 'od2-frozen.json'
    if output.exists() or freeze_file.exists():
        raise SystemExit('E-48 frozen evaluation already started; do not rerun or tune on held-out results.')
    before_text, text_hash = baseline_module('titleblock')
    with patch.dict(sys.modules, {'engine.titleblock': before_text}):
        before_schedules, schedule_hash = baseline_module('schedules')
    frozen = {name: digest(ROOT / name) for name in CODE}
    freeze = dict(row='E-48', frozen_at=datetime.now(timezone.utc).isoformat(),
                  frozen_sha256=frozen, baseline_commit=BASE,
                  baseline_sha256={'engine/schedules.py': schedule_hash, 'engine/titleblock.py': text_hash},
                  development_data='generated for demo PDFs and tables only; no held-out source inspection')
    with freeze_file.open('x') as f:
        f.write(json.dumps(freeze, indent=2) + '\n')

    held = set((ROOT / 'data/sets/heldout_docs.txt').read_text().splitlines())
    questions = [q for q in load_set('sample200') if q['source'] == 'opening_design' and q['doc_id'] in held]
    archive = [json.loads(line) for line in (ROOT / 'results/bench/e-s200-z2.rows.jsonl').read_text().splitlines()]
    archive = [r for r in archive if r['source'] == 'opening_design' and r['doc_id'] in held]
    key = lambda r: (r['doc_id'], r['question'])
    assert questions and Counter(map(key, questions)) == Counter(map(key, archive))
    assert 'opening_design__generated-schedules-demo' not in held
    artifacts = [p for did in {q['doc_id'] for q in questions} for p in (ROOT / 'artifacts' / did).iterdir() if p.is_file()]
    stamps = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in artifacts}
    results = {}
    with patch('engine.models.call', side_effect=AssertionError('E-48 evaluation forbids model calls')), \
            patch.dict('os.environ', {'MODELS_FAKE': '1'}):
        for phase in ('before', 'after'):
            _cache.clear()  # neither phase reuses tables constructed with the other's text grouping

            def answer_fn(question, ids, on_event):
                root = ROOT / 'artifacts'
                schedule, title = ((before_schedules.answer_schedule, before_text.answer_text)
                                   if phase == 'before' else (answer_schedule, answer_text))
                return schedule(question, ids, root) or title(question, ids, root) or defer(question, ids)

            result = run(questions, answer_fn=answer_fn, concurrency=1)
            results[phase] = result
            (OUT / f'od2-{phase}.rows.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n'
                                                                        for r in result['results']))
    assert frozen == {name: digest(ROOT / name) for name in CODE}, 'Frozen solver code changed during evaluation'
    assert stamps == {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in artifacts}
    summary = dict(**freeze, set='sample200 / held-out opening_design',
                   heldout_documents_evaluated=len({q['doc_id'] for q in questions}),
                   method='One frozen before/after deterministic evaluation. Gold is never passed to the lookup. '
                          'Numeric deferrals count as incorrect; text answers remain unjudged. '
                          'No model calls or held-out artifact writes. Production reader/forced rungs are '
                          'verified with generated fixtures, not remeasured on held-out rows.',
                   changes=['Verified mirrored room-number columns; directional wall header aliases.',
                            'Rotated PDF heading grouping; explicit square-foot/metre column units.',
                            'Room-specific area lookup tolerates missing unrelated areas; largest still requires all.',
                            'Unknown wall finishes, malformed numbers and conflicting units defer.'],
                   archive=summarize(archive)['ALL x ALL'],
                   before=results['before']['cells']['ALL x ALL'], after=results['after']['cells']['ALL x ALL'],
                   cells={phase: result['cells'] for phase, result in results.items()},
                   cost_usd=sum(r['totals']['cost_usd'] for r in results.values()),
                   production_artifacts_modified=False,
                   unit_note='The archive labels its numeric area answer m²; code preserves printed units. '
                             'The dataset numeric scorer compares values and does not score units.')
    before = {key(r): r for r in results['before']['results']}
    after = {key(r): r for r in results['after']['results']}
    fields = ('outcome', 'value', 'unit', 'route', 'text', 'confidence', 'boxes', 'text_verdict', 'error')
    summary['rows'] = [dict(doc_id=k[0], question=k[1], gold=before[k]['gold'],
                           before={f: before[k][f] for f in fields}, after={f: after[k][f] for f in fields})
                       for k in before]
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: summary[k] for k in ('before', 'after', 'cost_usd')}, indent=2))


if __name__ == '__main__':
    main()
