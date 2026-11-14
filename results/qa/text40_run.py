"""E-35 local check: generated for demo, not dataset or held-out accuracy.

Run through scripts/heavy.sh .venv/bin/python results/qa/text40_run.py r1|r2.
The preview's 265 text questions all map to held-out artifact IDs, so none
can be used for this development check. Gold below is copied from clean PDFs.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def build():
    from engine.reader.text import PageText, build_segments
    held = set((REPO / 'data/sets/heldout_docs.txt').read_text().splitlines())
    rows = []

    def add(did, field, question, gold):
        assert did not in held
        t = json.loads((REPO / 'artifacts' / did / 'text-1.json').read_text())
        pt = PageText(did, 1, t['image']['w'], t['image']['h'], t['words'])
        segs = build_segments(pt)
        matches = [s for s in segs if gold in s['text']]
        # Multi-line project name: preserve each exact source line separately.
        if not matches and gold == 'Xcel Sports Complex':
            matches = [s for s in segs if s['text'] in ('Xcel', 'Sports Complex')]
        assert matches, (did, gold)
        rows.append(dict(question=question, doc_id=did, gold=gold, type='text',
                         origin='generated for demo', field=field, page=1,
                         gold_sources=[dict(quote=s['text'], bbox_px=s['bbox_px']) for s in matches]))

    for num in ('601', '602', '603', '610', '650'):
        title = {'610': 'plan-details', '650': 'details'}.get(num, 'section-details')
        did = f'opening_design__sports-complex-sheets-current-set-a-{num}-{title}-exterior-envelope'
        vals = [
            ('sheet_number', 'What is the sheet number in the title block?', f'A-{num}'),
            ('scale', 'What scale is printed in the title block?', 'As indicated' if num == '650' else '3" = 1\'-0"'),
            ('date', 'What date is printed beside Date in the title block?', '2/10/2016'),
            ('project_name', 'What is the project name in the title block?', 'Xcel Sports Complex'),
            ('architect', 'Which architect is listed on this sheet?', 'OpeningDesign'),
            ('revision', 'What is the description of revision 3 on this sheet?', 'ADDENDUM 1'),
        ]
        for field, question, gold in vals:
            add(did, field, question, gold)
    for sheet, title, date in [('A500', 'ada-restroom-schedules', '05.03.2017'),
                               ('A402', 'exterior-details', '04.10.2017')]:
        did = f'opening_design__vacation-rental-transfer-20170503-issue-for-permit-{sheet.lower()}-{title}'
        for field, question, gold in [
            ('sheet_number', 'What sheet number is printed in the title block?', sheet),
            ('date', 'What issue date is listed in the title block?', date),
            ('project_name', 'What project name is printed in the title block?', 'The Downtowner'),
            ('architect', 'Who is the architect listed on this sheet?', 'OpeningDesign'),
            ('owner', 'Who is the owner listed on this sheet?', 'FYF LLC.'),
        ]:
            add(did, field, question, gold)
    assert len(rows) == 40
    (REPO / 'results/qa/text40.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))


def normal(s):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKC', str(s)).casefold())


def run(revision):
    from dotenv import dotenv_values
    keys = dotenv_values(REPO / '.env')  # never print or export secrets
    has_keys = any(keys.get(k) for k in ('GEMINI_API_KEY', 'NVIDIA_API_KEY', 'ANTHROPIC_API_KEY',
                                        'RUNWARE_API_KEY', 'FEATHERLESS_API_KEY'))
    if has_keys:
        os.environ.pop('MODELS_FAKE', None)
    else:
        os.environ['MODELS_FAKE'] = '1'
    # Keep benchmark-generated caches out of other workers' artifact folders.
    os.environ['MODELS_CACHE_DIR'] = '/tmp/junction-engine2-model-cache'
    os.environ['MODELS_COSTS_LOG'] = str(REPO / f'results/qa/text40-{revision}-costs.jsonl')
    from engine.answer import answer
    rows = [json.loads(l) for l in (REPO / 'results/qa/text40.jsonl').read_text().splitlines()]
    held = set((REPO / 'data/sets/heldout_docs.txt').read_text().splitlines())
    assert not any(x['doc_id'] in held for x in rows)
    start = time.perf_counter()
    results = []
    out = REPO / f'results/qa/text40-{revision}.json'

    def one(row):
        a = answer(row['question'], [row['doc_id']])
        text = a['answer']['text_md']
        correct = not a['answer']['abstained'] and normal(row['gold']) in normal(text)
        return {**row, 'correct': correct, 'result': a}

    def save():
        summary = dict(total=len(results), correct=sum(x['correct'] for x in results),
                       answered=sum(not x['result']['answer']['abstained'] for x in results),
                       cost_usd=round(sum(x['result']['cost']['usd_total'] for x in results), 6))
        payload = dict(revision=revision, origin='generated for demo', dataset_questions=0,
                       eligible_dataset_text_questions=0, excluded_heldout_text_questions=265,
                       note='All 16 opening_design PDF text questions (and all 249 IFC text questions) are held out. '
                            'These 40 manually grounded development questions are NOT dataset accuracy.',
                       provider_mode='real providers available; MODELS_FAKE unset' if has_keys else 'fake; code path only',
                       grade='non-abstained, normalized gold contained in answer (NFKC, casefold, alphanumeric)',
                       elapsed_s=round(time.perf_counter() - start, 2), summary=summary, results=results)
        out.write_text(json.dumps(payload, indent=2))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for row in pool.map(one, rows):
            results.append(row)
            save()
            print(f"{revision} {len(results)}/40 correct={sum(x['correct'] for x in results)}", flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'build':
        build()
    else:
        run(sys.argv[1])
