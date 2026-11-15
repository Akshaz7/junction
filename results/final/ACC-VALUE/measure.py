"""ACC-VALUE measurement only; filters the forbidden ids before any artifact access.

MODELS_FAKE=1 scripts/heavy.sh .venv/bin/python results/final/ACC-VALUE/measure.py \
  --bench-dir /path/to/scratchpad/bench --tag after
Run from the worktree root. Does not modify shared source artifacts.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def category(row):
    q = row['question'].lower()
    if row['type'] == 'count' and row['gold'] == 0:
        return 'zero_count'
    if row['source'] == 'swiss_dwellings' and row['type'] == 'area' and 'apartment' in q:
        return 'apartment_area'
    if 'rooms (spaces)' in q:
        return 'rooms_spaces'
    if row['type'] == 'count' and any(s in q for s in ('plumbing', 'mep', 'sanitary', 'pipe')):
        return 'mep_count'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench-dir', type=Path, required=True)
    ap.add_argument('--tag', required=True)
    args = ap.parse_args()
    forbidden = set((args.bench_dir / 'forbidden_heldout_docs.txt').read_text().split())
    rows = []
    for file in sorted((args.bench_dir / 'out').glob('*.rows.jsonl')):
        for line in file.open():
            row = json.loads(line)
            if row['doc_id'] not in forbidden and category(row):
                rows.append(dict(row, category=category(row), answer=row['gold']))
    sample = []
    for line in (ROOT / 'data/sets/sample200.jsonl').open():
        row = json.loads(line)
        if row['doc_id'] not in forbidden:
            sample.append(row)
    doc_ids = {r['doc_id'] for r in sample + rows}
    for did in list(doc_ids):
        m = re.match(r'^(.+?)-plan-\d+-', did)
        if m:
            doc_ids.add(m[1])
    if doc_ids & forbidden:
        raise RuntimeError('An excluded parent would be accessed; refusing this measurement.')
    root = Path(tempfile.mkdtemp(prefix='acc-value-artifacts-'))
    fingerprints = {}
    for did in sorted(doc_ids):
        source = ROOT / 'artifacts' / did
        if source.is_dir():
            (root / did).symlink_to(source.resolve(), target_is_directory=True)
            files = [source / 'doc.json', source / 'elements.json', *source.glob('planmap-*.json'), *source.glob('text-*.json')]
            fingerprints[did] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}
    os.environ['ARTIFACTS_DIR'] = str(root)
    os.environ['MODELS_FAKE'] = '1'
    from engine.answer import answer
    from engine.bench import _one, summarize
    out = {'metadata': {'models_fake': True, 'features': 'product defaults', 'concurrency': 1,
                        'origins': sorted({r['source'] for r in sample + rows}), 'fingerprints': fingerprints}}
    for name, inputs in [('sample200', sample), ('categories', rows)]:
        results = []
        for i, row in enumerate(inputs):
            ans = answer(row['question'], [row['doc_id']])
            result = _one(row, lambda *a: ans, judge=False)
            result['category'] = row.get('category')
            result['trace'] = ans.get('trace', [])
            results.append(result)
            if (i + 1) % 25 == 0:
                print(name, i + 1, len(inputs), flush=True)
        out[name] = {'rows': results, 'summary': summarize(results)}
        print(name, Counter(r['outcome'] for r in results), flush=True)
    output = Path(__file__).parent / (args.tag + '.json')
    output.write_text(json.dumps(out, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
