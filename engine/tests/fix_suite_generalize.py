"""Final-only checks on real sources, including the preselected unopened DXF."""
from __future__ import annotations
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'results/final/FIX-SUITE'
RUNTIME=ROOT/'.fix-suite-runtime'


def main():
    os.environ.update(MODELS_FAKE='1',ARTIFACTS_DIR=str(RUNTIME/'artifacts'),MODELS_COSTS_LOG=str(RUNTIME/'model_calls.jsonl'))
    from engine.answer import answer
    from engine.solvers.data import load_doc
    root=RUNTIME/'artifacts'
    rows=[]
    for did,q in [('ifc_bench__ac20-arc','How many windows are 0.9 m wide and 2.0 m high?'),
                  ('ifc_bench__digital-hub-arc','Give a door schedule by width'),
                  ('cubicasa5k__colorful-11397','How big is the makuuhuone?')]:
        d=load_doc(did,root)
        r=answer(q,[did])
        ids={i for c in r['citations'] for i in c.get('item_ids',[])}
        if did.endswith('ac20-arc'):
            gold={i.item_id for i in d.items if i.kind=='window' and abs(i.q.get('width_m',0)-.9)<.0005 and abs(i.q.get('height_m',0)-2)<.0005}
            ok=r['answer']['value']==len(gold) and ids==gold
        elif d.mode=='ifc':
            gold={i.item_id for i in d.items if i.kind=='door'}
            ok=r['answer']['value']==len(gold) and ids==gold and '| Size | Count |' in r['answer']['text_md']
        else:
            gold={i.item_id for i in d.items if i.kind=='room' and i.props.get('room_type')=='bedroom'}
            ok=r['answer']['value'] is None and ids==gold and 'Which one' in r['answer']['text_md']
        rows.append({'doc_id':did,'mode':d.mode,'question':q,'expected_item_count':len(gold),'answer':r['answer'],'cited_items':len(ids),
                     'schema':d.meta.get('schema'),'applications':d.meta.get('applications'), 'pass':ok,'cost_usd':r['cost']['usd_total']})
    # First opening of the reserved source: all implementation work is complete.
    source=ROOT/json.loads((OUT/'reserved.json').read_text())['reserved_source']
    import ezdxf
    from pipeline import pages
    from pipeline.dxf_planmap import process
    started=time.perf_counter()
    raw=ezdxf.readfile(str(source))
    ms=raw.modelspace()
    text_labels=[e.plain_text() if e.dxftype()=='MTEXT' else e.dxf.text for e in ms.query('TEXT MTEXT') if e.dxf.layer=='ROOM_TEXT']
    labels=sorted({t for t in text_labels if t.strip() and not any(c.isdigit() for c in t) and not t.startswith('App.')})
    if not labels:
        raise RuntimeError('Reserved source has no named room labels; cannot perform the planned label lookup')
    label=labels[0]
    expected=sum(t==label for t in text_labels)
    did='reserved-final-dxf'
    art=RUNTIME/'blind'/did;art.mkdir(parents=True,exist_ok=True)
    _,_,_,w,h=pages.dxf_frame(pages.dxf_lines(raw))
    (art/'pages.json').write_text(json.dumps({'source':'dxf','pages':[{'w':w,'h':h}]}))
    (art/'doc.json').write_text(json.dumps({'doc_id':did,'kind':'dxf','title':source.stem,'pages':1,'formats':['dxf']}))
    conversion=process(did,art,source)
    os.environ['ARTIFACTS_DIR']=str(art.parent)
    q=f"How many rooms labelled '{label}' are there?"
    r=answer(q,[did])
    import jsonschema
    jsonschema.validate(r,json.loads((ROOT/'server/schemas/answer.schema.json').read_text()))
    ids={i for c in r['citations'] for i in c.get('item_ids',[])}
    ok=r['answer']['value']==expected and bool(r['citations']) and bool(r.get('reasoning')) and r['cost']['usd_total']==0
    rows.append({'reserved_source':str(source.relative_to(ROOT)),'first_opened_at_final_validation':True,
                 'origin':'Swiss Dwellings DXF','dxf_version':raw.dxfversion,'source_unit_code':raw.header.get('$INSUNITS'),
                 'question':q,'oracle':'Exact ROOM_TEXT source label occurrences, independent of polygon attribution',
                 'expected':expected,'answer':r['answer'],'cited_items':len(ids),'reasoning':r.get('reasoning'),
                 'conversion_counts':conversion['counts'],'elapsed_s':round(time.perf_counter()-started,3),'pass':ok,'cost_usd':r['cost']['usd_total']})
    report={'passed':sum(r['pass'] for r in rows),'of':len(rows),'rows':rows,'limitations':'Exercises answer/filter/schedule paths; does not claim support for every authoring tool or IFC schema.'}
    (OUT/'generality.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'of':len(rows),'reserved_expected':expected,'reserved_got':r['answer']['value']}))
    return 0 if all(x['pass'] for x in rows) else 1


if __name__=='__main__':
    raise SystemExit(main())
