"""Run the unchanged sample200 questions against isolated artifact sidecars."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
os.environ['MODELS_FAKE'] = '1'
from engine import answer, bench

out = Path(__file__).parent
with tempfile.TemporaryDirectory(prefix='.sample-', dir=out) as scratch:
    root = Path(scratch)
    os.environ['MODELS_CACHE_DIR'] = str(root / 'cache')
    os.environ['MODELS_COSTS_LOG'] = str(root / 'costs.jsonl')
    os.environ['ARTIFACTS_DIR'] = str(root)
    questions = bench.load_set('sample200')
    for did in {q['doc_id'] for q in questions}:
        src = REPO / 'artifacts' / did
        if not src.is_dir():
            continue
        dst = root / did
        dst.mkdir()
        for p in src.iterdir():
            if p.suffix == '.json':
                shutil.copyfile(p, dst / p.name)
            elif p.suffix in {'.png', '.glb'}:
                (dst / p.name).symlink_to(p.resolve())
    result = bench.run(questions, answer_fn=lambda q, ds, history: answer.answer(q, ds, history), concurrency=2)
    (out / ('sample200-' + sys.argv[1] + '.json')).write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps(result['totals']))
    print(json.dumps(result['cells']['ALL x ALL']))
