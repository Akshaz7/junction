"""Read-only validation; run via heavy.sh. Never opens the reserved file in dev."""
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PIL import Image
from engine.models import call
from engine.scales import scale_anchors
from pipeline.sheet_views import annotate_views
from server.vlm_planmap import PROMPT, SCHEMA, build

OUT = Path(__file__).parent
RUNTIME = OUT / '.runtime'
RUNTIME.mkdir(exist_ok=True)
os.environ['MODELS_CACHE_DIR'] = str(RUNTIME/'cache')
os.environ['MODELS_COSTS_LOG'] = str(OUT/'model_costs.jsonl')
source = json.loads((OUT/'candidates.json').read_text())
selected = [source[k] for k in [0, 3, 10, 13, 14, 15, 25, 28, 35, 47, 48]]
more = json.loads((OUT/'more-candidates.json').read_text())
selected += [more[k] for k in [0, 1, 3, 10]]
if '--final-unseen' in sys.argv:
    file = Path(json.loads((OUT/'selection.json').read_text())['random_unseen_file'])
    selected = [(file.parent.name+'__'+re.sub(r'[^a-z0-9]+','-',file.stem.lower()).strip('-'), str(file))]
rows = []
spent = 0
if (OUT/'model_costs.jsonl').exists():
    spent = sum(json.loads(line).get('cost_usd', 0) for line in (OUT/'model_costs.jsonl').read_text().splitlines())
for did, file in selected:
    dest = OUT/(did+'.json')
    if dest.exists() and '--refresh' not in sys.argv:
        rows.append(json.loads(dest.read_text()))
        continue
    if spent >= 2.75:
        raise RuntimeError('Row live budget nearly exhausted')
    start = time.monotonic()
    with Image.open(file) as original:
        W, H = original.size
        dpi = original.info.get('dpi')
        image = original.convert('RGB')
    page = RUNTIME/(did+'.jpg')
    preview = image.copy()
    preview.thumbnail((2048,2048))
    preview.save(page, quality=90)
    response = call('read_drawing', [{'role':'user', 'content': PROMPT}], images=[page], schema=SCHEMA, only=('runware_oai','gemini-4-carbon'))
    spent += response.cost_usd
    raw = response.json or {}
    pm = build(did, 1, W, H, raw, response.model, 0)
    # This is exactly the upload annotation hook: rendered-space words + DPI.
    pm.pop('view_analysis', None)
    pm = annotate_views(pm, [], image, dpi=dpi[0] if dpi else None)
    old_path = ROOT/'artifacts'/did/'planmap-1.json'
    if not old_path.exists():
        old_path = ROOT/'data'/'vision_gen'/did/'planmap-1.json'
    old = json.loads(old_path.read_text()) if old_path.exists() else None
    def counts(items):
        return {kind:sum(i.get('kind')==kind and float(i.get('conf') or 0)>=.5 for i in items) for kind in ['door','window','room']}
    eligible = [i for i in pm['items'] if not i.get('props',{}).get('excluded_from_plan_counts')]
    row = {'doc_id':did,'source_image':file,'image':[W,H],'dpi':dpi,'is_plan':raw.get('is_plan'),
           'raw':raw,'planmap':pm,'before_counts':counts(old['items']) if old else None,
           'before_scale':old.get('scale') if old else None,
           'new_unfiltered_counts':counts(pm['items']), 'after_counts':counts(eligible),
           'cost_usd':response.cost_usd,'elapsed_s':round(time.monotonic()-start,2),
           'manual_check':None}
    dest.write_text(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    rows.append(row)
    print(json.dumps({'doc_id':did,'views':len(pm.get('regions',[])), 'before':row['before_counts'],'after':row['after_counts'],'cost':response.cost_usd,'spent':spent}),flush=True)
(OUT/('real-unseen.json' if '--final-unseen' in sys.argv else 'real-development.json')).write_text(json.dumps([{k:v for k,v in r.items() if k not in {'raw','planmap'}} for r in rows],indent=2,ensure_ascii=False)+'\n')
