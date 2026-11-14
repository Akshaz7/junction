"""Reproduce the published Awais cases locally without writing shared artifacts.

Run via scripts/heavy.sh python -m engine.tests.run_fix_suite --output baseline.
The report distinguishes deterministic checks, manual review and reconstructed inputs.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(os.environ.get('FIX_SUITE_WORKTREE') or Path(__file__).resolve().parents[2])
OUT = ROOT / 'results/final/FIX-SUITE'
RUNTIME = ROOT / '.fix-suite-runtime'


def overlay():
    """Private directories: new OCR/crop/cache files never land in shared artifacts."""
    source = ROOT / 'artifacts'
    target = RUNTIME / 'artifacts'
    target.mkdir(parents=True, exist_ok=True)
    if (RUNTIME / 'inputs-frozen').exists():
        return target
    for src in source.iterdir():
        if not src.is_dir() or not (src / 'doc.json').exists():
            continue
        dest = target / src.name
        dest.mkdir(exist_ok=True)
        for f in src.iterdir():
            p = dest / f.name
            if p.exists() or p.is_symlink():
                continue
            if f.is_file():
                if f.name.startswith(('rtext-', 'scale-ocr-')):
                    shutil.copy2(f, p)
                else:
                    p.symlink_to(f.resolve())
    # Indexes are read-only inputs, not rebuilt in the shared tree.
    for name in ('project-index.json', 'registry.json'):
        f, p = source / name, target / name
        if f.exists() and not p.exists():
            p.symlink_to(f.resolve())
    return target


def docs_for(label, root):
    fixed = {'ac20-arc': 'ifc_bench__ac20-arc', 'colorful-11397': 'cubicasa5k__colorful-11397'}
    if label in fixed:
        return [fixed[label]]
    if label == '(none)':
        return []
    if label == 'ac20-arc, digital-hub-arc':
        return [fixed['ac20-arc'], 'ifc_bench__digital-hub-arc']
    patterns = {'1810 S Park pricing set': '*20181108-1810-s-park-st-drawings-for-pricing-exercise',
                'up:m-101a-piping-plan': 'uploads__m-101a-*',
                'up:home-plan-1921': 'uploads__home-plan-1921-*',
                'up:special-school': 'uploads__*special-school*',
                'up:s-100f': 'uploads__s-100f-*', 'up:a-2-dorm': 'uploads__a-2-dorm-*',
                'swiss_dwellings__site289': 'swiss_dwellings__site289-*'}
    for prefix, pat in patterns.items():
        if label.startswith(prefix):
            found = sorted(p.name for p in root.glob(pat) if p.is_dir())
            if len(found) != 1:
                raise ValueError((label, found))
            return found
    raise ValueError(label)


def turns_for(case):
    """Missing histories are documented reconstructions, never called original runs."""
    q = re.sub(r'^\(\d+ turns\) ', '', case['question'])
    reconstructed = {
        'D01': ['How many m2 of tiles do I need for all WCs including 10% waste?', q],
        'D02': ['How many linear metres of baseboard do I need for the Seminarraum, excluding door openings?'],
        'D07': ['How much paint do I need for both faces of all internal walls on 1. Obergeschoss, two coats at 8 m2 per litre?'],
        'F02': ['Remove the main entrance door', q],
        'J01': ['How many doors are in the building?', 'How many windows are in the building?', q],
        'J02': ['How many doors are on the ground floor?', q],
        'J03': ['How many doors are on the ground floor?', 'Remove the main entrance door', 'Restore the main entrance door', q],
        'J04': ['What is the area?', q],
        'K07': ["I'm a site engineer preparing a pricing exercise for the main contractor. How many windows are on the ground floor?"],
        'X06': ['filler text about the project. ' * 300 + 'How many doors are on the ground floor?'],
        'X28': [q, q],
        'X29': ['How many doors are on the ground floor?', 'Hide all doors on the ground floor', 'How many doors are on the ground floor?', q],
        'X30': ['Hide W3', q],
        'X38': ['How many windows are on the ground floor?', q],
    }
    return reconstructed.get(case['id'], [q])


def grade(case, r):
    """Only mechanically check explicit gold; prose/visual expectations need a human."""
    a = r['answer']
    text = a['text_md']
    if any(s['step'] == 'error' for s in r.get('trace', [])):
        return 'error'
    fake_calls = any(s.get('model') == 'fake' for s in r.get('trace', []))
    if fake_calls or any(c.get('provider') == 'fake' for c in r.get('cost', {}).get('calls', [])):
        return 'model_needed'
    gold = case['expected']
    m = re.fullmatch(r'(-?\d+(?:\.\d+)?)\s*(m2|m3|m|%|EUR|ft2|ft|acre)?', gold)
    if m:
        want = float(m[1])
        v = a.get('value')
        if isinstance(v, (int, float)) and abs(v - want) <= max(.05, abs(want)*.02):
            return 'pass'
        # Conversion preserves a metric value: only quantities explicitly carrying
        # the requested display unit qualify. Citation numbers can never match gold.
        unit = m[2]
        patterns = {'ft2': r'ft²|ft2', 'ft': r'ft', 'acre': r'acres?',
                    'm2': r'm²|m2', 'm3': r'm³|m3', 'EUR': r'EUR', '%': '%'}
        if unit in patterns:
            nums = re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*(?:' + patterns[unit] + r')', text)
            if any(abs(float(x.replace(',', ''))-want) <= max(.05, abs(want)*.02) for x in nums):
                return 'pass'
        return 'fail'
    if gold.startswith('['):
        try:
            vals = json.loads(gold)
        except ValueError:
            return 'manual_review'
        for v in vals:
            if isinstance(v, str):
                if not any(t.lower() in text.lower() for t in v.split('|')):
                    return 'fail'
            elif not re.search(r'(?<![\w.])' + re.escape(str(v)) + r'(?![\w.])', re.sub(r'\[\d+\]', '', text)):
                return 'fail'
        return 'pass'
    if gold == 'clarify':
        return 'pass' if a.get('value') is None and re.search('ask|understand|finish|question|select|clarif', text, re.I) else 'fail'
    return 'manual_review'


def run(output, live=False, budget=0.0, only=None):
    root = overlay()
    os.environ.update(ARTIFACTS_DIR=str(root), MODELS_CACHE_DIR=str(RUNTIME / 'models'),
                      MODELS_COSTS_LOG=str(RUNTIME / 'model_calls.jsonl'), ANSWER_TIMEOUT_S='120')
    if live:
        os.environ.pop('MODELS_FAKE', None)
    else:
        os.environ['MODELS_FAKE'] = '1'
    from engine.answer import answer
    from engine.models import core
    import engine.models as models
    original = models.call
    spent = [0.0]
    def bounded(*args, **kwargs):
        if live and spent[0] >= budget:
            raise core.BudgetExceeded('FIX-SUITE row budget reached')
        res = original(*args, **kwargs)
        spent[0] += res.cost_usd
        return res
    models.call = bounded
    cases = json.loads((ROOT / 'engine/tests/fixtures/awais_suite.json').read_text())
    results = []
    for case in cases:
        if only and case['id'] not in only:
            continue
        docs = docs_for(case['doc_label'], root)
        history, state, turn_results = [], {'hidden': []}, []
        start = time.perf_counter()
        try:
            for question in turns_for(case):
                r = answer(question, docs, scene_state=state, history=history)
                history += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': r['answer']['text_md'], 'answer': r}]
                for c in r.get('evidence', {}).get('scene', {}).get('commands', []):
                    ids = c.get('item_ids', [])
                    if c['op'] == 'hide': state['hidden'] = sorted(set(state['hidden']) | set(ids))
                    if c['op'] == 'restore': state['hidden'] = [i for i in state['hidden'] if i not in ids]
                    if c['op'] == 'reset': state['hidden'] = []
                turn_results.append({'question': question, 'answer': r['answer'], 'trace': r['trace'],
                                     'reasoning': r.get('reasoning'), 'cost': r['cost'], 'route': r['route'],
                                     'citations': len(r['citations']),
                                     'item_ids': [i for c in r['citations'] for i in c.get('item_ids', [])],
                                     'commands': r.get('evidence', {}).get('scene', {}).get('commands', [])})
            verdict = grade(case, r)
            result = dict(case, doc_ids=docs, verdict=verdict, turns=turn_results, ms=round((time.perf_counter()-start)*1000))
        except Exception as exc:
            result = dict(case, doc_ids=docs, verdict='error', error=f'{type(exc).__name__}: {exc}', turns=turn_results)
        results.append(result)
        print(case['id'], result['verdict'], (turn_results[-1]['answer']['text_md'][:110] if turn_results else result.get('error')), flush=True)
        write_report(output, results, live, spent[0])
    return results


def write_report(name, rows, live, spent):
    categories = defaultdict(Counter)
    for r in rows:
        categories[r['category']][r['verdict']] += 1
    report = {'mode': 'live' if live else 'MODELS_FAKE=1', 'commit': os.environ.get('FIX_SUITE_CODE_REVISION') or subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
              'cases': len(rows), 'verdicts': dict(Counter(r['verdict'] for r in rows)),
              'categories': {k:dict(v) for k,v in categories.items()}, 'cost_usd': round(spent,6),
              'limitations': ['14 published inputs truncate questions or omit history; these use explicitly marked reconstructions.',
                               'Numeric/text checks are mechanical; prose and image-based expectations remain manual_review.',
                               'Fake model output is not evidence of accuracy. Unit conversion keeps answer.value metric; prose checked separately.'],
              'results': rows}
    (OUT / f'{name}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--live', action='store_true')
    p.add_argument('--budget', type=float, default=0)
    p.add_argument('--only', help='comma-separated case ids')
    args=p.parse_args()
    run(args.output, args.live, args.budget, set(args.only.split(',')) if args.only else None)
