"""End-only generality check: never inspected or used to develop the algorithm."""
import json
from pathlib import Path
from PIL import Image
from engine.sheet_align import cached_alignment

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/final/OVERLAY'


def sheet(path):
    with Image.open(path) as image: w,h=image.size
    return {'image': {'w':w,'h':h}, 'words': [], 'image_path':str(path), 'image_stamp':path.stat().st_mtime_ns}


def main():
    chosen=ROOT/json.loads((OUT/'reserved.json').read_text())['reserved_unseen']
    other=chosen.with_name(chosen.name.replace('_original','_scaled'))
    result=cached_alignment(sheet(chosen),sheet(other))
    unrelated=cached_alignment(sheet(chosen),sheet(OUT/'.local/pair0-overlay.png'))
    report={'reserved_unseen':str(chosen.relative_to(ROOT)), 'real_export_pair':str(other.relative_to(ROOT)),
            'pair':{k:v for k,v in result.items() if k!='anchors'},
            'unrelated_pair':{k:v for k,v in unrelated.items() if k!='anchors'},
            'policy':'First opened and tested after implementation and unit tests. No tuning or training on this drawing.',
            'model_calls':0,'cost_usd':0}
    (OUT/'reserved-result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    assert result['status']=='aligned'
    assert unrelated['status']=='needs_manual'


if __name__=='__main__': main()
