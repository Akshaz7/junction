"""Read-only local validation of scene edit arithmetic and exported opening support.

Usage: MODELS_FAKE=1 python -m engine.tests.validate_scene_files DOC_ID ... --output PATH
This does not establish source-drawing detection accuracy or substitute for screenshots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

from engine.answer import answer
from engine.scene_cmds import SceneIntent, scene_answer
from engine.solvers.data import load_doc
from server.scene_edits import fold


def validate(doc_id: str, root: Path) -> dict:
    doc = load_doc(doc_id, root)
    if doc is None:
        return {"doc_id": doc_id, "passed": False, "detail": "No readable document data"}
    manifest = json.loads((root / doc_id / 'scene.json').read_text())
    meta = json.loads((root / doc_id / 'doc.json').read_text())
    windows = [i.item_id for i in doc.items if i.kind == 'window' and i.item_id in manifest['items']]
    if len(windows) < 3:
        return {"doc_id": doc_id, "passed": False, "detail": "Fewer than three shared source/scene windows; cannot exercise two edit groups"}
    state = {"hidden": [], "edits": []}
    history = []
    def count():
        result = answer('How many windows are there?', [doc_id], scene_state=state, history=history)
        history.extend([{"role": "user", "content": 'How many windows are there?', "doc_ids": [doc_id]},
                        {"role": "assistant", "content": result['answer']['text_md'], "doc_ids": [doc_id]}])
        return result['answer']['value']
    def edit(command):
        state['edits'].append({**command, 'doc_id': doc_id, 'labels': command.get('labels', {})})
        state.update(fold(state['edits'])[doc_id])
    baseline = count()
    edit({'op': 'hide', 'item_ids': windows[:1]})
    edit({'op': 'hide', 'item_ids': windows[1:3]})
    removed = count()
    undo = answer('undo that', [doc_id], scene_state=state, history=history)
    for command in undo['evidence']['scene'].get('commands', []):
        edit(command)
    after_undo = count()
    edit({'op': 'restore', 'item_ids': []})
    restored = count()
    undo_restore = scene_answer('undo', doc, SceneIntent('undo'), state)
    for command in undo_restore['evidence']['scene'].get('commands', []):
        edit(command)
    after_restore_undo = count()
    edit({'op': 'highlight', 'item_ids': []})
    passed = (isinstance(baseline, (int, float)) and removed == baseline - 3
              and after_undo == baseline - 1 and restored == baseline
              and after_restore_undo == baseline - 1 and state['hidden'] == windows[:1])
    out = {"doc_id": doc_id, "source": meta.get('source'), "kind": meta.get('kind'), "mode": doc.mode,
           "passed": passed, "windows_before": baseline, "after_removing_three": removed,
           "after_group_undo": after_undo, "after_restore_all": restored,
           "after_undo_restore": after_restore_undo, "clear_preserves_hidden": state['hidden'] == windows[:1],
           "scene_items": len(manifest['items'])}
    if doc.mode == 'planmap':
        from pipeline.tests.measure_opening_gaps import measure
        try:
            out['opening_support'] = measure(root / doc_id)
        except (KeyError, ValueError) as error:
            out['opening_support'] = {"available": False, "detail": str(error)}
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('doc_ids', nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path('artifacts'))
    args = parser.parse_args()
    results = [validate(doc_id, args.root) for doc_id in args.doc_ids]
    report = {"created": datetime.now(timezone.utc).isoformat(), "results": results,
              "all_edit_checks_passed": all(r['passed'] for r in results),
              "visual_validation": "Blocked: Chromium launch SIGABRT/EPERM in Codex sandbox; screenshots pending"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['all_edit_checks_passed'] else 1)
