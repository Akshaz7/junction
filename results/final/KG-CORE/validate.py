"""Reproducible real-artifact validation. Run via scripts/heavy.sh with MODELS_FAKE=1."""
import json
import time
from collections import Counter
from pathlib import Path

from engine.kg.build import build_uncached
from engine.tests.test_kg_core import valid
from server.projects_routes import DEMO_FAMILIES

ROOT=Path(__file__).resolve().parents[3]
ART=ROOT/'artifacts'
OUT=Path(__file__).parent


def run():
    rows=[]
    for name,predicate in DEMO_FAMILIES:
        docs=[p.name for p in ART.iterdir() if p.is_dir() and predicate(p.name.lower()) and (p/'doc.json').is_file()]
        start=time.monotonic()
        graph=build_uncached({'id':'kg-core-validation-'+str(len(rows)),'name':name,'docs':docs},ART)
        elapsed=time.monotonic()-start
        valid(graph)
        rows.append({'name':name,'doc_ids':docs,'elapsed_s':round(elapsed,4),'under_30_s':elapsed<30,
                     'stats':graph['stats'],'methods':dict(Counter(e['method'] for e in graph['edges'])),
                     'warnings':graph.get('warnings',[])})
        print(name,round(elapsed,3),graph['stats']['nodes'],graph['stats']['edges'],flush=True)
    (OUT/'demo-validation.json').write_text(json.dumps(rows,indent=2))
    assert all(r['under_30_s'] for r in rows)


if __name__=='__main__':
    run()
