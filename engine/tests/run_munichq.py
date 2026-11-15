"""F-MUNICHQ before/after checks. Run through scripts/heavy.sh; no shared writes."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['MODELS_FAKE'] = '1'
os.environ['EXPLAIN'] = '0'
OUT = ROOT / 'results/final/MUNICHQ'
QUESTIONS = [
    'What is this drawing?',
    'How many linear metres of baseboard do I need?',
    'What is the total length of pipes or ducts?',
    'What is the fire rating of the doors in the third basement?',
]


def compact_case(a):
    """Keep source evidence and answers; omit large duplicate UI/calculation payloads."""
    result={k:a[k] for k in ('question','doc_ids','answer','route','trace','citations','quantity_rows','ifc_overview') if k in a}
    card=a.get('reasoning') or {}
    result['validation']={'confidence_label':(card.get('confidence') or {}).get('label'),
                          'calc_status':(card.get('calc') or {}).get('status'),
                          'calc_issues':(card.get('calc') or {}).get('issues')}
    return result


def main():
    from engine.answer import answer
    from engine import bench, mep
    phase = sys.argv[1]
    # Old MEP indexes can rebuild shared sidecars on a miss: keep rebuilds in memory.
    cache = {}
    def index(doc):
        if doc.doc_id not in cache:
            p = ROOT / 'artifacts' / doc.doc_id / 'mep.json'
            old = json.loads(p.read_text()) if p.exists() else None
            f = mep._find_ifc(doc.doc_id)
            cache[doc.doc_id] = old if old and old.get('version') == mep.MEP_VERSION else mep.build(doc.doc_id, f) if f and f.stat().st_size < 60e6 else None
        return cache[doc.doc_id]
    mep.load_index = index
    cases = []
    documents=['ifc_bench__city-house-munich-arc', 'ifc_bench__ac20-arc', 'ext_ifcr2__schependomlaan-design']
    if phase == 'after':
        documents.append('ext_ifcr2__bsi-ifc4-building-architecture')
    for did in documents:
        for q in QUESTIONS:
            a = answer(q, [did])
            cases.append(a)
            print(did, q, a['answer'], flush=True)
    (OUT / f'questions.{phase}.json').write_text(json.dumps([compact_case(a) for a in cases], indent=1) + '\n')
    res = bench.run(bench.load_set('sample200'), concurrency=2, max_usd=.01,
                    progress=lambda n,total,usd: print(f'{n}/{total}', flush=True) if n % 40 == 0 else None)
    (OUT / f'sample200.{phase}.json').write_text(json.dumps(res, indent=1) + '\n')
    print(res['totals'], flush=True)
    if phase == 'after':
        before = json.loads((OUT / 'sample200.before.json').read_text())
        gold = {(r['doc_id'], r['question']): r for r in before['results']}
        regressions = [r for r in res['results'] if gold[r['doc_id'], r['question']]['outcome'] == 'correct' and r['outcome'] != 'correct']
        (OUT / 'regressions.json').write_text(json.dumps(regressions, indent=1) + '\n')
        print('correct-to-wrong:', len(regressions), flush=True)
        if regressions:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
