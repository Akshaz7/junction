"""Final real-file check, including the randomly reserved untouched IFC.

No files in data/artifacts are modified. Run only after implementation is final,
via scripts/heavy.sh. Save small measurements / provenance, never source data.
"""
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
os.environ['MODELS_FAKE']='1'


def main():
    import ifcopenshell
    import ifcopenshell.util.element as E
    from pipeline.ifc_quantities import build
    from engine import ifc_quantities as Q
    from engine.solvers.data import Doc,Item
    from engine.reasoning import attach
    import jsonschema
    out=ROOT/'results/final/IFCQTY'
    heldout=json.loads((out/'holdout-final.json').read_text())['path']
    pilot=[json.loads(l) for l in (ROOT/'results/external/round2/pilot_questions.jsonl').read_text().splitlines()]
    origins=[next(r['path'] for r in pilot if r['doc_id']=='ext_ifcr2__viktor-samplebimmodelwebinar'),
             next(r['path'] for r in pilot if r['doc_id']=='ext_ifcr2__schependomlaan-design'),heldout]
    checks=[]
    schema=json.loads((ROOT/'server/schemas/answer.schema.json').read_text())
    for path in origins:
        start=time.perf_counter()
        f=ifcopenshell.open(str(ROOT/path))
        idx=build(f)
        items=[Item(r['item_id'],r['kind'],name=r['name'],q=r['quantities'],props={'ifc_class':r['ifc_class']}) for r in idx['rows']]
        doc=Doc('validation-model','ifc',items)
        original=Q.load_index
        Q.load_index=lambda doc:idx
        rows=[]
        try:
            for cls,noun in [('IfcWall','walls'),('IfcSlab','slabs')]:
                raw=f.by_type(cls)
                types=Counter(E.get_type(e).Name for e in raw if E.get_type(e) is not None and E.get_type(e).Name)
                if not types:
                    continue
                label,n=types.most_common(1)[0]
                question=f'How many {noun} of type "{label}" are there?'
                answer=Q.answer(question,doc)
                jsonschema.validate(answer,schema)
                rows.append({'question':question,'expected':n,'actual':answer['answer']['value'],
                             'pass':answer['answer']['value']==n,
                             'evidence_items':sum(len(c['item_ids']) for c in answer['citations']),
                             'calc':next(t['detail'] for t in answer['trace'] if t['step']=='calc')})
            raw=f.by_type('IfcReinforcingBar')
            answer=Q.answer('How many reinforcing bars are in this model?',doc)
            jsonschema.validate(answer,schema)
            rows.append({'question':answer['question'],'expected':len(raw),'actual':answer['answer']['value'],
                         'pass':answer['answer']['value']==len(raw)})
        finally:
            Q.load_index=original
        checks.append({'path':path,'reserved_untouched':path==heldout,'schema':f.schema,
                       'authoring_applications':sorted({a.ApplicationFullName for a in f.by_type('IfcApplication')}),
                       'index_rows':len(idx['rows']),'index_errors':idx['errors'],
                       'checks':rows,'seconds':round(time.perf_counter()-start,3)})
        print(path, f.schema, len(idx['rows']),'rows', sum(x['pass'] for x in rows),'/',len(rows),'pass',flush=True)
    (out/'real-files.json').write_text(json.dumps(checks,indent=1)+'\n')
    if not all(r['pass'] for c in checks for r in c['checks']):
        raise SystemExit(1)

if __name__=='__main__':
    main()
