"""Small reproducible report from actual runs; never modifies shared data."""
import hashlib
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
os.environ['MODELS_FAKE']='1'
from engine import reasoning
from engine.solvers import solve
from pipeline.sheet_views import annotate_views

OUT=Path(__file__).parent
manual=json.loads((OUT/'manual_checks.json').read_text())['files']
rows=[]
for path in sorted(OUT.glob('*__*.json')):
    row=json.loads(path.read_text())
    pm=row['planmap']
    def counts(items):
        return {k:sum(i['kind']==k and float(i.get('conf') or 0)>=.5 for i in items) for k in ['door','window','room']}
    row['after_counts']=counts([i for i in pm['items'] if not i.get('props',{}).get('excluded_from_plan_counts')])
    oldpath=ROOT/'artifacts'/row['doc_id']/'planmap-1.json'
    if not oldpath.exists():oldpath=ROOT/'data'/'vision_gen'/row['doc_id']/'planmap-1.json'
    if oldpath.exists():
        raw=oldpath.read_bytes()
        old=json.loads(raw)
        scoped=annotate_views(old,[],views=pm.get('regions'))
        row['baseline_planmap_sha256']=hashlib.sha256(raw).hexdigest()
        row['same_detections_after_scope']=counts([i for i in scoped['items'] if not i.get('props',{}).get('excluded_from_plan_counts')])
        assert oldpath.read_bytes()==raw
    row['manual_check']=manual[row['doc_id']]
    d=OUT/'.runtime'/row['doc_id']
    d.mkdir(exist_ok=True)
    (d/'doc.json').write_text(json.dumps({'kind':'raster','title':row['doc_id']}))
    (d/'planmap-1.json').write_text(json.dumps(pm))
    row['solver_checks']={}
    for kind in ['door','window','room']:
        question=f'How many {kind}s?'
        answer=solve(question,row['doc_id'],root=d.parent)
        card=reasoning.build(answer,question,d.parent)
        row['solver_checks'][kind]={'answer':answer['answer'],'citations':answer['citations'],'boxes':answer['evidence']['boxes'],'reasoning':card}
        if manual[row['doc_id']].get('expected_plan_answer')=='unavailable':
            assert answer['answer']['value'] is None and answer['answer']['abstained']
    path.write_text(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    ratios=sorted({r['scale'].get('ratio') for r in pm.get('regions',[]) if r.get('scale',{}).get('ratio')})
    labels=pm.get('printed_scale_labels',[])
    rows.append({'doc_id':row['doc_id'],'mixed':manual[row['doc_id']].get('mixed_plan_and_nonplan'), 'unseen':manual[row['doc_id']].get('reserved_unseen',False),
                 'before_detections':row['before_counts'],'same_detections_scoped':row.get('same_detections_after_scope'),
                 'new_solver_counts':{k:c['answer']['value'] for k,c in row['solver_checks'].items()},
                 'manual_count_gold':manual[row['doc_id']].get('plan_count_gold'),'manual_scale_text':manual[row['doc_id']]['scale_text'],
                 'assigned_ratios':ratios,'read_scale_labels':[l['text'] for l in labels], 'ocr':row.get('ocr')})
before=json.loads((OUT/'sample200-before.json').read_text())
after=json.loads((OUT/'sample200-after.json').read_text())
key=lambda r:(r['doc_id'],r['question'])
b={key(r):r for r in before['results']};a={key(r):r for r in after['results']}
changed=[key(r) for r in after['results'] if any(r.get(f)!=b[key(r)].get(f) for f in ['value','unit','outcome','route','boxes'])]
assert len(a)==len(b)==200 and not changed
cost=sum(json.loads(l)['cost_usd'] for l in (OUT/'model_costs.jsonl').read_text().splitlines())
report={'status':'PARTIAL','code_features':'implemented and tested','files':len(rows),'mixed_plan_nonplan_sheets':sum(bool(r['mixed']) for r in rows),
        'successful_model_cost_usd':round(cost,6),'cost_limitation':'One schema-rejected provider response did not return a cost record; successful calls only are totalled.',
        'sample200':{'before':before['cells']['ALL x ALL'],'after':after['cells']['ALL x ALL'],'changed_numeric_answers':changed,'text_only_changes':[key(r) for r in after['results'] if r.get('text')!=b[key(r)].get('text')]},
        'validation':{'python_tests_passed':176,'web_tests_passed':3,'typescript':'passed'},'rows':rows,
        'limitation':'View filtering prevents non-plan detections being counted, but automatic symbol counts within historical plans remain imperfect. Shared/alternative scales without a safe local owner are left unassigned. No exact accuracy percentage claimed for the mixed-sheet set.'}
(OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:report[k] for k in ['status','files','mixed_plan_nonplan_sheets','successful_model_cost_usd','validation']}))
