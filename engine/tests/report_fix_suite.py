"""Summarize measured before/after runs; no model calls or score substitutions."""
from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess

from engine.tests.run_fix_suite import grade

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results/final/FIX-SUITE'


def read(name):
    return json.loads((OUT/name).read_text())


def regrade(report):
    for row in report['results']:
        if row.get('turns'):
            row['verdict']=grade(row,row['turns'][-1])
    categories=defaultdict(Counter)
    for r in report['results']:
        categories[r['category']][r['verdict']]+=1
    report['verdicts']=dict(Counter(r['verdict'] for r in report['results']))
    report['categories']={k:dict(v) for k,v in categories.items()}
    return report


def tests(name):
    text=(OUT/name).read_text()
    summary=re.findall(r'(?:\d+ failed, )?\d+ passed(?:, \d+ skipped)? in [^\n]+',text)
    if not summary: raise RuntimeError(f'{name} is still running or has no pytest summary')
    return {'summary':summary[-1],'failures':sorted(re.findall(r'^FAILED (\S+)',text,re.M))}


def main():
    before=regrade(read('baseline-full.json'));after=regrade(read('after.json'))
    assert before['cases']==after['cases']==163
    b={r['id']:r for r in before['results']};a={r['id']:r for r in after['results']}
    reg=[i for i in b if b[i]['verdict']=='pass' and a[i]['verdict']!='pass']
    improved=[i for i in b if b[i]['verdict']!='pass' and a[i]['verdict']=='pass']
    comparison={k:{'before':before['categories'].get(k,{}),'after':after['categories'].get(k,{})}
                for k in sorted(set(before['categories'])|set(after['categories']))}
    def input_type(r):
        label=r['doc_label']
        if label=='(none)':return 'No selected document'
        if label.startswith(('ac20','digital')):return 'IFC'
        if label.startswith('colorful'):return 'Raster PNG'
        if label.startswith('swiss'):return 'DXF'
        if label.startswith(('up:home-plan','up:special-school')):return 'Scans'
        if label.startswith('up:'):return 'Stoa low-resolution sheets'
        return 'PDF drawing sets'
    inputs={}
    for kind in sorted({input_type(r) for r in a.values()}):
        inputs[kind]={phase:dict(Counter(r['verdict'] for r in report['results'] if input_type(r)==kind))
                      for phase,report in [('before',before),('after',after)]}
    exact={phase:dict(Counter(r['verdict'] for r in report['results'] if r['original_complete']))
           for phase,report in [('before',before),('after',after)]}
    after['comparison']={'baseline':'baseline-full.json','before':before['verdicts'],'after':after['verdicts'],
                         'by_category':comparison,'by_input_type':inputs,'improved_case_ids':improved,
                         'regressed_case_ids':reg,'original_complete_inputs_only':exact}
    # The published gold is retained, with a separate source-data discrepancy.
    raw=json.loads((ROOT/'.fix-suite-runtime/artifacts/ifc_bench__ac20-arc/elements.json').read_text())
    lab_ids=set(a['C08']['turns'][-1]['item_ids'])
    areas=[e['quantities']['net_floor_area_m2'] for e in raw['elements'] if e['item_id'] in lab_ids and e['kind']=='room']
    after['gold_discrepancies']=[{'case':'C08','published_gold':'5 labs, 59.1 m²','source_room_areas_m2':areas,
                                'source_sum_m2':sum(areas),'note':'Do not alter source quantities to reproduce a rounded or incorrect gold total.'}]
    after['grading_notes']=['Mechanical checks are a lower bound on passing cases: prose/image rubrics remain manual_review.',
                            'Textual quantities are scored with explicit units; citation numbers cannot satisfy a numeric gold.',
                            '14 incomplete published inputs use documented reconstructions; original-only scores are separate.',
                            'Local catalogue size differs from the deployed Data catalogue; N01 is not graded against the historical live count.',
                            'Warm disk/model caches are used. These timings do not prove cold-upload latency or HTTP/SSE behavior.']
    (OUT/'baseline-full.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
    (OUT/'baseline.json').write_text(json.dumps(before,ensure_ascii=False,indent=2)+'\n')
    (OUT/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2)+'\n')
    bs=read('sample200-before.json');aa=read('sample200-after.json')
    rows=lambda p:[json.loads(l) for l in (OUT/p).read_text().splitlines()]
    key=lambda r:(r['doc_id'],r['question'])
    bb={key(r):r for r in rows('sample200-before.rows.jsonl')};ab={key(r):r for r in rows('sample200-after.rows.jsonl')}
    bench_reg=[{'doc_id':k[0],'question':k[1],'before':bb[k]['value'],'after':ab[k]['value']} for k in bb if bb[k]['outcome']=='correct' and ab[k]['outcome']!='correct']
    baseline_tests=tests('baseline-engine-all.log');final_tests=tests('engine-tests.log')
    new_failures=sorted(set(final_tests['failures'])-set(baseline_tests['failures']))
    paid=[]
    for line in (ROOT/'.fix-suite-runtime/model_calls.jsonl').read_text().splitlines():
        try:r=json.loads(line)
        except ValueError:continue
        if r.get('cost_usd',0):paid.append({k:r.get(k) for k in ('provider','task','model','cost_usd','cache_hit','request_id')})
    usd=round(sum(r['cost_usd'] for r in paid),6)
    (OUT/'costs.json').write_text(json.dumps({'usd_total':usd,'calls':paid},indent=2)+'\n')
    result={'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'judge_suite':{'before':before['verdicts'],'after':after['verdicts'],'improved':improved,'regressions':reg},
            'sample200':{'mode':'MODELS_FAKE=1; all 200 cases executed in each run','before':bs['cells']['ALL x ALL'],
                         'after':aa['cells']['ALL x ALL'],'regressions':bench_reg},
            'engine_tests':{'command':'MODELS_FAKE=1 python -m pytest engine/tests --ignore=engine/tests/test_models.py -q',
                            'before':baseline_tests,'after':final_tests,'new_failures':new_failures},
            'generality':read('generality.json'),'total_logged_model_cost_usd':usd,
            'cross_file':['engine/library.py','engine/units.py'],
            'limitations':['58 prose/visual cases remain outside the mechanical grader; no claim that the full judge suite is green.',
                           'Existing failing baseboard/piping/PDF/readdraw tests are reported; model-adapter tests excluded.',
                           'PDF ingestion, deployment, HTTP rate limits, UI interaction and every IFC schema/authoring tool are not validated by this row.']}
    (OUT/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    assert not reg and not bench_reg and not new_failures,(reg,bench_reg,new_failures)
    assert usd<3
    print(json.dumps({'suite_before':before['verdicts'],'suite_after':after['verdicts'],'sample200_correct':aa['cells']['ALL x ALL']['correct'],
                      'regressions':len(reg)+len(bench_reg)+len(new_failures),'usd':usd}))


if __name__=='__main__':
    main()
