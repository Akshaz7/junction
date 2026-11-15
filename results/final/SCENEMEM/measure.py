"""Run via scripts/heavy.sh; derived models stay in a private temporary folder."""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[3]
CASES = [
    ('munich', REPO / 'data/full/junction-dataset/data/ifc_bench/city_house_munich_arc.ifc', 'ifc_bench__city-house-munich-arc'),
    ('schependomlaan', REPO / 'data/external/ifc_round2/schependomlaan_design.ifc', 'external__schependomlaan-design'),
    # Randomly selected before development; do not open until final validation.
    ('reserved', REPO / 'data/junction-dataset-preview/data/opening_design/Facilities_Building/Transfer/20181108 - to structure & MBM - for pricing/1810 S Park.ifc', 'opening_design__facilities-building-transfer-20181108-to-structure-mbm-for-pricing-1810-s-park'),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('label')
    p.add_argument('case', choices=[c[0] for c in CASES])
    p.add_argument('--cap', type=float, default=900)
    p.add_argument('--timeout', type=float, default=240)
    p.add_argument('--work', type=Path)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--baseline', type=Path)
    p.add_argument('--index', type=Path)
    p.add_argument('--fresh-index', action='store_true')
    args = p.parse_args()
    _, source, doc_id = next(c for c in CASES if c[0] == args.case)
    if args.worker:
        sys.path.insert(0, str(REPO))
        if args.baseline:
            sys.path.insert(0, str(args.baseline))
        from server.ifc_worker import run
        try:
            result = run('ifc_scene', source, args.work)
            print(json.dumps({'ok': True, 'result': result}), flush=True)
        finally:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(json.dumps({'resource_peak_mib': rss / (1024**2 if sys.platform == 'darwin' else 1024)}), flush=True)
        return
    from shutil import copyfile
    work = args.work or Path(tempfile.mkdtemp(prefix='f-scenemem-'))
    work.mkdir(parents=True, exist_ok=True)
    (work / 'doc.json').write_text(json.dumps({'doc_id': doc_id}))
    index = args.index or REPO / 'artifacts' / doc_id / 'elements.json'
    index_metrics = None
    if index.exists() and not args.fresh_index:
        copyfile(index, work / 'elements.json')
    elif args.label != 'before':
        sys.path.insert(0, str(REPO))
        from server.ifc_ingest import index as build_index
        index_metrics = build_index(source, {'doc_id': doc_id}, work, 180)
    if (work / 'elements.json').exists():
        copyfile(work / 'elements.json', work / 'input-elements.json')
    env = {**os.environ, 'IFC_WORKER_MEMORY_BYTES': str(int(args.cap * 1024**2)),
           'IFC_CONVERT_THREADS': '1', 'IFC_CONVERT_PY': '1', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
    start, peak, reason = time.monotonic(), 0, None
    with (work / 'measure.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, __file__, args.label, args.case, '--worker', '--work', str(work)] + (['--baseline', str(args.baseline)] if args.baseline else []),
                                stdout=log, stderr=subprocess.STDOUT, env=env)
        while proc.poll() is None:
            if sys.platform == 'linux':
                try: rss = int(Path(f'/proc/{proc.pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1024**2
                except (OSError, IndexError): rss = 0
            else:
                r = subprocess.run(['ps', '-o', 'rss=', '-p', str(proc.pid)], capture_output=True, text=True)
                rss = int(r.stdout.strip() or 0) / 1024
            peak = max(peak, rss)
            if peak > args.cap or time.monotonic() - start > args.timeout:
                reason = 'memory cap' if peak > args.cap else 'timeout'
                proc.kill()
                break
            time.sleep(.1)
        proc.wait()
    log_text = (work / 'measure.log').read_text()
    result = {'label': args.label, 'case': args.case, 'doc_id': doc_id, 'source': str(source.relative_to(REPO)),
              'source_mb': source.stat().st_size / 1e6, 'peak_sampled_mib': round(peak, 2),
              'seconds': round(time.monotonic() - start, 2), 'exit_code': proc.returncode, 'stopped': reason, 'work': str(work), 'fresh_index_metrics': index_metrics}
    for line in log_text.splitlines():
        try: result.update(json.loads(line))
        except ValueError: pass
    report = REPO / 'results/final/SCENEMEM' / f'{args.label}-{args.case}.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if proc.returncode: print(log_text[-1500:])


if __name__ == '__main__':
    main()
