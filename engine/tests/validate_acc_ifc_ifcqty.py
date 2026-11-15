"""Read-only integration check against the IFCQTY commit named in the handoff."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    os.environ.update(MODELS_FAKE='1', EXPLAIN='0')
    revision = '8b79bcf'
    for package in ('pipeline', 'engine'):
        name = f'{package}.ifc_quantities'
        source = subprocess.check_output(['git', 'show', f'{revision}:{package}/ifc_quantities.py'], cwd=ROOT, text=True)
        module = types.ModuleType(name)
        module.__file__ = f'{revision}:{package}/ifc_quantities.py'
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    from engine.tests.test_acc_ifc import model, entity, aggregate, document, room
    from engine.solvers.data import load_doc
    from engine.ifc_accuracy import guard, checked_analytics
    import engine.ifc_quantities as Q
    import ifcopenshell
    import jsonschema
    checks = []
    with tempfile.TemporaryDirectory(prefix='acc-ifc-ifcqty-') as tmp:
        root = Path(tmp)
        os.environ['ARTIFACTS_DIR'] = str(root)
        f = model()
        parent, child = entity(f, 'IfcWall', 'Parent'), entity(f, 'IfcWall', 'Part')
        typ = entity(f, 'IfcWallType', 'Assembly wall', PredefinedType='NOTDEFINED')
        entity(f, 'IfcRelDefinesByType', RelatedObjects=[parent, child], RelatingType=typ)
        aggregate(f, parent, child)
        room(f, net=100)
        did = document(root, f)
        (root / did / 'doc.json').write_text(json.dumps({'files': {'ifc': str(root / did / 'source.ifc')}}))
        doc = load_doc(did, root)
        question = 'How many walls of type "Assembly wall" are there?'
        old = Q.answer(question, doc, time.perf_counter())
        before = old['answer']['value']
        fixed = guard(old, question, [did], root)
        checks.append({'check': 'IFCQTY filtered-count route + ACC-IFC hierarchy guard', 'before': before,
                       'after': fixed['answer']['value'], 'expected': 1,
                       'pass': before == 2 and fixed['answer']['value'] == 1 and fixed['citations'][0]['item_ids'] == [parent.GlobalId]})
        schema = json.loads((ROOT / 'server/schemas/answer.schema.json').read_text())
        jsonschema.validate(fixed, schema)
        # The decorator preserves IFCQTY's original early hook, with operands
        # normalised before every remaining analytics handler.
        from engine.analytics import filtered_question
        @checked_analytics
        def merged_run(question, doc, t0, solve_fn=None):
            return Q.answer(question, doc, t0) or filtered_question(question, doc, t0)
        area = merged_run('What is the area of the room "101"?', doc, time.perf_counter())
        # Exact numeric room labels use the normal solver, not named-room analytics.
        from engine.solvers.solve import solve
        area = area or solve('What is the area of room 101?', did, root=root)
        jsonschema.validate(area, schema)
        checks.append({'check': 'Measured room area alongside IFCQTY sidecar', 'after': area['answer']['value'], 'expected': 12,
                       'pass': area['answer']['value'] == 12 and any('-> flag' in t['detail'] for t in area['trace'])})
    result = {'ifcqty_revision': revision, 'checks': checks, 'models_fake': True, 'shared_artifacts_written': False}
    (ROOT / 'results/final/ACC-IFC/ifcqty-compatibility.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    assert all(c['pass'] for c in checks)


if __name__ == '__main__':
    main()
