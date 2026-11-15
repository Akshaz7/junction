"""Lightweight document graph built from the same item index as the solvers."""
from engine.solvers.data import load_doc


def build(doc_id, root):
    doc = load_doc(doc_id, root)
    if doc is None:
        return {'nodes': [], 'edges': []}
    nodes = []
    for it in doc.items:
        marked = it.props.get('confirmed_by_user', False)
        nodes.append({'id': it.item_id, 'kind': it.kind, 'label': it.label or it.name,
                      'page': it.page, 'bbox_px': it.bbox_px,
                      'method': 'user_label' if marked else it.source,
                      'confidence': 1.0 if marked else it.conf,
                      'taught_symbol_ids': [l['taught_symbol_id'] for l in it.props.get('user_labels', [])],
                      'linked_item_ids': it.props.get('linked_item_ids', [])})
    return {'doc_id': doc_id, 'nodes': nodes, 'edges': []}
