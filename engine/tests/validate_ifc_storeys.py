"""Run with scripts/heavy.sh; read IFC properties, never rewrite source artifacts."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import ifcopenshell.util.unit as uunit
import jsonschema

from engine.analytics import storey_compare
from engine.ifc_storeys import canonical_storeys
from engine.solvers import solve
from engine.solvers.data import load_doc
from engine.solvers.solve import resolve_storey
from pipeline.ifc_index import open_properties
from pipeline.ifc_props import building_meta
from pipeline.ifc_scene import storey_of

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results/final/STOREYS"


def validate(path, doc_id, temporary_root, blind=False):
    model = open_properties(path)
    unit = uunit.get_project_unit(model, "LENGTHUNIT")
    scale = uunit.calculate_unit_scale(model) if unit is not None else None

    def level(entity):
        return {"name": entity.Name or "Unnamed level", "elevation_m":
                round(float(entity.Elevation) * scale, 4) if entity.Elevation is not None and scale is not None else None}

    raw = [level(s) for s in model.by_type("IfcBuildingStorey")]
    elements = []
    for cls, kind in (("IfcSpace", "room"), ("IfcSlab", "slab")):
        for entity in model.by_type(cls):
            storey = storey_of(entity)
            elements.append({"item_id": entity.GlobalId, "ifc_class": cls, "kind": kind,
                             "name": entity.Name, "storey": level(storey) if storey is not None else None,
                             "quantities": {}, "props": {}})
    folder = temporary_root / doc_id
    folder.mkdir()
    (folder / "elements.json").write_text(json.dumps({"storeys": raw, "elements": elements}))
    doc = load_doc(doc_id, temporary_root)
    question = "How many storeys are there?"
    result = solve(question, doc_id, root=temporary_root)
    jsonschema.validate(result, json.loads((ROOT / "server/schemas/answer.schema.json").read_text()))
    assert result["answer"]["value"] == len(doc.storeys) if raw else result["answer"]["abstained"]
    assert sorted(i for s in doc.storeys for i in s["source_indices"]) == list(range(len(raw)))
    assert sum(r["values"]["count"] for r in result.get("_calc", {}).get("rows", [])) == len(doc.storeys)
    assert {i for c in result["citations"] for i in c["item_ids"]} <= {e["item_id"] for e in elements}
    for s in doc.storeys:
        assert resolve_storey(f"Rooms on {s['name']}", doc.storeys) == s["name"]
    rooms = storey_compare("How many rooms per floor?", doc, time.perf_counter())
    assigned_rooms = [i for i in doc.items if i.kind == "room" and i.storey in {s["name"] for s in doc.storeys}]
    if rooms is not None:
        assert rooms["answer"]["value"] == len(assigned_rooms)
    # A normalized metre index uses the same physical tolerance for metric and
    # imperial native declarations. These variants exercise conversion only.
    canonical = canonical_storeys(raw)
    for native_m in (1, .001, .3048):
        converted = [{**s, "elevation_m": s["elevation_m"] / native_m * native_m
                      if s["elevation_m"] is not None else None} for s in raw]
        assert len(canonical_storeys(converted)) == len(canonical)
    meta = building_meta(model)
    return {"doc_id": doc_id, "path": str(path.relative_to(ROOT)), "blind": blind,
            "schema": model.schema, "applications": meta.get("applications"), "m_per_native_unit": scale,
            "native_declarations": len(raw), "distinct_storeys": len(doc.storeys),
            "duplicates_excluded": len(raw) - len(doc.storeys), "citation_item_ids":
            [i for c in result["citations"] for i in c["item_ids"]],
            "source_rows_preserved": len(raw), "assigned_rooms": len(assigned_rooms),
            "rooms_per_level_value": rooms["answer"]["value"] if rooms else None,
            "storeys": [{"name": s["name"], "elevation_m": s["elevation_m"], "source_indices": s["source_indices"]} for s in doc.storeys],
            "schema_valid": True, "all_assertions_passed": True}


def main():
    docs = ["ifc_bench__city-house-munich-arc", "ifc_bench__ac20-arc",
            "ext_ifcr2__bsi-ifc4-building-architecture", "ext_ifcr2__schep-kanaalplaat"]
    records = []
    with tempfile.TemporaryDirectory(prefix="storeys-validation-") as tmp:
        root = Path(tmp)
        for doc_id in docs:
            meta = json.loads((ROOT / "artifacts" / doc_id / "doc.json").read_text())
            relative = Path(meta["files"]["ifc"])
            path = ROOT / "data/full/junction-dataset" / relative
            if not path.exists():
                path = ROOT / relative
            records.append(validate(path, doc_id, root))
            print(doc_id, records[-1]["native_declarations"], "->", records[-1]["distinct_storeys"], flush=True)
        # This file was randomly reserved before development. Open it only now,
        # after the implementation and focused tests are complete.
        blind = json.loads((OUT / "blind.json").read_text())
        records.append(validate(ROOT / blind["path"], "blind__reserved", root, blind=True))
        print("blind", records[-1]["native_declarations"], "->", records[-1]["distinct_storeys"], flush=True)
    (OUT / "real-files.json").write_text(json.dumps({"files": records, "cost_usd": 0,
        "method": "Read native declarations/containment only; no tessellation, models, tuning or source writes."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
