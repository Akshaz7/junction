"""Final real-file and reserved-file validation. No tuning after blind results.

Run through scripts/heavy.sh only after implementation and unit tests pass.
Shared source files and artifacts are read only; blind ingestion uses /tmp.
"""
import json
import os
import re
from pathlib import Path
import sys
import tempfile
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'results/final/MUNICHQ'
os.environ['MODELS_FAKE']='1'
os.environ['EXPLAIN']='0'


def main():
    import ifcopenshell
    from engine.answer import answer
    from engine.ifc_quantities import _source
    from engine.solvers.data import load_doc
    from pipeline.ifc_index import process
    from engine.tests.run_munichq import QUESTIONS
    reports=[]
    saved=json.loads((OUT/'questions.after.json').read_text())
    for did in ['ifc_bench__city-house-munich-arc','ifc_bench__ac20-arc','ext_ifcr2__bsi-ifc4-building-architecture']:
        source=_source(did,ROOT/'artifacts')
        f=ifcopenshell.open(str(source))
        overview=next(r for r in saved if r['doc_ids']==[did] and r['question']==QUESTIONS[0])
        checks=[]
        for cls,n in overview['ifc_overview']['class_counts'].items():
            native=len(f.by_type(cls,include_subtypes=False))
            checks.append({'check':cls+' indexed count agrees with native IFC class inventory','expected':native,'actual':n,'pass':n==native})
        native_storeys=f.by_type('IfcBuildingStorey')
        import ifcopenshell.util.unit as U
        scale=U.calculate_unit_scale(f)
        raw_levels=len({(re.sub(r'[^\w]','',re.sub(r'^\d+\s*[.:_-]\s*','',s.Name or '').casefold()),
                         round(s.Elevation*scale,4) if s.Elevation is not None else None) for s in native_storeys})
        shown=len(overview['ifc_overview']['levels'])
        checks.append({'check':'deduplicated indexed levels agree with distinct native IFC labels/elevations','raw_storey_entities':len(native_storeys),'expected':raw_levels,'actual':shown,'pass':raw_levels==shown})
        reports.append({'doc_id':did,'source':str(source.relative_to(source.parents[0])),'schema':f.schema,
                        'authoring_applications':[a.ApplicationFullName for a in f.by_type('IfcApplication')],
                        'checks':checks})
        del f
    # Open the reserved file for the first time here, after all implementation.
    blind=ROOT/json.loads((OUT/'blind.json').read_text())['path']
    with tempfile.TemporaryDirectory(prefix='munichq-blind-') as temp:
        root=Path(temp)
        did='blind-reserved-model'
        folder=root/did;folder.mkdir()
        doc={'doc_id':did,'kind':'ifc','title':'Reserved unseen IFC','formats':['ifc'],'files':{'ifc':str(blind)}}
        (folder/'doc.json').write_text(json.dumps(doc))
        process(blind,doc,folder)
        os.environ['ARTIFACTS_DIR']=str(root)
        loaded=load_doc(did,root)
        responses=[answer(q,[did]) for q in QUESTIONS]
        summary=[]
        for r in responses:
            summary.append({'question':r['question'],'answer':r['answer'],'citations':len(r['citations']),
                            'reasoning_label':r.get('reasoning',{}).get('confidence',{}).get('label'),
                            'quantity_rows':len(r.get('quantity_rows',[])),
                            'calc_status':r.get('reasoning',{}).get('calc',{}).get('status')})
        f=ifcopenshell.open(str(blind))
        counts=responses[0].get('ifc_overview',{}).get('class_counts',{})
        checks=[{'check':cls+' count matches native IFC','expected':len(f.by_type(cls,include_subtypes=False)),
                 'actual':n,'pass':n==len(f.by_type(cls,include_subtypes=False))} for cls,n in counts.items()]
        checks.append({'check':'all answers have evidence cards and no error route','pass':all(r.get('reasoning') and r['route']!='error' for r in responses)})
        checks.append({'check':'no zero-length service answer','pass':responses[2]['answer']['value']!=0})
        reports.append({'doc_id':did,'path':str(blind.relative_to(ROOT)),'reserved_untouched_until_final':True,
                        'schema':f.schema,'authoring_applications':[a.ApplicationFullName for a in f.by_type('IfcApplication')],
                        'checks':checks,'answers':summary})
    (OUT/'real-files.json').write_text(json.dumps(reports,indent=1)+'\n')
    print(json.dumps([{'doc_id':r['doc_id'],'schema':r['schema'],'apps':r['authoring_applications'],
                       'passed':sum(c['pass'] for c in r['checks']),'checks':len(r['checks'])} for r in reports],indent=1),flush=True)
    if not all(c['pass'] for r in reports for c in r['checks']):
        raise SystemExit(1)


if __name__=='__main__':
    main()
