"""Do not guess missing quantities while an IFC has only a property index."""
import json


def missing_quantity(res, doc_ids, root):
    if res is None or not res.get("answer", {}).get("abstained") or len(doc_ids) != 1:
        return False
    try:
        index = json.loads((root / doc_ids[0] / "elements.json").read_text())
    except (OSError, ValueError):
        return False
    return index.get("geometry") == "pending"
