"""Replay cached live outputs through final code; no live models or shared writes."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from PIL import Image
from pipeline.sheet_views import annotate_views
from server.vlm_planmap import build

OUT=Path(__file__).parent
for path in sorted(OUT.glob('*__*.json')):
    row=json.loads(path.read_text())
    with Image.open(row['source_image']) as image:
        pm=build(row['doc_id'],1,image.width,image.height,row['raw'],'gemini-4-carbon',0)
        pm.pop('view_analysis',None)
        pm=annotate_views(pm,[],image,dpi=row['dpi'][0] if row['dpi'] else None)
    row['planmap']=pm
    def counts(items):
        return {k:sum(i['kind']==k and float(i.get('conf') or 0)>=.5 for i in items) for k in ['door','window','room']}
    row['new_unfiltered_counts']=counts(pm['items'])
    row['after_counts']=counts([i for i in pm['items'] if not i.get('props',{}).get('excluded_from_plan_counts')])
    oldpath=ROOT/'artifacts'/row['doc_id']/'planmap-1.json'
    if not oldpath.exists():oldpath=ROOT/'data'/'vision_gen'/row['doc_id']/'planmap-1.json'
    if oldpath.exists():
        raw=oldpath.read_bytes()
        old=json.loads(raw)
        row['baseline_planmap_sha256']=hashlib.sha256(raw).hexdigest()
        scoped=annotate_views(old,[],views=pm.get('regions'))
        row['same_detections_after_scope']=counts([i for i in scoped['items'] if not i.get('props',{}).get('excluded_from_plan_counts')])
        row['excluded_original_detections']=row['before_counts']['room']-row['same_detections_after_scope']['room']
        assert oldpath.read_bytes()==raw
    path.write_text(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    print(row['doc_id'],row.get('before_counts'),'->',row.get('same_detections_after_scope'),flush=True)
