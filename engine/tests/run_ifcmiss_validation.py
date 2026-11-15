"""Read-only final IFC regression runner. Invoke through scripts/heavy.sh."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BENCH = Path('/private/tmp/claude-501/-Users-akshatthapa-Workspace-junction-server/bb83e630-bcda-48d0-8000-9c87e8300b2a/scratchpad/bench')
OUT = ROOT / 'results/final/IFCMISS'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['before', 'after'])
    ap.add_argument('--suite', choices=['ifc', 'sample200'], default='ifc')
    args = ap.parse_args()
    banned = set((BENCH / 'forbidden_heldout_docs.txt').read_text().split())
    blind = json.loads((OUT / 'selection.json').read_text())['blind_doc_id']
    os.environ.update(MODELS_FAKE='1', EXPLAIN='0')
    from engine import bench
    if args.suite == 'ifc':
        original = [json.loads(l) for kind in ('ifc_count', 'ifc_area')
                    for l in (BENCH / 'out' / (kind + '.rows.jsonl')).read_text().splitlines()]
        rows = [{**r, 'answer': r['gold']} for r in original]
    else:
        rows = bench.load_set('sample200')
    rows = [r for r in rows if r['doc_id'] not in banned and r['doc_id'] != blind]
    rows.sort(key=lambda r: (re.sub(r'-plan-\d+-.*$', '', r['doc_id']), r['doc_id'], r['type']))
    # Only allowed documents can be seen by global search. JSON copies keep
    # lazy index/recount writes away from shared artifacts; assets stay read-only.
    with tempfile.TemporaryDirectory(prefix='ifcmiss-bench-') as tmp:
        root = Path(tmp)
        ids = {r['doc_id'] for r in rows}
        ids |= {re.sub(r'-plan-\d+-.*$', '', did) for did in ids}
        assert not ids & banned and blind not in ids
        for did in sorted(ids):
            src = ROOT / 'artifacts' / did
            if not src.is_dir():
                continue
            dest = root / did
            dest.mkdir()
            for p in src.iterdir():
                if p.is_file():
                    if p.suffix in ('.json', '.jsonl'):
                        shutil.copyfile(p, dest / p.name)
                    else:
                        (dest / p.name).symlink_to(p.resolve())
        os.environ['ARTIFACTS_DIR'] = tmp
        from engine.answer import answer
        results = []
        output = OUT / f'{args.suite}.{args.phase}.rows.jsonl'
        with output.open('w') as stream:
            for n, row in enumerate(rows, 1):
                result = bench._one(row, answer, judge=False)
                results.append(result)
                stream.write(json.dumps(result) + '\n')
                stream.flush()
                if n % 10 == 0 or result['error']:
                    print(f'{args.phase}/{args.suite}: {n}/{len(rows)} {row["doc_id"]} {result["outcome"]}', flush=True)
    summary = {'n': len(results), 'outcomes': dict(Counter(r['outcome'] for r in results)),
               'cells': bench.summarize(results), 'fake': True, 'forbidden_evaluated': 0,
               'blind_evaluated': False, 'shared_artifacts_written': False,
               'cost_usd': sum(r['cost_usd'] for r in results)}
    (OUT / f'{args.suite}.{args.phase}.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
