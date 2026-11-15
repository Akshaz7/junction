"""Final source-consistency diagnostics; no gold or blind-file tuning.

Run once, after development: scripts/heavy.sh .venv/bin/python .../final_checks.py --bench-dir ...
The injected missing fields/headlines are generated for demo; source counts are real.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bench-dir', required=True, type=Path)
    args = ap.parse_args()
    forbidden = set((args.bench_dir / 'forbidden_heldout_docs.txt').read_text().split())
    outdir = Path(__file__).parent
    blind = json.loads((outdir / 'selection.json').read_text())['blind_doc_id']
    if blind in forbidden:
        raise RuntimeError('Reserved file is excluded; refusing access.')
    # Select three original real files from different eligible benchmark origins.
    selected = {}
    for file in sorted((args.bench_dir / 'out').glob('*.rows.jsonl')):
        for line in file.open():
            row = json.loads(line)
            did, source = row['doc_id'], row['source']
            if did in forbidden or source in selected:
                continue
            folder = ROOT / 'artifacts' / did
            if (folder / 'elements.json').exists() or (folder / 'planmap-1.json').exists():
                selected[source] = did
    if len(selected) < 3 or blind in selected.values():
        raise RuntimeError('Need three different eligible origins and a separate blind file.')
    root = Path(tempfile.mkdtemp(prefix='acc-value-final-artifacts-'))
    ids = list(selected.values()) + [blind]
    for did in ids:
        (root / did).symlink_to((ROOT / 'artifacts' / did).resolve(), target_is_directory=True)
    os.environ['MODELS_FAKE'] = '1'
    os.environ['ARTIFACTS_DIR'] = str(root)
    from engine.answer import answer
    from engine.numeric import guard_answer_value
    from engine.reader.agent import _build
    from engine.reader.tools import Session
    from engine.solvers.data import load_doc
    from engine.solvers.solve import solve
    results = []
    for did in ids:
        doc = load_doc(did, root)
        if doc is None:
            raise RuntimeError('Selected final-check file has no usable structured data.')
        question = 'How many rooms are there?'
        direct = solve(question, did, root=root)
        public = answer(question, [did])
        wrong = copy.deepcopy(direct)
        wrong['answer'].update(value=1.25, unit='m²', abstained=False, text_md='Generated for demo: **1.25 m².**')
        repaired = guard_answer_value(wrong, question, [did], root)
        assert repaired['answer']['value'] == direct['answer']['value']
        assert repaired['answer']['unit'] == 'count'
        sess = Session([did], root)
        sess.run('ifc' if doc.mode == 'ifc' else 'planmap', {'kind': 'room'})
        facts = [r for r in sess.numeric_results if r.get('unit') == 'count']
        value = facts[-1]['value']
        ref = facts[-1]['refs'][0]
        restored = _build(question, [did], sess, {'action': 'final', 'answer': f'**Stored count: {value} rooms.**',
                          'value': None, 'unit': None, 'evidence': [ref], 'confidence': 0.8}, [], [], time.perf_counter())
        assert restored['answer']['value'] == value and restored['answer']['unit'] == 'count'
        assert restored['citations']
        assert public.get('reasoning') and public['answer']['unit'] == 'count'
        results.append({'doc_id': did, 'source': did.split('__')[0], 'blind': did == blind,
                        'mode': doc.mode, 'stored_items': len(doc.items), 'solver_room_count': direct['answer']['value'],
                        'reader_inventory_count': value, 'public_room_count': public['answer']['value'],
                        'checks': ['public answer with reasoning', 'wrong-measurement retry', 'missing reader value recovery with citation'],
                        'passed': True})
    (outdir / 'final_checks.json').write_text(json.dumps({'purpose': 'source consistency, not independent gold accuracy',
        'injected_answer_data': 'generated for demo', 'results': results, 'checks_passed': sum(len(r['checks']) for r in results)}, indent=2) + '\n')
    print(json.dumps({'documents': len(results), 'origins': list(selected), 'checks_passed': sum(len(r['checks']) for r in results)}))


if __name__ == '__main__':
    main()
