"""Reproduce IFC quantity pilot and sample200 without modifying shared artifacts.

Run via scripts/heavy.sh; outputs belong only to results/final/IFCQTY.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['before', 'after'])
    ap.add_argument('--fake-pilot', action='store_true')
    ap.add_argument('--set', choices=['pilot', 'sample200', 'both'], default='both')
    a = ap.parse_args()
    from engine import bench, mep
    # The older MEP reader rebuilds its shared sidecar on a miss. Evaluation
    # keeps equivalent rebuilds in memory, leaving other workers' data alone.
    cache, lock = {}, threading.RLock()
    def index(doc):
        with lock:
            if doc.doc_id in cache:
                return cache[doc.doc_id]
            p = ROOT / 'artifacts' / doc.doc_id / 'mep.json'
            existing = json.loads(p.read_text()) if p.exists() else None
            if existing and existing.get('version') == mep.MEP_VERSION:
                cache[doc.doc_id] = existing
            else:
                f = mep._find_ifc(doc.doc_id)
                cache[doc.doc_id] = mep.build(doc.doc_id, f) if f and f.stat().st_size <= 60e6 else None
            return cache[doc.doc_id]
    mep.load_index = index
    out = ROOT / 'results/final/IFCQTY'
    out.mkdir(parents=True, exist_ok=True)
    for name in (['pilot', 'sample200'] if a.set == 'both' else [a.set]):
        os.environ['EXPLAIN'] = '0'
        if name == 'sample200' or a.fake_pilot:
            os.environ['MODELS_FAKE'] = '1'
        else:
            os.environ.pop('MODELS_FAKE', None)
        rows = bench.load_set('sample200') if name == 'sample200' else [json.loads(l) for l in (ROOT / 'results/external/round2/pilot_questions.jsonl').read_text().splitlines()]
        res = bench.run(rows, concurrency=2, max_usd=0.90,
                        progress=lambda n, total, usd: print(f'{name}: {n}/{total}, ${usd:.4f}', flush=True) if n % 20 == 0 else None)
        meta = {(r['doc_id'], r['question']): r for r in rows}
        for r in res['results']:
            m = meta[r['doc_id'], r['question']]
            r['kind'] = m.get('kind', m['type'])
            if name == 'pilot' and r['outcome'] not in ('abstained', 'error') and m['type'] != 'count':
                tolerance = .15 if m.get('tolerance') == '+-15%' else .10
                r['outcome'] = 'correct' if abs(float(r['value']) - float(m['answer'])) <= max(.05, tolerance * abs(float(m['answer']))) else 'wrong'
        groups = collections.defaultdict(collections.Counter)
        for r in res['results']:
            groups[r['kind']][r['outcome']] += 1
        res['by_kind'] = {k: dict(v) for k, v in sorted(groups.items())}
        (out / f'{name}.{a.phase}.json').write_text(json.dumps(res, indent=1) + '\n')
        print(name, json.dumps({'totals':res['totals'], 'by_kind': res['by_kind']}), flush=True)

if __name__ == '__main__':
    main()
