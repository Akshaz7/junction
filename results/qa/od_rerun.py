"""E-41 single frozen opening_design evaluation; no model calls or artifact writes.

PYTHONPATH=. scripts/heavy.sh .venv/bin/python results/qa/od_rerun.py
All development fixtures are generated for demo. Held-out PDFs are read only by
this evaluation, after freezing code. The archived model-backed baseline is
reported separately from the comparable before/after deterministic code routes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
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
from engine.schedules import answer_schedule
from engine.titleblock import answer_text

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/qa'
ARCHIVE = ROOT / 'results/bench/e-s200-z2.rows.jsonl'
BASE = '6ecf793b3e8c5c8e58fe735d541776e53fd50674'
CODE = ['engine/schedules.py', 'engine/titleblock.py', 'engine/answer.py', 'engine/tests/test_od_pdf.py']


def question_class(row):
    q = row['question'].casefold()
    if 'all four walls' in q:
        return 'room finish schedule / all-four-wall predicate'
    if row['type'] == 'count':
        return 'opening schedule / room-mark count'
    if 'largest' in q:
        return 'room finish schedule / largest area'
    return 'room finish schedule / area lookup'


def failure_report(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[question_class(row)].append(row)
    bad = lambda r: r['outcome'] == 'wrong' or r.get('text_verdict') in {'wrong', 'partial'}
    lines = ['# Opening_design PDF failures — E-41', '',
             'Source: `results/bench/e-s200-z2.rows.jsonl`. Gold is copied from the archive only; '
             'it is never supplied to the schedule reader.', '',
             '| Class | Total | Wrong | Partial |', '|---|---:|---:|---:|']
    ranked = sorted(groups.items(), key=lambda pair: (-sum(bad(r) for r in pair[1]), pair[0]))
    for name, values in ranked:
        lines.append(f"| {name} | {len(values)} | {sum(r['outcome'] == 'wrong' or r.get('text_verdict') == 'wrong' for r in values)} | "
                     f"{sum(r.get('text_verdict') == 'partial' for r in values)} |")
    lines += ['', '## Failing examples (up to two per class)', '']
    for name, values in ranked:
        examples = [r for r in values if bad(r)][:2]
        if not examples:
            continue
        lines += [f'### {name}', '']
        for row in examples:
            lines += [f"- Document: `{row['doc_id']}`", f"- Question: {row['question']}",
                      f"- Gold: **{row['gold']}**; ours: **{row['value']}**. Route: `{row['route']}`.",
                      f"- Saved answer: {row['text']}"]
        if len(examples) < 2:
            lines.append('- Only one failing example exists; no second example is invented.')
        lines.append('')
    held = set((ROOT / 'data/sets/heldout_docs.txt').read_text().splitlines())
    lines += ['## Scope and development', '',
              f"- {len(rows)} archived rows; {sum(bad(r) for r in rows)} wrong/partial. "
              f"{len({r['doc_id'] for r in rows})} distinct document(s); "
              f"{len({r['doc_id'] for r in rows} & held)} held out.",
              '- There is only one failing class, so there is no second failure class to rank. '
              'The second development path is the neighboring door/window schedule room-mark count; '
              'its archived door question was already correct.',
              '- Code fixes: require four separately headed wall cells per complete room record; '
              'match finish codes exactly; reject incomplete/merged/duplicate records. '
              'Match opening marks by explicit room column, or exact room-derived marks; honor explicit quantities.',
              '- Room-area lookup and largest-area lookup share those records and preserve printed SF/m² units. '
              'The archived area answer has value 5183 labeled m²; its dataset score checks the number, not units.',
              '- Development uses generated for demo PDFs/tables only. No held-out PDF, image, text artifact or plan map '
              'was inspected to choose the fixes. Title-block behavior remains E-35; no title/scale failure exists in these rows.',
              '- A deterministic lookup returns None on unsupported/incomplete evidence. Production keeps running '
              'the reader and `_answer_forced` (`engine/answer.py`); generated integration tests cover both a reader answer '
              'and a reader abstention followed by the forced rung. Existing vision recount is not bypassed.',
              '- The frozen evaluation compares deterministic code before/after, with the model-backed archive shown '
              'separately. Deferred rows count as incorrect; no archived answer is substituted for a fresh code result. '
              'It does not claim a new production/model accuracy measurement.', '']
    (OUT / 'od-failures.md').write_text('\n'.join(lines))


def baseline_module():
    name = 'engine._od_titleblock_before'
    source = subprocess.check_output(['git', 'show', f'{BASE}:engine/titleblock.py'], cwd=ROOT, text=True)
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / 'engine/titleblock.py')
    sys.modules[name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def deferred(question, ids):
    from engine.answer import _abstained
    return _abstained(question, ids, 'PDF code lookup defers to the production reader/forced ladder.',
                      [], time.perf_counter())


def main():
    output = OUT / 'od-before-after.json'
    if output.exists():
        raise SystemExit('Frozen held-out evaluation already exists; do not rerun/tune it.')
    rows = [json.loads(line) for line in ARCHIVE.read_text().splitlines()
            if json.loads(line)['source'] == 'opening_design']
    questions = [q for q in load_set('sample200') if q['source'] == 'opening_design']
    key = lambda r: (r['doc_id'], r['question'])
    assert Counter(map(key, questions)) == Counter(map(key, rows))
    failure_report(rows)
    old = baseline_module()
    frozen = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in CODE}
    frozen_at = datetime.now(timezone.utc).isoformat()
    results = {}
    with patch('engine.models.call', side_effect=AssertionError('E-41 evaluation forbids model calls')), \
            patch.dict('os.environ', {'MODELS_FAKE': '1'}):
        for phase in ('before', 'after'):
            def answer_fn(question, doc_ids, on_event):
                root = ROOT / 'artifacts'
                result = (old.answer_text(question, doc_ids, root) if phase == 'before' else
                          answer_schedule(question, doc_ids, root) or answer_text(question, doc_ids, root))
                return result or deferred(question, doc_ids)

            result = run(questions, answer_fn=answer_fn, concurrency=1)
            results[phase] = result
            (OUT / f'od-{phase}.rows.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n'
                                                                       for r in result['results']))
    assert frozen == {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in CODE}
    held = set((ROOT / 'data/sets/heldout_docs.txt').read_text().splitlines())
    summary = dict(row='E-41', set='sample200 / opening_design', baseline_commit=BASE,
                   frozen_at=frozen_at, frozen_sha256=frozen,
                   heldout_documents_evaluated=len({r['doc_id'] for r in rows} & held),
                   development_data='generated for demo PDFs and schedules only',
                   method='Single frozen deterministic PDF lookup evaluation, before/after. No model calls. '
                          'Deferred code rows count as incorrect; production reader/forced fallbacks are tested with generated fixtures. '
                          'Archived model-backed production results are separate, not substituted into the after results. '
                          'Text answers remain unjudged in the code-only run.',
                   archive=summarize(rows)['ALL x ALL'],
                   before=results['before']['cells']['ALL x ALL'], after=results['after']['cells']['ALL x ALL'],
                   cells={phase: result['cells'] for phase, result in results.items()},
                   cost_usd=sum(r['totals']['cost_usd'] for r in results.values()),
                   production_artifacts_modified=False)
    before = {key(r): r for r in results['before']['results']}
    after = {key(r): r for r in results['after']['results']}
    summary['rows'] = [dict(doc_id=k[0], question=k[1], gold=before[k]['gold'],
                           before={f: before[k][f] for f in ('outcome', 'value', 'unit', 'route', 'text')},
                           after={f: after[k][f] for f in ('outcome', 'value', 'unit', 'route', 'text')}) for k in before]
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: summary[k] for k in ('archive', 'before', 'after', 'cost_usd')}, indent=2))


if __name__ == '__main__':
    main()
