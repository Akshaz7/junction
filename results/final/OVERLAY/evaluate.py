"""Reproducible local-only evaluation. Source drawings are never staged.

Run with scripts/heavy.sh and the project Python. Uses no model calls.
"""
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
import pypdfium2 as pdfium
from engine.sheet_align import cached_alignment, load_pdf_page, manual_alignment

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/final/OVERLAY'
LOCAL = OUT / '.local'


def render(path, name):
    with pdfium.PdfDocument(path) as pdf:
        page = pdf[0]
        s = min(1, 1800/max(page.get_size()))
        bitmap = page.render(scale=s)
        image = bitmap.to_pil(); dest = LOCAL / f'{name}.png'; image.save(dest)
        bitmap.close(); page.close()
    return dest


def raster(path):
    with Image.open(path) as im: w,h = im.size
    return {'image': {'w': w,'h': h}, 'words': [], 'image_path': str(path), 'image_stamp': path.stat().st_mtime_ns}


def compact(result):
    return {k:v for k,v in result.items() if k not in {'anchors'}}


def main():
    LOCAL.mkdir(exist_ok=True)
    judges = ROOT/'data/judges'
    arch = judges/'ARK-103-03_floor_plan_3rd_floor.pdf'
    vent = judges/'L30301_ventilation_3rd_floor_block_U.pdf'
    start=time.monotonic()
    # Actual preview dimensions, not a DPI guessed from the PDF.
    with Image.open(judges/'p1.png') as im: arch_size=im.size
    with Image.open(judges/'p0.png') as im: vent_size=im.size
    a=load_pdf_page(arch,image_size=arch_size); b=load_pdf_page(vent,image_size=vent_size)
    result=cached_alignment(a,b)
    report={'judges': {'base': str(arch.relative_to(ROOT)), 'overlay': str(vent.relative_to(ROOT)),
                       'base_image': a['image'], 'overlay_image': b['image'], **compact(result), 'seconds': time.monotonic()-start}, 'real_raster_pairs': []}
    (LOCAL/'judges-alignment.json').write_text(json.dumps({**result,'base_image':a['image'],'overlay_image':b['image']}))
    origin=ROOT/'data/full/junction-dataset/data/opening_design'
    pairs=[('Crema Cafe', origin/'Crema_Cafe/Models/pdfs/A-100 - Floor Plans v3.pdf', origin/'Crema_Cafe/Transfer/20170509 - Markup to Maira/A-100 - Floor Plans v2.pdf'),
           ('Sports Complex', origin/'Sports_Complex/Models/2D/Sports Complex - Sheet - A-101 - First Floor Plan.pdf', origin/'Sports_Complex/Transfer/_Archive/20150428 - clean plans to owner/20150428 - XSC - Floor Plan.pdf')]
    for i,(name,p,q) in enumerate(pairs):
        t=time.monotonic(); x=render(p,f'pair{i}-base'); y=render(q,f'pair{i}-overlay')
        fit=cached_alignment(raster(x),raster(y))
        if fit['status']=='needs_manual' and name=='Sports Complex':
            # Evaluation-only manual clicks, read from the rendered sheets after auto-fit abstained.
            # Top-left fieldhouse corner and lower-right fieldhouse corner, then an unused third corner.
            fit['manual_check'] = manual_alignment([[281,428],[1346,970]], [[435,422],[1495,974]])
            matrix=np.asarray(fit['manual_check']['matrix'])
            check=np.array([1495,422]) @ matrix[:,:2].T + matrix[:,2]
            fit['manual_check']['third_corner_residual_px']=float(np.linalg.norm(check-[1346,428]))
            fit['manual_check']['note']='Evaluation-only visual picks on source rasters; no production coordinates. No millimetre claim.'

        report['real_raster_pairs'].append({'project':name,'base':str(p.relative_to(ROOT)),'overlay':str(q.relative_to(ROOT)), **compact(fit), 'seconds':time.monotonic()-t})
    report['model_calls']=0
    report['cost_usd']=0
    report['residual_note']='Residual is RMS agreement of accepted anchors, not a guarantee of building measurement accuracy. Millimetres are reported only from an explicit unambiguous PDF scale or trusted plan-map scale.'
    (OUT/'real-pairs.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    assert result['status']=='aligned'
    assert all(x['status']=='aligned' or x.get('manual_check',{}).get('status')=='manual' for x in report['real_raster_pairs'])


if __name__=='__main__': main()
