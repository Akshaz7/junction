"""Final blind multi-file run. Selection was frozen before development; no ingest or calibration."""
import json
import time
from pathlib import Path

from engine.kg.build import build_uncached
from engine.tests.test_kg_core import valid
from pipeline.registry import doc_id_for

ROOT=Path(__file__).resolve().parents[3]
ART=ROOT/'artifacts'
OUT=Path(__file__).parent


def run():
    reserved=json.loads((OUT/'unseen.json').read_text())
    source,relative=reserved['group'].split('/',1)
    docs=[]
    files=[]
    for filename in reserved['files']:
        rel=relative+'/'+filename
        did=doc_id_for(source,rel)
        docs.append(did)
        folder=ART/did
        files.append({'filename':filename,'doc_id':did,'has_doc_metadata':(folder/'doc.json').is_file(),
                      'planmap_pages':len(list(folder.glob('planmap-[0-9]*.json'))),
                      'text_pages':len(list(folder.glob('text-[0-9]*.json')))})
    start=time.monotonic()
    graph=build_uncached({'id':'reserved-unseen','name':'Reserved unseen multi-file set','docs':docs},ART)
    valid(graph)
    report={'group':reserved['group'],'selection_before_development':True,'files':files,
            'elapsed_s':round(time.monotonic()-start,4),'stats':graph['stats'],
            'warnings':graph.get('warnings',[]),'mep':graph.get('mep'),
            'limitations':'This checks robustness and source-backed graph structure; link accuracy is unknown where no independent item truth exists.'}
    (OUT/'unseen-validation.json').write_text(json.dumps(report,indent=2))
    print('Reserved unseen set',report['elapsed_s'],graph['stats']['nodes'],graph['stats']['edges'],flush=True)


if __name__=='__main__':
    run()
