"""ACC-IFC measurement runner. Run with scripts/heavy.sh; shared data stays read-only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'results/final/ACC-IFC'
FORBIDDEN = Path('/private/tmp/claude-501/-Users-akshatthapa-Workspace-junction-server/bb83e630-bcda-48d0-8000-9c87e8300b2a/scratchpad/bench/forbidden_heldout_docs.txt')


def forbidden():
    # Fail closed if the independently maintained benchmark exclusions disappear.
    return set(FORBIDDEN.read_text().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['before', 'after'])
    ap.add_argument('--baseline', help='Run the unchanged Python source of this git revision in a temporary directory')
    args = ap.parse_args()
    if args.baseline:
        # Archive source/configuration only, never dataset fixtures or labels.
        names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', args.baseline, 'engine', 'pipeline', 'vision'], cwd=ROOT, text=True).splitlines()
        names = [n for n in names if Path(n).suffix in ('.py', '.yaml', '.yml', '.txt')
                 and not any(p in Path(n).parts for p in ('tests', 'fixtures', 'labels'))]
        with tempfile.TemporaryDirectory(prefix='acc-ifc-baseline-') as tmp:
            base = Path(tmp)
            archive = base / 'source.tar'
            with archive.open('wb') as stream:
                subprocess.run(['git', 'archive', args.baseline, '--', *names], cwd=ROOT, stdout=stream, check=True)
            with tarfile.open(archive) as stream:
                stream.extractall(base, filter='data')
            (base / 'engine/tests').mkdir(parents=True, exist_ok=True)
            shutil.copyfile(__file__, base / 'engine/tests/run_acc_ifc_validation.py')
            dest = base / 'results/final/ACC-IFC'
            dest.mkdir(parents=True)
            shutil.copyfile(OUT / 'selection.json', dest / 'selection.json')
            for name in ('data', 'artifacts'):
                (base / name).symlink_to((ROOT / name).resolve(), target_is_directory=True)
            subprocess.run([sys.executable, str(base / 'engine/tests/run_acc_ifc_validation.py'), args.phase], cwd=base,
                           env={**os.environ, 'MODELS_FAKE': '1', 'PYTHONPATH': str(base)}, check=True)
            output = json.loads((dest / f'sample200.{args.phase}.json').read_text())
            output['baseline_revision'] = args.baseline
            (OUT / f'sample200.{args.phase}.json').write_text(json.dumps(output, indent=1)+'\n')
        return
    banned = forbidden()
    blind = json.loads((OUT / 'selection.json').read_text())['blind']['doc_id']
    os.environ.update(MODELS_FAKE='1', EXPLAIN='0')
    from engine import bench, mep
    rows = [r for r in bench.load_set('sample200') if r['doc_id'] not in banned and r['doc_id'] != blind]
    # Only the selected, permitted documents are visible to global search fallbacks.
    # Individual file symlinks prevent a cache miss from writing into shared data.
    with tempfile.TemporaryDirectory(prefix='acc-ifc-bench-') as tmp:
        root = Path(tmp)
        for did in {r['doc_id'] for r in rows}:
            src = ROOT / 'artifacts' / did
            if not src.is_dir():
                continue
            (root / did).mkdir()
            for p in src.iterdir():
                if p.is_file():
                    if p.suffix in ('.json', '.jsonl'):
                        shutil.copyfile(p, root / did / p.name)
                    else:
                        (root / did / p.name).symlink_to(p.resolve())
        os.environ['ARTIFACTS_DIR'] = tmp
        cache, lock = {}, threading.RLock()
        def index(doc):
            with lock:
                if doc.doc_id not in cache:
                    p = root / doc.doc_id / 'mep.json'
                    existing = json.loads(p.read_text()) if p.exists() else None
                    if existing and existing.get('version') == mep.MEP_VERSION:
                        cache[doc.doc_id] = existing
                    else:
                        f = mep._find_ifc(doc.doc_id)
                        cache[doc.doc_id] = mep.build(doc.doc_id, f) if f and f.stat().st_size <= 60e6 else None
                return cache[doc.doc_id]
        mep.load_index = index
        res = bench.run(rows, concurrency=1, max_usd=None,
                        progress=lambda n, total, usd: print(f'{args.phase}: {n}/{total}', flush=True) if n % 20 == 0 else None)
    res['hygiene'] = {'sample200_rows': len(rows), 'forbidden_evaluated': 0, 'blind_evaluated': False,
                      'fake': True, 'shared_artifacts_written': False}
    (OUT / f'sample200.{args.phase}.json').write_text(json.dumps(res, indent=1) + '\n')
    print(json.dumps({'totals': res['totals'], 'cells': res['cells']}), flush=True)


if __name__ == '__main__':
    main()
