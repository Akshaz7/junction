"""Read-only real-file validation; final unseen scan is evaluated last.

Run via scripts/heavy.sh because --heldout may invoke the existing local vision
pipeline. No gold is inferred from predictions, no provider calls, no training,
no shared artifacts written. Source-specific names below are validation inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from engine.reasoning import build
from engine.reasoning_parts import confidence
from engine.solvers import solve

ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = [
    ('ifc_bench__fzk-house-arc', 'How many windows are there?', 'IFC'),
    ('swiss_dwellings__site1000-bldg2082-floor9385', 'What is the total net floor area of all rooms?', 'DXF'),
    ('cubicasa5k__colorful-11397', 'How many windows are there?', 'scan'),
    ('cubicasa5k__colorful-11397', 'What is the total area of all rooms?', 'scan'),
]


def case(doc_id, question, root, kind, calibration):
    answer = solve(question, doc_id, root=root)
    assert not answer['answer']['abstained'], (doc_id, answer['answer']['text_md'])
    card = build(answer, question, root)
    assert card and card.get('margin') and card.get('based_on')
    terms = sum(len(c['terms']) for c in card.get('arithmetic', []))
    if kind == 'scan':
        assert card['confidence']['label'] != 'Verified'
    matched_calibration = None
    if calibration.is_file():
        original = confidence.CALIBRATION_PATH
        try:
            confidence.CALIBRATION_PATH = calibration
            calibrated_card = build(answer, question, root)
            matched_calibration = calibrated_card['confidence']
        finally:
            confidence.CALIBRATION_PATH = original
    return dict(doc_id=doc_id, question=question, format=kind, value=answer['answer']['value'], unit=answer['answer']['unit'],
                margin=card['margin'], based_on=card['based_on'], arithmetic_terms=terms,
                steps=card['steps'], confidence=card['confidence'], calibrated_preview=matched_calibration,
                correctness='Not independently gold-scored; validates evidence arithmetic and honest uncertainty only')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--heldout', type=Path, required=True)
    ap.add_argument('--heldout-doc', required=True)
    ap.add_argument('--calibration', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    rows = [case(d, q, ROOT / 'artifacts', kind, args.calibration) for d, q, kind in DEVELOPMENT]
    print(f'Development checks: {len(rows)} passed across IFC, DXF, scan.', flush=True)
    # This is the first inspection of the pre-reserved file. Do not use its
    # contents or result to tune code or thresholds after this point.
    print('Beginning end-only reserved scan check.', flush=True)
    heldout = args.heldout.resolve()
    digest = hashlib.sha256(heldout.read_bytes()).hexdigest()
    existing = ROOT / 'artifacts' / args.heldout_doc / 'planmap-1.json'
    inference = False
    with tempfile.TemporaryDirectory(prefix='f-evidence2-unseen-') as td:
        out_root = Path(td)
        if existing.is_file():
            heldout_root = ROOT / 'artifacts'
        else:
            import torch
            torch.set_num_threads(2)
            import vision.build_planmaps as pipeline
            # Reuse the unchanged production pipeline with an explicit image
            # path and an isolated output directory, never the shared registry.
            original_image_path = pipeline.image_path
            try:
                pipeline.image_path = lambda _doc: heldout
                timing, problems = pipeline.run([args.heldout_doc], out_root=out_root)
            finally:
                pipeline.image_path = original_image_path
            assert not any(problems.values()), problems
            inference = True
            heldout_root = out_root
        for question in ('How many windows are there?', 'What is the total area of all rooms?'):
            rows.append(case(args.heldout_doc, question, heldout_root, 'scan', args.calibration))
    calibration_data = json.loads(args.calibration.read_text()) if args.calibration.is_file() else {}
    report = {
        'row': 'F-EVIDENCE2', 'time': datetime.now().astimezone().isoformat(),
        'branch': subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip(),
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'checks_passed': len(rows), 'documents': len({r['doc_id'] for r in rows}), 'source_formats': ['IFC', 'DXF', 'scan'],
        'before_margin_cards': 0, 'after_margin_cards': len(rows),
        'before_based_on_cards': 0, 'after_based_on_cards': len(rows),
        'before_note': 'Base engine/reasoning.py had neither margin nor based_on fields; answer accuracy is not claimed to improve.',
        'local_vision_inference_for_heldout': inference, 'live_provider_calls': 0, 'live_spend_usd': 0,
        'reserved_file': str(args.heldout), 'reserved_sha256': digest, 'selection_seed': 261114,
        'unseen_policy': 'Reserved by the previous run before implementation; first inspected at this script\'s end-only stage. No training or tuning on it.',
        'calibration_integration': 'Preview reads QA2 worktree only; production percentages remain null until its report is merged at results/final/QA2/calibration.json.',
        'calibration_sha256': hashlib.sha256(args.calibration.read_bytes()).hexdigest() if args.calibration.is_file() else None,
        'calibration_buckets': calibration_data.get('by_format_and_question_type', []),
        'limitations': ['No independent count/area truth is claimed for the reserved scan.',
                       'No active-model/source-matched detector precision/recall is currently linked, so scan count margins are unknown.',
                       'Door-icon scatter does not quantify physical door-width variation, so door-prior area margins are unknown.',
                       'Error budgets cover the stated source/measurement components, not source completeness or construction tolerances.'],
        'cases': rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(f'{len(rows)} checks passed; wrote {args.output}', flush=True)


if __name__ == '__main__':
    main()
