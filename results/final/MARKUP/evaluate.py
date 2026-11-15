"""Read-only real sheet evaluation. Outputs only to this worker's results directory.
Run through scripts/heavy.sh. Development gold is deliberately window-scoped.
"""
import json
from pathlib import Path
from engine.symbol_teach import find_similar
OUT = Path(__file__).parent

def evaluate(image, case):
    result = find_similar(image, case['template_bbox'])
    x0,y0,x1,y1 = case['validation_window']
    matches = [m for m in result['matches'] if x0 <= (m['bbox'][0]+m['bbox'][2])/2 < x1 and y0 <= (m['bbox'][1]+m['bbox'][3])/2 < y1]
    remaining = list(case['gold_centres'])
    tp = 0
    for m in matches:
        b = m['bbox']
        # Gold centres are hand clicks. Permit half a template size around a candidate.
        nearby = [g for g in remaining if b[0]-4 <= g[0] <= b[2]+4 and b[1]-4 <= g[1] <= b[3]+4]
        if nearby:
            remaining.remove(nearby[0]); tp += 1
    fp, fn = len(matches)-tp, len(case['gold_centres'])-tp
    return {**case, 'page_image': str(image), 'whole_sheet_candidates': len(result['matches']), 'window_candidates': len(matches), 'true_positive': tp, 'false_positive': fp, 'false_negative': fn, 'precision': tp/len(matches) if matches else None, 'recall': tp/len(case['gold_centres']) if case['gold_centres'] else None, 'matches_in_window': matches, 'ms': result.get('ms'), 'cost_usd': 0}

if __name__ == '__main__':
    gold=json.loads((OUT/'gold.json').read_text())
    import sys
    if '--unseen-only' in sys.argv:
        result = evaluate(Path('artifacts/wikimedia__36599716/page-1.png'), gold['unseen_final'])
        data=json.loads((OUT/'eval.json').read_text())
        data['unseen_random_id']='wikimedia__36599716'
        data['sheets']=[s for s in data['sheets'] if s['id'] != 'wikimedia__36599716']
        data['sheets'].append({'id':'wikimedia__36599716', 'cases':[result], 'final_only':True})
        (OUT/'eval.json').write_text(json.dumps(data,indent=2))
        print('Unseen final-only:', 'TP', result['true_positive'], 'FP', result['false_positive'], 'FN',result['false_negative'])
        raise SystemExit(0)
    if not (OUT/'local/vent.png').is_file():
        import pypdfium2
        (OUT/'local').mkdir(parents=True, exist_ok=True)
        pdf=pypdfium2.PdfDocument('data/judges/L30301_ventilation_3rd_floor_block_U.pdf')
        pdf[0].render(scale=1).to_pil().save(OUT/'local/vent.png')
    results=[evaluate(OUT/'local/vent.png', c) for c in gold['ventilation']]
    sports = evaluate(Path('artifacts/opening_design__sports-complex-transfer-archive-20150921-documents-to-address-permit-comments-to-printer-titlesheet/page-1.png'), gold['sports'])
    (OUT/'eval.json').write_text(json.dumps({'method':gold['method'], 'sheets':[{'id':'judges ventilation third floor', 'image_size':[4762,2526], 'cases':results}, {'id':'opening_design sports complex titlesheet', 'cases':[sports]}], 'model_calls':0, 'live_cost_usd':0}, indent=2))
    for c in results+[sports]: print(c['name'], 'TP',c['true_positive'],'FP',c['false_positive'],'FN',c['false_negative'],'whole sheet candidates',c['whole_sheet_candidates'])
