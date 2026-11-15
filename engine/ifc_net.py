"""Read typed net areas with their own source units; keep old indexes read-only."""
from dataclasses import replace
from functools import lru_cache


@lru_cache(maxsize=2)
def _read(path, mtime_ns, size, key):
    import ifcopenshell
    from pipeline.ifc_scene import quantities_of
    from pipeline.ifc_accuracy import stored_net_area
    f = ifcopenshell.open(path)
    rows = {}
    for el in f.by_type('IfcSpace' if key == 'net_floor_area_m2' else 'IfcWall'):
        value = stored_net_area(el)[0] if key == 'net_floor_area_m2' else quantities_of(el, 1.).get(key)
        if value is not None:
            rows[el.GlobalId] = value
    return rows  # Never retain the parsed IFC file or change shared sidecars.


def refresh(doc, root, key):
    from engine.ifc_accuracy import source_path
    did = doc.meta.get('sheet_of') or doc.doc_id
    path = source_path(did, root)
    if path is None:
        return doc
    try:
        stat = path.stat()
        rows = _read(str(path.resolve()), stat.st_mtime_ns, stat.st_size, key)
    except (ImportError, OSError, ValueError, TypeError, RuntimeError, AttributeError, KeyError):
        return doc
    items = []
    for item in doc.items:
        value = rows.get(item.item_id)
        if value is None or value == item.q.get(key):
            items.append(item)
            continue
        record = {'doc_id': did, 'item_id': item.item_id, 'quantity': key,
                  'value': value, 'unit': 'm2', 'source_file': path.name}
        items.append(replace(item, q={**item.q, key: value},
                             props={**item.props, 'net_quantity_source': record}))
    return replace(doc, items=items)
