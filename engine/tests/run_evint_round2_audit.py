"""Read-only round-2 evidence audit; run via scripts/heavy.sh. No live calls."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/final/EVINT'


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blind', action='store_true')
    args = parser.parse_args()
    os.environ.update(MODELS_FAKE='1', READER='0', RECOUNT='0', EXPLAIN='0', ANSWER_TIMEOUT_S='0', ARTIFACTS_DIR=str(ROOT / 'artifacts'))
    from engine.answer import answer
    from engine.calc import validate
    from engine.tests.test_evint_round2 import DOCS, QUESTIONS
    docs = [json.loads((OUT / 'round2-blind.json').read_text())['doc_id']] if args.blind else DOCS
    records = []
    for did in docs:
        for question in QUESTIONS:
            r = answer(question, [did])
            card = r['reasoning']
            c, trace, margin = card['confidence'], card.get('calc') or {}, card.get('margin')
            factors = c.get('factors') or []
            issues = validate(trace, ROOT / 'artifacts') if trace else []
            method = trace.get('method')
            expected_method = bool(trace)
            checks = {'confidence_sum': sum(f['delta'] for f in factors) == c['pct'],
                      'one_base': sum(bool(f.get('base')) for f in factors) == 1,
                      'method': not expected_method or bool(method and all(method.get(k) for k in ('id', 'label', 'why_chosen'))),
                      'replay': not issues,
                      'result_matches_answer': not trace or trace['result']['value'] == r['answer']['value']}
            if did.startswith(('cubicasa5k__', 'ext_')) and trace:
                checks['numeric_observed_margin'] = isinstance((margin or {}).get('value'), (int, float))
                checks['margin_not_false_bound'] = (margin or {}).get('is_error_bound') is False
            records.append({'doc_id': did, 'question': question, 'route': r.get('route'), 'value': r['answer']['value'],
                            'abstained': r['answer']['abstained'], 'checks': checks, 'confidence': c,
                            'margin': margin, 'method': method, 'graph_path': card.get('graph_path'),
                            'calc_steps': len(trace.get('steps') or []), 'replay_issues': issues,
                            'model_mode': 'fake', 'usd_total': r.get('cost', {}).get('usd_total', 0)})
    summary = {'answers': len(records), 'all_checks_passed': sum(all(r['checks'].values()) for r in records),
               'factor_sums_passed': sum(r['checks']['confidence_sum'] for r in records),
               'methods': sum(bool(r['method']) for r in records), 'numeric_margins': sum(isinstance((r['margin'] or {}).get('value'), (int, float)) for r in records),
               'replay_passed': sum(r['checks']['replay'] for r in records), 'live_calls': 0, 'live_spend_usd': 0}
    report = {'time': datetime.now(timezone.utc).isoformat(), 'blind': args.blind,
              'scope': 'Evidence arithmetic/method/source checks; fake-model prose is not scored for semantic accuracy.',
              'limits': ['Uncalibrated route/model scores are explicitly labelled and never described as measured accuracy.',
                         'Observed scan discrepancy/reference MAE is a partial variation proxy, not an error bound.',
                         'Zero coverage discrepancy does not imply zero detection error. Unknown semantic/physical error is not assigned a fabricated bound.'],
              'summary': summary, 'records': records}
    (OUT / ('round2-blind-report.json' if args.blind else 'round2-report.json')).write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(summary))
    for r in records:
        if not all(r['checks'].values()):
            print(r['doc_id'], r['question'], r['checks'], r['replay_issues'])
    if summary['all_checks_passed'] != len(records):
        raise SystemExit(1)


if __name__ == '__main__':
    run()
