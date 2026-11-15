"""Run with scripts/heavy.sh; never mutate shared input artifacts."""
import argparse
import importlib.util
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('label')
    ap.add_argument('name')
    ap.add_argument('source', type=Path)
    ap.add_argument('--baseline', type=Path)
    ap.add_argument('--cap', type=float, default=900)
    ap.add_argument('--worker', action='store_true')
    ap.add_argument('--production', action='store_true')
    ap.add_argument('--work', type=Path)
    args = ap.parse_args()
    if args.worker:
        sys.path.insert(0, str(REPO))
        if args.baseline:
            spec = importlib.util.spec_from_file_location('old_usdz', args.baseline)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            from pipeline import usdz as module
        try:
            if args.production:
                from server.ifc_worker import run
                result = run('usdz', args.work / 'scene.glb', args.work)
            else:
                result = module.process(args.name, args.work)
            print(json.dumps({'ok': True, 'result': result}), flush=True)
        finally:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(json.dumps({'resource_peak_mib': peak / (1048576 if sys.platform == 'darwin' else 1024)}), flush=True)
        return
    work = Path(tempfile.mkdtemp(prefix='f-usdzmem-'))
    shutil.copyfile(args.source / 'scene.json', work / 'scene.json')
    scene = json.loads((work / 'scene.json').read_text())
    (work / 'doc.json').write_text(json.dumps({'doc_id': scene['doc_id']}))
    (work / 'scene.glb').symlink_to((args.source / 'scene.glb').resolve())
    cmd = [sys.executable, __file__, args.label, args.name, str(args.source), '--worker', '--work', str(work)]
    if args.production:
        cmd += ['--production']
    if args.baseline:
        cmd += ['--baseline', str(args.baseline)]
    start, peak, stopped = time.monotonic(), 0., None
    with (work / 'measure.log').open('w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MODELS_FAKE': '1',
                                     'IFC_WORKER_MEMORY_BYTES': str(int(args.cap * 1048576))})
        while proc.poll() is None:
            if sys.platform == 'linux':
                try:
                    rss = int(Path(f'/proc/{proc.pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1048576
                except (OSError, IndexError):
                    rss = 0
            else:
                r = subprocess.run(['ps', '-o', 'rss=', '-p', str(proc.pid)], check=False, text=True, capture_output=True)
                rss = int(r.stdout.strip() or 0) / 1024
            peak = max(peak, rss)
            if peak > args.cap or time.monotonic() - start > 240:
                stopped = 'memory cap' if peak > args.cap else 'timeout'
                proc.kill()
                break
            time.sleep(.05)
        proc.wait()
    result = {'label': args.label, 'case': args.name, 'input': str(args.source), 'work': str(work),
              'glb_mb': (args.source / 'scene.glb').stat().st_size / 1e6,
              'sampled_peak_mib': peak, 'seconds': time.monotonic() - start,
              'exit_code': proc.returncode, 'stopped': stopped}
    log_text = (work / 'measure.log').read_text()
    for line in log_text.splitlines():
        try:
            result.update(json.loads(line))
        except ValueError:
            pass
    report = REPO / 'results/final/USDZMEM' / f'{args.label}-{args.name}.json'
    report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    if proc.returncode:
        print(log_text[-2000:])


if __name__ == '__main__':
    main()
