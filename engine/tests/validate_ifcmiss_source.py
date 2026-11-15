"""Inspect source IFC quantity/class provenance without changing any artifacts."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def inspect(did):
    import ifcopenshell
    from engine.ifc_accuracy import source_path
    from pipeline.ifc_accuracy import count_metadata
    from pipeline.ifc_scene import quantities_of, storey_of, kind_of
    p = source_path(did, ROOT / 'artifacts')
    if p is None:
        return {'doc_id': did, 'source': 'unavailable'}
    f = ifcopenshell.open(str(p))
    classes = Counter(e.is_a() for e in f.by_type('IfcProduct'))
    levels = defaultdict(lambda: {'count': 0, 'net_side_m2': 0., 'with_net_side': 0})
    for wall in f.by_type('IfcWall'):
        st = storey_of(wall)
        label = st.Name if st else 'unassigned'
        row = levels[label]
        row['count'] += 1
        q = quantities_of(wall, 1.)
        if 'net_side_area_m2' in q:
            row['net_side_m2'] += q['net_side_area_m2']
            row['with_net_side'] += 1
    counts = Counter()
    for el in f.by_type('IfcProduct'):
        if not count_metadata(el).get('count_component_of'):
            counts[kind_of(el)] += 1
    return {'doc_id': did, 'schema': f.schema,
            'applications': sorted({a.ApplicationFullName for a in f.by_type('IfcApplication') if a.ApplicationFullName}),
            'source_classes': dict(classes), 'native_counts_excluding_components': dict(counts),
            'wall_qto_by_storey': dict(levels)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('doc_ids', nargs='+')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    os.environ['MODELS_FAKE'] = '1'
    banned = set(Path('/private/tmp/claude-501/-Users-akshatthapa-Workspace-junction-server/bb83e630-bcda-48d0-8000-9c87e8300b2a/scratchpad/bench/forbidden_heldout_docs.txt').read_text().split())
    assert not set(args.doc_ids) & banned
    rows = [inspect(did) for did in args.doc_ids]
    Path(args.out).write_text(json.dumps({'documents': rows, 'source_files_written': False}, indent=2) + '\n')
    print(json.dumps([{'doc_id': r['doc_id'], 'schema': r.get('schema'), 'applications': r.get('applications'),
                       'walls': r.get('wall_qto_by_storey')} for r in rows]))


if __name__ == '__main__':
    main()
