"""Read-only six-scan round-3 audit and exact cached second-look replay.

Run via scripts/heavy.sh. No model calls, artifact writes or training. The
reserved sixth drawing is opened only with --blind after development finishes.
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/final/EVINT'
BASELINE = '0a31112a41d58d11ca8c5bef7a63e3176e0b30c0'
DEV = ['cubicasa5k__colorful-11397', 'cubicasa5k__colorful-10052', 'ext_cvcfp__iib-dd0601',
       'ext_resplan__plan-13503', 'ext_cvcfp__9']
QUESTIONS = ['How many doors are there?', 'How many windows are there?', 'what is this', 'What is the total area of all rooms?']
CACHE = Path('/tmp/hologram/recount_cache.json')


def cases(docs):
    import engine.answer as api
    from engine.calc import validate
    from engine.solvers.data import load_doc
    from engine.xcheck_audit import cached_recount
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    original = api._recount_ladder
    replayed = {}

    def saved_only(res, question, did, parsed, root, calls, hidden):
        doc = load_doc(did, root)
        hit = None
        image = Path(root) / did / 'page-1.png'
        if doc and image.is_file():
            from engine.recount import _cache_key
            with patch.dict(os.environ):
                os.environ.pop('MODELS_FAKE', None)
                key = _cache_key('count', image, parsed.kind, question)
            saved = cache.get(key)
            if (isinstance(saved, list) and len(saved) >= 2 and type(saved[0]) is int
                    and saved[0] >= 0 and 'fake' not in str(saved[1]).lower()):
                hit = saved[0], saved[1], parsed.kind
        if not hit and doc:
            hit = cached_recount(question, doc, root, cache)
        if not hit:
            return res
        n, model, kind = hit
        if kind != parsed.kind:
            return res
        replayed[(did, question)] = {'value': n, 'model': model, 'cache': str(CACHE),
                                     'match': 'exact source image hash, normalized question and current prompt pin; otherwise only an unambiguous saved reading; no fake records'}
        # Invoke the real reconciliation code with an exact saved reading; all
        # model entrypoints in this path are replaced with read-only results.
        with patch.dict(os.environ, {'RECOUNT': '1', 'DET_BOXES': '0'}):
            os.environ.pop('MODELS_FAKE', None)
            with patch('engine.recount.recount', return_value=(n, 0, 'cache:' + model)), patch('engine.recount.detect', return_value=(None, 0, 'no cached boxes')):
                return original(res, question, did, parsed, root, calls, hidden)

    records = []
    with patch.object(api, '_recount_ladder', saved_only):
        for did in docs:
            for question in QUESTIONS:
                r = api.answer(question, [did])
                card = r['reasoning']; c = card.get('calc') or {}; margin = card.get('margin') or {}
                conf = card['confidence']; steps = c.get('steps') or []
                main = [s for s in steps if s.get('level') != 'detail']
                sections = ['result', 'detections', 'scale', 'recount', 'margin', 'confidence']
                order = [sections.index(s['section']) for s in main if s.get('section') in sections]
                issues = validate(c, ROOT / 'artifacts')
                checks = {'replay': not issues, 'answer_matches_calc': r['answer']['value'] == (c.get('result') or {}).get('value'),
                          'factor_sum': sum(f['delta'] for f in conf['factors']) == conf['pct'],
                          'at_most_12_main_steps': 1 <= len(main) <= 12,
                          'importance_order': len(order) == len(main) and order == sorted(order),
                          'detail_follows_summary': all(s.get('level') == 'detail' for s in steps[len(main):]),
                          'excluded_alternatives': all(x['label'] != 'Saved extraction count disagreement' for x in margin.get('components') or []),
                          'short_margin': not margin.get('value') or len(margin['why']) <= 180,
                          'no_false_error_bound': not isinstance(margin.get('value'), (int, float)) or margin.get('is_error_bound') is False}
                if question.startswith('How many'):
                    checks['result_first'] = bool(main and main[0].get('section') == 'result')
                records.append({'doc_id': did, 'question': question, 'value': r['answer']['value'], 'unit': r['answer']['unit'],
                                'checks': checks, 'issues': issues, 'margin': {k: v for k, v in margin.items() if k != 'components'},
                                'component_values': [{k: c[k] for k in ('label', 'value', 'unit')} for c in margin.get('components') or []],
                                'confidence': conf['pct'], 'pct_kind': conf.get('pct_kind'), 'factors': conf['factors'],
                                'recount': replayed.get((did, question)), 'steps': len(steps), 'summary_steps': len(main),
                                'first_steps': [{k: s.get(k) for k in ('id', 'label', 'section', 'value', 'unit', 'note')} for s in main[:12]],
                                'live_calls': 0, 'live_spend_usd': 0})
    return records


def run():
    p = argparse.ArgumentParser(); p.add_argument('--blind', action='store_true'); p.add_argument('--baseline-child', action='store_true')
    args = p.parse_args()
    os.environ.update(MODELS_FAKE='1', READER='0', RECOUNT='0', EXPLAIN='0', ANSWER_TIMEOUT_S='0', ARTIFACTS_DIR=str(ROOT / 'artifacts'))
    docs = [json.loads((OUT / 'round3-blind.json').read_text())['doc_id']] if args.blind else DEV
    if args.baseline_child:
        print(json.dumps(cases(docs))); return
    after = cases(docs)
    with tempfile.TemporaryDirectory(prefix='.round3-baseline-', dir=OUT) as tmp:
        folder = Path(tmp)
        archive = subprocess.check_output(['git', 'archive', BASELINE, 'engine'], cwd=ROOT)
        with tarfile.open(fileobj=BytesIO(archive)) as tf:
            tf.extractall(path=folder, filter='data')
        (folder / 'results').symlink_to(OUT.parents[1], target_is_directory=True)
        command = 'import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_path(sys.argv.pop(1),run_name="__main__")'
        args_child = [sys.executable, '-c', command, str(folder), str(Path(__file__)), '--baseline-child']
        if args.blind: args_child.append('--blind')
        before = json.loads(subprocess.check_output(args_child, cwd=ROOT, text=True))
    summary = {'real_scans': len(docs), 'answers': len(after), 'all_checks_passed': sum(all(r['checks'].values()) for r in after),
               'cached_recounts': sum(bool(r['recount']) for r in after), 'max_summary_steps': max(r['summary_steps'] for r in after),
               'live_calls': 0, 'live_spend_usd': 0}
    report = {'time': datetime.now(timezone.utc).isoformat(), 'baseline_commit': BASELINE, 'blind': args.blind,
              'scope': 'Arithmetic, presentation and exact saved recount replay. Description uses fake models; not semantic accuracy.',
              'rounding': 'ceil(max supported same-unit variation components) for whole-item count margin; pct uses the rounded count margin. raw_value/raw_pct retain the unrounded comparison.',
              'summary': summary, 'before': before, 'after': after}
    (OUT / ('round3-blind-report.json' if args.blind else 'round3-report.json')).write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(summary))
    for r in after:
        if not all(r['checks'].values()): print(r['doc_id'], r['question'], r['checks'], r['issues'])
    if summary['all_checks_passed'] != len(after): raise SystemExit(1)


if __name__ == '__main__': run()
