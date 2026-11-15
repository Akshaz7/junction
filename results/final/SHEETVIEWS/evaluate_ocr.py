"""Run real scan upload annotation in isolated folders (heavy.sh required)."""
import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from PIL import Image
from engine.scales import scale_anchors
from pipeline.scale_regions import annotate_cached
from server.vlm_planmap import build
OUT = Path(__file__).parent
for path in sorted(OUT.glob('*__*.json')):
    row=json.loads(path.read_text())
    if '--unseen-only' in sys.argv and row['doc_id'] != 'habs__az0258-sheet-00018':
        continue
    d=OUT/'.runtime'/row['doc_id']
    d.mkdir(exist_ok=True)
    src=Path(row['source_image']).resolve()
    page=d/'page-1.png'
    if not page.exists():
        if src.suffix.lower()=='.png':page.symlink_to(src)
        else:
            with Image.open(src) as image:
                opts={'dpi':image.info['dpi']} if image.info.get('dpi') else {}
                image.save(page,**opts)
    pm=build(row['doc_id'],1,*row['image'],row['raw'],'gemini-4-carbon',0)
    words=[{'text': i['label'],'bbox_px':i['bbox_px']} for i in pm['items'] if i.get('label') and i['kind']=='room']+pm.get('printed_scale_labels',[])
    (d/'text-1.json').write_text(json.dumps({'source':'vlm','image':pm['image'],'words':words}))
    start=time.monotonic()
    try:
        row['planmap']=annotate_cached(pm,d,allow_ocr=True)
        cache=d/'scale-ocr-1.json'
        ocr=json.loads(cache.read_text()) if cache.exists() else {'words':[]}
        row['ocr']={'words':len(ocr['words']),'scale_anchors':scale_anchors(ocr['words']),'elapsed_s':round(time.monotonic()-start,2)}
        row['scale_validation']='real upload annotation: existing model text supplemented with fresh local OCR'
    except Exception as e:
        row['ocr']={'error':type(e).__name__+': '+str(e)[:180]}
    path.write_text(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    print(row['doc_id'],row['ocr'],flush=True)
