"""Inventory-based traces for catalogues, comparisons and rule findings."""
from dataclasses import asdict

from engine.calc import Row, input_value, record, source, step, summed


def metadata(res, docs, *, pages=False):
    rows = []
    for doc in docs:
        snapshot = {k: doc.get(k) for k in ("doc_id", "title", "pages", "formats", "kind", "mode", "source")}
        value = doc.get("pages") if pages else 1
        if isinstance(value, list): value = len(value)
        ref = {"kind": "metadata", "doc_id": doc["doc_id"], "page": 1, "field": "pages" if pages else "document present",
               "record": snapshot, "text": "Snapshot of the visible catalogue used for this answer"}
        rows.append(asdict(Row(doc["doc_id"], doc.get("title") or doc["doc_id"], {"pages" if pages else "documents": value}, ref)))
    return record(res, summed(res, rows, "pages" if pages else "documents", "sum the selected document metadata rows"))


def revisions(res, comparison):
    rows = []
    artifact = "elements.json" if comparison.get("method") == "ifc-globalid" else None
    for change in comparison.get("changes", []):
        side = change.get("v2") or change.get("v1")
        ref = {"kind": "element", "doc_id": side["doc_id"], "page": side.get("page", 1), "item_id": side["item_id"],
               "bbox": side.get("bbox_px"), "artifact": artifact or f"planmap-{side.get('page', 1)}.json", "field": "compared item"}
        rows.append(asdict(Row(change["change_id"], change["description"], {"changes": 1, "change_type": change["type"]}, ref)))
    return record(res, summed(res, rows, "changes", "change count = Σ(1 per detected change event)",
                               note="An element can contribute several events, such as movement and a property change. Events, not distinct elements, are counted."))


def findings(res, doc, matches, checked_rules):
    rows = []
    for finding in matches:
        ref = source(doc, field="elements checked by " + finding["rule_id"])
        ref["item_ids"] = finding.get("item_ids", [])
        rows.append(asdict(Row(finding["finding_id"], finding["title"], {"count": 1, "rule_id": finding["rule_id"]}, ref)))
    return record(res, summed(res, rows, "count", "issue count = Σ(1 per finding from the checked rules)",
                               note="Checked rules: " + ", ".join(checked_rules) + ". This is not a full compliance sign-off."))
