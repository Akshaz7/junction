"""F-WOHNEN: compare public answers using isolated artifact copies, no live calls."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['MODELS_FAKE'] = '1'
from engine.answer import answer
from engine.bench import run

OUT = ROOT / 'results/final/WOHNEN'
phase = sys.argv[1]
selection = json.loads((OUT / 'selection.json').read_text())
sample = [json.loads(l) for l in (ROOT / 'data/sets/sample200.jsonl').read_text().splitlines()]
all_rows = [json.loads(l) for l in (ROOT / 'data/sets/questions_en.full.jsonl').read_text().splitlines()]
docs = selection['swiss_development_docs'] + ['swiss_dwellings__site236-bldg436-floor1710']
if phase == 'after':
    docs.append(selection['reserved_unseen_doc'])
swiss = [r for r in all_rows if r['doc_id'] in docs and r['type'] == 'count'
         and any(t in r['question'] for t in ["'Wohnen'", "'Zimmer'", "'Bad'"])]
with tempfile.TemporaryDirectory(prefix='wohnen-validation-') as scratch:
    root = Path(scratch)
    os.environ['ARTIFACTS_DIR'] = str(root)
    os.environ['MODELS_CACHE_DIR'] = str(root / 'cache')
    os.environ['MODELS_COSTS_LOG'] = str(root / 'costs.jsonl')
    for did in {r['doc_id'] for r in sample + swiss}:
        src = ROOT / 'artifacts' / did
        if not src.is_dir():
            continue
        dst = root / did
        dst.mkdir()
        for p in src.iterdir():
            if p.suffix == '.json':
                shutil.copyfile(p, dst / p.name)
            elif p.suffix in {'.png', '.glb'}:
                (dst / p.name).symlink_to(p.resolve())
    for name, rows in [('sample200', sample), ('swiss', swiss)]:
        result = run(rows, answer_fn=lambda q, ds, history: answer(q, ds, history=history), concurrency=2)
        (OUT / f'{name}-{phase}.json').write_text(json.dumps(result, indent=2) + '\n')
        print(name, phase, result['cells']['ALL x ALL'], flush=True)

if phase == 'after':
    comparison = {}
    for name in ['sample200', 'swiss']:
        before = json.loads((OUT / f'{name}-before.json').read_text())
        after = json.loads((OUT / f'{name}-after.json').read_text())
        indexed = {(r['doc_id'], r['question']): r for r in after['results']}
        transitions = []
        worse = []
        for old in before['results']:
            new = indexed[old['doc_id'], old['question']]
            if old['outcome'] != new['outcome'] or old['value'] != new['value']:
                transitions.append({'doc_id': old['doc_id'], 'question': old['question'], 'gold': old['gold'],
                                    'before': old['value'], 'after': new['value'],
                                    'outcome_before': old['outcome'], 'outcome_after': new['outcome']})
            if old['outcome'] == 'correct' and new['outcome'] != 'correct':
                worse.append(transitions[-1])
        comparison[name] = {'before': before['cells']['ALL x ALL'], 'after': after['cells']['ALL x ALL'],
                            'correct_to_not_correct': len(worse), 'changes': transitions,
                            'sources': sorted({r['source'] for r in after['results']})}
        assert not worse, worse
    unseen = [r for r in indexed.values() if r['doc_id'] == selection['reserved_unseen_doc']]
    comparison['reserved_unseen'] = {'doc_id': selection['reserved_unseen_doc'], 'questions': len(unseen),
                                     'correct': sum(r['outcome'] == 'correct' for r in unseen)}
    (OUT / 'comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
    print('Correct-to-not-correct:', {k: comparison[k]['correct_to_not_correct'] for k in ['sample200', 'swiss']})
