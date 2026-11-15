"""Evaluate independent artifact origins without changing ingestion or source data."""
import json
import time
from pathlib import Path
from engine.kg.build import build_uncached
from engine.tests.test_kg_core import valid

ROOT=Path(__file__).resolve().parents[3]
ART=ROOT/'artifacts'
OUT=Path(__file__).parent


def run():
    rows=[]
    for source in ('swiss_dwellings','cubicasa5k'):
        candidates=sorted(p for p in ART.glob(source+'__*') if list(p.glob('planmap-[0-9]*.json')))
        if not candidates:
            rows.append({'source':source,'status':'unavailable'})
            continue
        did=candidates[0].name
        start=time.monotonic()
        graph=build_uncached({'id':'origin-'+source,'docs':[{'doc_id':did,'role':'plan'}]},ART)
        valid(graph)
        rows.append({'source':source,'doc_id':did,'elapsed_s':round(time.monotonic()-start,4),
                     'stats':graph['stats'],'warnings':graph.get('warnings',[]),'mep':graph.get('mep')})
        print(source,did,graph['stats']['nodes'],graph['stats']['edges'],flush=True)
    (OUT/'origin-validation.json').write_text(json.dumps(rows,indent=2))


if __name__=='__main__':
    run()
