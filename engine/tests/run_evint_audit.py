"""Read-only real-artifact trace audit. Run through scripts/heavy.sh.

No inference, training or artifact rewrites. Fake-model description text is not
scored for semantic correctness; this audit tests source arithmetic and traces.
"""
import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/final/EVINT'

DEV = ['cubicasa5k__colorful-11397', 'cubicasa5k__colorful-10052', 'ext_cvcfp__iib-dd0601', 'ext_resplan__plan-13503',
       'swiss_dwellings__site1000-bldg2082-floor9385', 'ifc_bench__ac20-arc']
QUESTIONS = ['what is this', 'How many doors are there?', 'What is the total area of all rooms?']


def cases(docs):
    from engine.answer import answer
    from engine.calc import validate
    records = []
    for did in docs:
        for question in QUESTIONS:
            r = answer(question, [did])
            card = r.get('reasoning') or {}
            c = card.get('calc') or {}
            issues = validate(c, ROOT / 'artifacts') if c else ['No calc']
            steps = c.get('steps', [])
            records.append({'doc_id': did, 'question': question, 'route': r.get('route'), 'value': r['answer']['value'],
                            'abstained': r['answer']['abstained'], 'steps': len(steps), 'selected_rows': len(c.get('rows', [])),
                            'inventory_rows': len(c.get('inventory_rows', [])), 'complete': bool(c) and not issues,
                            'issues': issues, 'scale_proofs': len(c.get('scale_proof', [])), 'missing': c.get('unavailable', []),
                            'score_statistics': sum(s.get('unit') == 'score' for s in steps),
                            'pixel_measurements': sum(s.get('unit') in ('px', 'px2') for s in steps),
                            'numeric_input_sources': sum(len(s.get('inputs', [])) for s in steps),
                            'confidence': card.get('confidence'), 'model_calls': len(r.get('cost', {}).get('calls') or []),
                            'cost_usd': r.get('cost', {}).get('usd_total', 0)})
    return records


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blind', action='store_true')
    parser.add_argument('--baseline-child', action='store_true')
    args = parser.parse_args()
    os.environ.update(MODELS_FAKE='1', READER='0', RECOUNT='0', EXPLAIN='0', ANSWER_TIMEOUT_S='0',
                      ARTIFACTS_DIR=str(ROOT / 'artifacts'))
    docs = [json.loads((OUT / 'blind.json').read_text())['doc_id']] if args.blind else DEV
    if args.baseline_child:
        print(json.dumps(cases(docs)))
        return
    current = cases(docs)
    # Reproduce the actual committed integration baseline in a temporary local
    # package, with read-only links to source artifacts. Never switch branches.
    with tempfile.TemporaryDirectory(prefix='.baseline-', dir=OUT) as tmp:
        path = Path(tmp)
        archive = subprocess.check_output(['git', 'archive', 'bfc463f', 'engine'], cwd=ROOT)
        with tarfile.open(fileobj=BytesIO(archive)) as tf:
            tf.extractall(path=path, filter='data')
        for name in ('artifacts', 'data', 'docs'):
            (path / name).symlink_to(ROOT / name, target_is_directory=True)
        env = {**os.environ, 'PYTHONPATH': str(path)}
        # Execute this audit file with the isolated baseline package imported.
        command = "import runpy,sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
        child = [sys.executable, '-c', command, str(path), str(Path(__file__)), '--baseline-child']
        if args.blind: child.append('--blind')
        baseline = json.loads(subprocess.check_output(child, cwd=ROOT, env=env, text=True))
    result = {'time': datetime.now(timezone.utc).isoformat(), 'baseline_commit': 'bfc463f',
              'scope': 'Calculation/source-trace replay only; fake-model prose is not interpreted or scored. No accuracy claim.',
              'blind': args.blind, 'real_sources': docs, 'before': baseline, 'after': current,
              'summary': {'answers': len(current), 'before_with_calc': sum(e['steps'] > 0 for e in baseline),
                          'after_with_calc': sum(e['steps'] > 0 for e in current),
                          'after_complete': sum(e['complete'] for e in current),
                          'after_total_steps': sum(e['steps'] for e in current),
                          'after_inputs': sum(e['numeric_input_sources'] for e in current),
                          'live_calls': 0, 'live_spend_usd': 0}}
    (OUT / ('blind-report.json' if args.blind else 'report.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['summary']))
    for e in current:
        if not e['complete']: print(e['doc_id'], e['question'], e['issues'])


if __name__ == '__main__':
    run()
